import time
import random
import re
import os
import string
import threading
import json
import subprocess
import traceback
import concurrent.futures
from datetime import datetime

IS_TERMUX = "com.termux" in os.environ.get("PREFIX", "")

try:
    import requests
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains
    if not IS_TERMUX:
        import undetected_chromedriver as uc
    else:
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
except ImportError as e:
    print(f"❌ Thiếu thư viện! Lỗi: {e}")
    print("👉 Hãy mở CMD/Termux và chạy lệnh sau để cài đặt:")
    if IS_TERMUX:
        print("pip install setuptools requests selenium")
    else:
        print("pip install setuptools requests selenium undetected-chromedriver")
    input("\nNhấn Enter để thoát...")
    os._exit(1)

SAVE_FILE = "KataBump_Referrals.txt"
USAGE_FILE = "key_usage.json"
NOPECHA_KEY = "sub_1SrXPuCRwBwvt6ptmavjLF8I"

print_lock = threading.Lock()
driver_lock = threading.Lock() 
vpn_ready_event = threading.Event() 

def log(msg, prefix=">>", thread_id="Main"):
    ts = datetime.now().strftime("%H:%M:%S")
    with print_lock:
        print(f"[{ts}] [{thread_id}] {prefix} {msg}")

def check_and_update_limit(key):
    today = datetime.now().strftime("%Y-%m-%d")
    data = {}
    if os.path.exists(USAGE_FILE):
        try:
            with open(USAGE_FILE, "r") as f: data = json.load(f)
        except: pass
    if key not in data or data[key].get("date") != today:
        data[key] = {"date": today, "count": 0}
    if data[key]["count"] >= 9999:
        log("❌ Key này đã đạt giới hạn 3 lượt trong hôm nay!", "⚠️")
        return False
    data[key]["count"] += 1
    with open(USAGE_FILE, "w") as f: json.dump(data, f, indent=4)
    log(f"🔑 Lượt dùng trong ngày của Key: {data[key]['count']}/3", "✅")
    return True

def get_hwid():
    try:
        if os.name == 'nt': return subprocess.check_output('wmic csproduct get uuid').decode().split('\n')[1].strip()
        elif IS_TERMUX: return subprocess.check_output(['settings', 'get', 'secure', 'android_id']).decode().strip()
        else: return subprocess.check_output(['cat', '/etc/machine-id']).decode().strip()
    except: return "UNKNOWN_HWID_1234"

def verify_key_api(key):
    API_URL = "http://hk3.quvo.pro:15512/api/keyauth/activate"
    hwid = get_hwid()
    log(f"Đang kiểm tra Server Authentication...", "🔄")
    try:
        res = requests.post(API_URL, json={"key": key, "username": "KataBumpTool", "hwid": hwid}, timeout=10)
        data = res.json()
        if data.get("success"):
            log(f"API Xác thực thành công!", "✅")
            return True
        return False
    except: return False

def gen_string(k=7): return "".join(random.choices(string.ascii_lowercase + string.digits, k=k))
def gen_password(): return f"Kata{gen_string(5)}!@1"
def gen_name(): return random.choice(["Anh","Binh","Cuong","Dung","Ha","Tuan","Nam"]), random.choice(["Nguyen","Tran","Le","Pham","Vu"])

def create_email(thread_id):
    providers = ["https://api.mail.gw", "https://api.mail.tm"]
    random.shuffle(providers)
    
    for base in providers:
        try:
            r = requests.get(f"{base}/domains", timeout=15)
            doms = [d["domain"] for d in r.json().get("hydra:member", []) if d.get("isActive")]
            if not doms: continue
            
            addr = f"kref{gen_string(6)}@{random.choice(doms)}"
            pw = gen_password()
            
            if requests.post(f"{base}/accounts", json={"address": addr, "password": pw}, timeout=15).status_code in [200, 201]:
                tok = requests.post(f"{base}/token", json={"address": addr, "password": pw}, timeout=15)
                return {"address": addr, "password": pw, "token": tok.json().get("token"), "base": base}
        except:
            continue
    return None

def get_otp(acc, thread_id):
    hdrs = {"Authorization": f"Bearer {acc['token']}"}
    for _ in range(30):
        try:
            r = requests.get(f"{acc['base']}/messages", headers=hdrs, timeout=10)
            msgs = r.json().get("hydra:member", [])
            if msgs:
                dr = requests.get(f"{acc['base']}/messages/{msgs[0]['id']}", headers=hdrs, timeout=10)
                content = str(dr.json())
                match = re.search(r'(?<!\d)\d{6}(?!\d)', content)
                if match: return match.group(0)
        except: pass
        time.sleep(3)
    return None

# ĐOẠN JS ĐÁNH LỪA TRÌNH DUYỆT LUÔN LUÔN ACTIVE (KHÔNG CẦN FOCUS TAB)
ANTI_BLUR_JS = """
    Object.defineProperty(document, 'hidden', {get: function() {return false;}});
    Object.defineProperty(document, 'visibilityState', {get: function() {return 'visible';}});
    document.hasFocus = function() {return true;};
    window.addEventListener('blur', function(e) { e.stopImmediatePropagation(); }, true);
"""

def setup_persistent_driver(thread_id):
    with driver_lock: 
        if IS_TERMUX:
            options = Options()
            options.add_argument("--headless=new") # Dùng headless engine mới của Chrome
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            # Ép Termux có màn hình 1080p và giả mạo User-Agent của Windows để qua mặt Cloudflare
            options.add_argument("--window-size=1920,1080")
            options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            
            # Cố định Path cho Termux để khỏi báo lỗi no chrome binary
            chrome_bin = "/data/data/com.termux/files/usr/bin/chromium-browser"
            if not os.path.exists(chrome_bin): 
                chrome_bin = "/data/data/com.termux/files/usr/bin/chromium"
                
            options.binary_location = chrome_bin
            service = Service(executable_path="/data/data/com.termux/files/usr/bin/chromedriver")
            
            try: 
                driver = webdriver.Chrome(service=service, options=options)
                driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": ANTI_BLUR_JS})
                return driver
            except Exception as e:
                log(f"Lỗi khởi động Termux: {str(e)[:60]}", "❌", thread_id)
                log(f"Bác thử chạy lại lệnh này xem: pkg install tur-repo -y && pkg install chromium -y", "💡", thread_id)
                return None
        else:
            options = uc.ChromeOptions()
            options.add_argument("--disable-popup-blocking")
            options.add_argument("--disable-blink-features=AutomationControlled")
            
            profile_dir = os.path.join(os.getcwd(), f"BotProfile_{thread_id}")
            options.add_argument(f"--user-data-dir={profile_dir}")
            
            try:
                driver = uc.Chrome(options=options)
                driver.set_window_size(800, 600)
                driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": ANTI_BLUR_JS})
                return driver
            except Exception as e:
                log(f"Lỗi khởi tạo Chrome PC: {str(e)[:40]}", "❌", thread_id)
                return None

def clear_browser_data(driver):
    try:
        driver.get("https://dashboard.katabump.com/404")
        driver.delete_all_cookies()
        driver.execute_script("window.localStorage.clear(); window.sessionStorage.clear();")
    except: pass

def human_type(element, text):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.01, 0.05))

def solve_turnstile_v20(driver, url, step_name="", thread_id="1"):
    try:
        time.sleep(4) 
        try:
            cf_input = driver.find_element(By.NAME, "cf-turnstile-response")
            if cf_input.get_attribute("value"): return True
        except: pass

        # BƯỚC 1: CỐ GẮNG CLICK THỦ CÔNG QUA CDP (HOẠT ĐỘNG TRÊN CẢ TERMUX LẪN PC CHẠY NGẦM)
        try:
            iframe = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'turnstile') or contains(@src, 'cloudflare')]"))
            )
            # Cuộn nó ra giữa màn hình để lấy toạ độ chuẩn
            driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'instant'});", iframe)
            time.sleep(1) 
            
            rect = driver.execute_script("return arguments[0].getBoundingClientRect();", iframe)
            # Tính tâm điểm của iframe
            x = int(rect['x'] + rect['width'] / 2) + random.randint(-2, 2)
            y = int(rect['y'] + rect['height'] / 2) + random.randint(-2, 2)

            # Bắn tín hiệu chuột cực sâu ở cấp độ protocol (không quan tâm tab bị ẩn hay Termux headless)
            driver.execute_cdp_cmd('Input.dispatchMouseEvent', {'type': 'mousePressed', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})
            time.sleep(random.uniform(0.05, 0.15))
            driver.execute_cdp_cmd('Input.dispatchMouseEvent', {'type': 'mouseReleased', 'x': x, 'y': y, 'button': 'left', 'clickCount': 1})

            for i in range(6):
                time.sleep(1.5)
                try:
                    if driver.find_element(By.NAME, "cf-turnstile-response").get_attribute("value"): 
                        log(f"Bypass {step_name} thủ công THÀNH CÔNG!", "🎯", thread_id)
                        return True
                except: pass
        except: pass
        
        # BƯỚC 2: FALLBACK SANG API NẾU CLICK THỦ CÔNG XỊT (HOẶC IP BỊ CLOUDFLARE ĐÁNH DẤU XẤU QUÁ CẦN CAPTCHA ẢNH)
        try:
            element = driver.find_element(By.CSS_SELECTOR, "[data-sitekey]")
            sitekey = element.get_attribute("data-sitekey")
            req_data = {"key": NOPECHA_KEY, "type": "turnstile", "sitekey": sitekey, "url": url}
            res_post = requests.post("https://api.nopecha.com/token/", json=req_data, timeout=10).json()
            if "data" not in res_post: return False
                
            job_id = res_post["data"]
            log(f"Click thủ công kẹt, nhờ API NopeCHA giải cứu...", "🤖", thread_id)
            
            token = None
            for _ in range(5): 
                time.sleep(2)
                try:
                    res_get = requests.get(f"https://api.nopecha.com/token/?key={NOPECHA_KEY}&id={job_id}", timeout=5).json()
                    if "data" in res_get and res_get["data"]:
                        token = res_get["data"]
                        break
                except: pass
                    
            if not token: return False
                
            inject_js = "var token=arguments[0];var cf_input=document.querySelector('input[name=\"cf-turnstile-response\"]');if(cf_input){cf_input.value=token;cf_input.dispatchEvent(new Event('input',{bubbles:true}));cf_input.dispatchEvent(new Event('change',{bubbles:true}));}var tsEl=document.querySelector('[data-sitekey]');if(tsEl&&tsEl.hasAttribute('data-callback')){var cbName=tsEl.getAttribute('data-callback');if(typeof window[cbName]==='function'){window[cbName](token);}}"
            
            driver.execute_script(inject_js, token)
            time.sleep(2)
            return True
        except: return False
    except: return False

def auto_create_server(driver, thread_id="1"):
    target_url = "https://dashboard.katabump.com/servers/create"
    for attempt in range(1, 3):
        try:
            driver.get(target_url)
            time.sleep(4) 
            wait = WebDriverWait(driver, 10)
            
            try:
                name_input = wait.until(EC.presence_of_element_located((By.XPATH, "//input[@type='text']")))
                human_type(name_input, f"Node-{gen_string(6)}")
            except: pass
                
            try:
                time.sleep(1)
                for cb in driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']"):
                    driver.execute_script("arguments[0].click();", cb)
            except: pass
            
            if not solve_turnstile_v20(driver, target_url, f"(Tạo Server)", thread_id):
                continue
            
            try:
                btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Create') or contains(text(), 'create')]")
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                time.sleep(1)
                ActionChains(driver).move_to_element(btn).click().perform()
            except: pass
                
            time.sleep(5)
            if "error=captcha" in driver.current_url: continue 
            log("Tạo Server phụ xong!", "⚙️", thread_id)
            return True
        except: pass
    return False

def run_referral_loop(ref_link, thread_id):
    ref_code = ref_link.split("#")[-1] if "#" in ref_link else ref_link
    target_url = f"https://dashboard.katabump.com/auth/register#{ref_code}"
    
    log(f"Đang khởi động trình duyệt...", "🚀", thread_id)
    driver = setup_persistent_driver(thread_id)
    
    log("Đợi lệnh chạy từ bác...", "⏳", thread_id)
    vpn_ready_event.wait() 
    
    success_count = 0
    
    while True: 
        try:
            if driver is None: 
                driver = setup_persistent_driver(thread_id)
            
            if driver is None:
                log("Trình duyệt không thể chạy! Đang thử kết nối lại sau 5s...", "🛑", thread_id)
                time.sleep(5)
                continue 

            driver.current_url 
        except Exception:
            log("Cửa sổ Chrome bị văng/mất kết nối! Đang tự động mở lại cái mới...", "🔄", thread_id)
            try: driver.quit()
            except: pass
            driver = setup_persistent_driver(thread_id)
            time.sleep(2)
            continue 

        try:
            clear_browser_data(driver)
            driver.set_page_load_timeout(60) 
            driver.get(target_url)
            wait = WebDriverWait(driver, 15)
            
            log("Đang tạo mail ảo...", "📧", thread_id)
            acc = create_email(thread_id)
            if not acc: raise Exception("Hết mail ảo")
                
            email = acc["address"]; password = gen_password(); fname, lname = gen_name()
            
            human_type(wait.until(EC.presence_of_element_located((By.ID, "firstname"))), fname)
            human_type(driver.find_element(By.ID, "lastname"), lname)
            human_type(driver.find_element(By.ID, "email"), email)
            human_type(driver.find_element(By.ID, "password"), password)
            
            try: human_type(driver.find_element(By.ID, "username"), f"{fname.lower()}{lname.lower()}{gen_string(3)}")
            except: pass

            try: human_type(driver.find_element(By.XPATH, "//input[@id='password_confirmation' or @name='password_confirmation']"), password)
            except: pass

            try:
                ref_el = driver.find_element(By.XPATH, "//input[contains(@name, 'referral') or contains(@id, 'referral')]")
                if not ref_el.get_attribute('value'): human_type(ref_el, ref_code)
            except: pass

            try: 
                for cb in driver.find_elements(By.CSS_SELECTOR, "input[type='checkbox']"):
                    if not cb.is_selected(): driver.execute_script("arguments[0].click();", cb)
            except: pass

            log("Xử lý Captcha...", "🔍", thread_id)
            if not solve_turnstile_v20(driver, target_url, "(Đăng Ký)", thread_id):
                raise Exception("Trượt Captcha")

            try:
                btn = driver.find_element(By.XPATH, "//button[@type='submit']")
                ActionChains(driver).move_to_element(btn).click().perform()
            except: pass
            
            log("Trực chờ OTP...", "📩", thread_id)
            otp = get_otp(acc, thread_id)
            if not otp: raise Exception("OTP không về")
            
            try:
                otp_box = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//input[contains(@placeholder, 'Code') or @type='text' or @maxlength]")))
                human_type(otp_box, otp)
                time.sleep(1)
                try: driver.find_element(By.XPATH, "//button[contains(text(), 'Verify')]").click()
                except: otp_box.send_keys(Keys.ENTER)
            except:
                raise Exception("Trang web lag không điền được OTP")
            
            time.sleep(5)
            if "dashboard" in driver.current_url:
                success_count += 1
                log(f"✅ ĐÃ ĂN REF THÀNH CÔNG! (Tổng: {success_count})", "🎉", thread_id)
                with open(SAVE_FILE, "a") as f: f.write(f"{email}|{password}|{ref_code}\n")
                auto_create_server(driver, thread_id)
                
            time.sleep(3)
            
        except Exception as e:
            err_log = str(e).split('\n')[0][:40]
            if "no such window" in err_log.lower() or "disconnected" in err_log.lower():
                driver = None 
                continue
                
            log(f"Kẹt ({err_log}...) -> Đang F5 chạy lại!", "🔄", thread_id)
            time.sleep(3)
            continue 

def main():
    os.system("cls" if os.name == "nt" else "clear")
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║     KATABUMP AUTO REFERRAL (V22) - MULTI THREADS EDITION         ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    
    key = input("\n🔑 Nhập License Key: ").strip()
    if not verify_key_api(key) or not check_and_update_limit(key): return
        
    print("\n=== CHỌN CHẾ ĐỘ MULTI ===")
    print("1. Multi 1 Link Ref (Nhiều tab cùng cày 1 acc chính)")
    print("2. Multi nhiều Link Ref (Mỗi tab cày 1 link ref khác nhau)")
    mode = input("👉 Nhập lựa chọn (1/2): ").strip()

    links = []
    threads = 1
    
    if mode == "1":
        ref_link = input("\n🔗 Nhập link Referral gốc: ").strip()
        threads = int(input("⚙️ Nhập số luồng (tab) muốn chạy (Khuyến nghị 2-3): ").strip())
        links = [ref_link] * threads
    elif mode == "2":
        print("\n🔗 Nhập các link Referral (Mỗi link 1 dòng, gõ 'XONG' để kết thúc):")
        while True:
            link = input().strip()
            if link.upper() == 'XONG': break
            if link: links.append(link)
        threads = len(links)
        if threads == 0: return

    print(f"\n🚀 Đang nổ máy chạy {threads} luồng...")
    threads_list = []
    for i, link in enumerate(links):
        t = threading.Thread(target=run_referral_loop, args=(link, f"T{i+1}"))
        t.daemon = True 
        t.start()
        threads_list.append(t)
        time.sleep(1) 

    print(f"\n{'-'*65}")
    if IS_TERMUX:
        print("👉 ĐIỆN THOẠI: Bác hãy bật app VPN và kết nối.")
    else:
        print("👉 PC: CHROME ĐÃ MỞ! Bác cài/bật VPN trên tab hoặc bật VPN toàn máy tính đi.")
    input("🛑 Bấm [ENTER] tại đây khi bác đã BẬT VPN XONG ĐỂ BẮT ĐẦU CHẠY...")
    print(f"{'-'*65}\n")

    vpn_ready_event.set() 
    
    for t in threads_list:
        t.join()

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt:
        print("\nĐã dừng phần mềm!")
    except Exception as e:
        print(f"\n❌ Lỗi nghiêm trọng: {e}")
        traceback.print_exc()
        input("\nNhấn Enter để thoát...")
