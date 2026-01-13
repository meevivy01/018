import time
import pandas as pd
import undetected_chromedriver as uc
import os
import datetime
import re
import random
import yaml
import json
import smtplib
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException, ElementClickInterceptedException
from selenium.webdriver.common.action_chains import ActionChains
from dotenv import load_dotenv
from thefuzz import fuzz 
from dateutil.relativedelta import relativedelta 
import logging
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn, TimeElapsedColumn, TaskProgressColumn
from rich.theme import Theme

# --- SETUP & CONFIG ---
try:
    from fake_useragent import UserAgent
except ImportError:
    UserAgent = None

logging.getLogger("fake_useragent").setLevel(logging.CRITICAL)

def suppress_del_error(self):
    try: self.quit()
    except Exception: pass
uc.Chrome.__del__ = suppress_del_error

ENV_PATH = "User.env"
COMPETITORS_PATH = "compe.yaml"
CLIENTS_PATH = "co.yaml"
TIER1_PATH = "tier1.yaml"
RESUME_IMAGE_FOLDER = "resume_images" 
USE_HEADLESS_JOBTHAI = False # 🟢 ปรับเป็น False เพื่อใช้ Xvfb
EMAIL_USE_HISTORY = False        

rec_env = os.getenv("EMAIL_RECEIVER")
MANUAL_EMAIL_RECEIVERS = [rec_env] if rec_env else []

custom_theme = Theme({"info": "dim cyan", "warning": "yellow", "error": "bold red", "success": "bold green"})
console = Console(theme=custom_theme)

load_dotenv(ENV_PATH, override=True)
MY_USERNAME = os.getenv("JOBTHAI_USER")
MY_PASSWORD = os.getenv("JOBTHAI_PASS")

G_SHEET_KEY_JSON = os.getenv("G_SHEET_KEY")
G_SHEET_NAME = os.getenv("G_SHEET_NAME")

TIER1_TARGETS = {}
if os.path.exists(TIER1_PATH):
    try:
        with open(TIER1_PATH, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)
            if yaml_data:
                for k, v in yaml_data.items():
                    if v:
                        if isinstance(v, list): TIER1_TARGETS[k] = [str(x).strip() for x in v]
                        else: TIER1_TARGETS[k] = [str(v).strip()]
    except Exception as e: console.print(f"⚠️ Load Tier1 Error: {e}", style="yellow")

TARGET_COMPETITORS_TIER2 = [] 
if os.path.exists(COMPETITORS_PATH):
    try:
        with open(COMPETITORS_PATH, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)
            if yaml_data and 'competitors' in yaml_data:
                TARGET_COMPETITORS_TIER2 = [str(x).strip() for x in yaml_data['competitors'] if x]
    except: pass

CLIENTS_TARGETS = {}
if os.path.exists(CLIENTS_PATH):
    try:
        with open(CLIENTS_PATH, "r", encoding="utf-8") as f:
            CLIENTS_TARGETS = yaml.safe_load(f) or {}
            for k in list(CLIENTS_TARGETS.keys()):
                if not CLIENTS_TARGETS[k]: del CLIENTS_TARGETS[k]
                elif not isinstance(CLIENTS_TARGETS[k], list): CLIENTS_TARGETS[k] = [str(CLIENTS_TARGETS[k])]
    except: pass

# --- TARGET CONFIG ---
TARGET_UNIVERSITIES = ["หัวเฉียว"," Huachiew"]  
TARGET_FACULTIES = ["เครื่องสำอาง","Cosmetic Science"] 
TARGET_MAJORS = ["เครื่องสำอาง", "วิทยาศาสตร์เครื่องสำอาง","Cosmetic Science", "Cosmetics", "Cosmetic"]
SEARCH_KEYWORDS = ["หัวเฉียว เครื่องสำอาง","Cosmetic Huachiew"]


KEYWORDS_CONFIG = {
    "NPD": {"titles": ["NPD", "R&D", "RD", "Research", "Development", "วิจัย", "พัฒนา", "Formulation", "สูตร"]},
    "PCM": {"titles": ["PCM", "Production", "ผลิต", "Manufacturing", "Factory", "โรงงาน", "QA", "QC"]},
    "Sales": {"titles": ["Sale", "Sales", "ขาย", "AE", "BD", "Customer", "Telesale"]},
    "MKT": {"titles": ["MKT", "Marketing", "การตลาด", "Digital", "Content", "Media", "Ads"]},
    "Admin": {"titles": ["Admin", "ธุรการ", "ประสานงาน", "Coordinator", "Document", "เอกสาร"]},
    "HR": {"titles": ["HR", "Recruit", "สรรหา", "บุคคล", "Training", "Payroll"]},
    "SCM": {"titles": ["SCM", "Supply Chain", "Logistic", "ขนส่ง", "Warehouse", "Stock", "Import", "Export"]},
    "PUR": {"titles": ["PUR", "Purchase", "จัดซื้อ", "Sourcing", "Buyer"]},
    "DATA": {"titles": ["Data", "ข้อมูล", "Analyst", "Statistic", "สถิติ"]},
    "Present": {"titles": ["Present", "Speaker", "วิทยากร", "Trainer"]},
    "IT": {"titles": ["IT", "Computer", "Software", "Programmer", "Developer"]},
    "RA": {"titles": ["RA", "Regulatory", "อย.", "FDA", "ขึ้นทะเบียน"]},
    "ACC": {"titles": ["ACC", "Account", "บัญชี", "Finance", "การเงิน", "Audit"]}
}

def analyze_row_department(row):
    scores = {dept: 0 for dept in KEYWORDS_CONFIG.keys()}
    target_cols = ['ตำแหน่งที่ต้องการสมัคร_1', 'ตำแหน่งที่ต้องการสมัคร_2', 'ตำแหน่งที่ต้องการสมัคร_3']
    for col in target_cols:
        if col not in row or pd.isna(row[col]): continue
        text_val = str(row[col]).lower()
        for dept, config in KEYWORDS_CONFIG.items():
            for keyword in config['titles']:
                if keyword.lower() in text_val:
                    scores[dept] += 33
                    break 
    if not scores: return pd.Series(["Uncategorized", 0, ""])
    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_dept, max_score = sorted_scores[0]
    return pd.Series([best_dept, int(min(max_score, 100)), ", ".join([f"{k}({v})" for k, v in sorted_scores if v > 0])])

class JobThaiRowScraper:
    def __init__(self):
        console.rule("[bold cyan]🛡️ JobThai Scraper (GitHub Actions Optimized)[/]")
        self.history_file = "notification_history_uni.json" 
        self.history_data = {}
        if not os.path.exists(RESUME_IMAGE_FOLDER): os.makedirs(RESUME_IMAGE_FOLDER, exist_ok=True)
        
        if EMAIL_USE_HISTORY and os.path.exists(self.history_file):
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f: self.history_data = json.load(f)
            except: self.history_data = {}

        # --- Driver Configuration ---
        opts = uc.ChromeOptions()
        
        opts.add_argument('--window-size=1920,1080')
        opts.add_argument("--no-sandbox") 
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-popup-blocking")
        opts.add_argument("--disable-gpu") 
        opts.add_argument("--lang=th-TH")
        
        # ✅ ใช้ Static User Agent (ไม่ต้องสุ่มแล้ว เพื่อให้ Cookie ไม่หลุด)
        my_static_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        opts.add_argument(f'--user-agent={my_static_ua}')

        try:
            self.driver = uc.Chrome(options=opts, version_main=None) 
        except Exception as e:
            console.print(f"⚠️ Driver Init Fail (Retry): {e}", style="yellow")
            self.driver = uc.Chrome(options=opts)
        
        self.driver.set_page_load_timeout(60) 
        self.wait = WebDriverWait(self.driver, 20)
        self.total_profiles_viewed = 0 
        self.all_scraped_data = []
        
        # กำหนดค่า self.ua เป็น None กันเหนียวไว้ก่อน (แม้จะไม่ใช้แล้วก็ตาม)
        self.ua = None 

    def save_history(self):
        if not EMAIL_USE_HISTORY: return
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f: json.dump(self.history_data, f, ensure_ascii=False, indent=4)
        except: pass

    # 🔴 จุดที่แก้: เปลี่ยนให้ฟังก์ชันนี้ไม่ทำอะไรเลย (pass) เพราะเราใช้ User Agent แบบ Fixed แล้ว
    def set_random_user_agent(self):
        pass 

    def random_sleep(self, min_t=4.0, max_t=7.0): time.sleep(random.uniform(min_t, max_t))

    def wait_for_page_load(self, timeout=10):
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except: pass

    def safe_click(self, selector, by=By.XPATH, timeout=10):
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                element = WebDriverWait(self.driver, 2).until(EC.presence_of_element_located((by, selector)))
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                time.sleep(0.5)
                element.click()
                return True
            except ElementClickInterceptedException:
                try:
                    element = self.driver.find_element(by, selector)
                    self.driver.execute_script("arguments[0].click();", element)
                    return True
                except: pass
            except: pass
            time.sleep(1)
        return False

    def safe_type(self, selector, text, by=By.CSS_SELECTOR, timeout=10):
        try:
            element = WebDriverWait(self.driver, timeout).until(EC.element_to_be_clickable((by, selector)))
            try:
                element.click()
                element.clear()
            except: pass
            try:
                element.send_keys(text)
            except:
                self.driver.execute_script("arguments[0].value = arguments[1];", element, text)
            return True
        except: return False

    def human_scroll(self):
        try:
            total_height = self.driver.execute_script("return document.body.scrollHeight")
            current_position = 0
            while current_position < total_height:
                scroll_step = random.randint(300, 700)
                current_position += scroll_step
                self.driver.execute_script(f"window.scrollTo(0, {current_position});")
                time.sleep(random.uniform(0.1, 0.4))
            time.sleep(0.5)
            self.driver.execute_script("window.scrollTo(0, 0);")
        except: pass

    def parse_thai_date_exact(self, date_str):
        if not date_str: return None
        thai_months = {'มกราคม': 1, 'กุมภาพันธ์': 2, 'มีนาคม': 3, 'เมษายน': 4, 'พฤษภาคม': 5, 'มิถุนายน': 6, 'กรกฎาคม': 7, 'สิงหาคม': 8, 'กันยายน': 9, 'ตุลาคม': 10, 'พฤศจิกายน': 11, 'ธันวาคม': 12}
        try:
            date_str = date_str.strip()
            parts = date_str.split() 
            if len(parts) < 3: return None
            day = int(parts[0])
            month = thai_months.get(parts[1])
            year_be = int(parts[2])
            year_ad = year_be - 543
            return datetime.date(year_ad, month, day)
        except: return None

    def calculate_duration_text(self, date_range_str):
        if not date_range_str: return ""
        thai_months = {'มกราคม': 1, 'กุมภาพันธ์': 2, 'มีนาคม': 3, 'เมษายน': 4, 'พฤษภาคม': 5, 'มิถุนายน': 6, 'กรกฎาคม': 7, 'สิงหาคม': 8, 'กันยายน': 9, 'ตุลาคม': 10, 'พฤศจิกายน': 11, 'ธันวาคม': 12}
        try:
            clean_str = " ".join(date_range_str.split())
            if '-' not in clean_str: return ""
            start_str, end_str = clean_str.split('-')
            def parse_thai_date(d_str):
                d_str = d_str.strip()
                if "ปัจจุบัน" in d_str: return datetime.datetime.now()
                parts = d_str.split()
                if len(parts) < 2: return None
                m = thai_months.get(parts[0])
                if not m: return None
                y = int(parts[1]) - 543
                return datetime.datetime(y, m, 1)
            s_date = parse_thai_date(start_str)
            e_date = parse_thai_date(end_str)
            if s_date and e_date:
                diff = relativedelta(e_date, s_date)
                txt = []
                if diff.years > 0: txt.append(f"{diff.years} ปี")
                if diff.months > 0: txt.append(f"{diff.months} เดือน")
                return " ".join(txt) if txt else "น้อยกว่า 1 เดือน"
            return ""
        except: return ""

    # ==============================================================================
    # 🔥 STEP 1: LOGIN (Xvfb Supported - กดปุ่มได้ชัวร์กว่า)
    # ==============================================================================
    def step1_login(self):
        login_url = "https://www.jobthai.com/th/employer"
        max_retries = 5 
        
        for attempt in range(1, max_retries + 1):
            console.rule(f"[bold cyan]🔐 Login Attempt {attempt}/{max_retries} (Xvfb Mode)[/]")
            
            try:
                if attempt > 1:
                    console.print("   🔄 Refreshing...", style="yellow")
                    try: self.driver.refresh()
                    except: pass
                    self.wait_for_page_load()
                    self.random_sleep(5, 7)
                else:
                    self.driver.set_window_size(1920, 1080)
                    self.driver.get(login_url)
                    self.wait_for_page_load()
                    self.random_sleep(4, 5)

                try:
                    self.driver.execute_script("var blockers=document.querySelectorAll('#close-button,.cookie-consent,[class*=\"pdpa\"],[class*=\"popup\"]');blockers.forEach(b=>b.remove());")
                except: pass

                # 3. Navigation (ActionChains = Human Mouse)
                # เมื่อรันบน Xvfb เราสามารถใช้ ActionChains ได้เต็มประสิทธิภาพ
                try:
                    # A. กดปุ่มเมนู
                    if not self.driver.find_elements(By.CSS_SELECTOR, "input[type='password']"):
                        menu_sels = ['#menu-jobseeker-login', 'a[href*="login"]']
                        for sel in menu_sels:
                            try:
                                elm = WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                                ActionChains(self.driver).move_to_element(elm).click().perform()
                                console.print(f"   🖱️ กดเมนูสำเร็จ: {sel}", style="dim")
                                break
                            except: continue
                        self.random_sleep(4, 6)
                    
                    # B. กดแท็บ Employer
                    tab_selectors = ['#login_tab_employer', 'li[data-tab="employer"]']
                    for sel in tab_selectors:
                        try:
                            t_elm = WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                            ActionChains(self.driver).move_to_element(t_elm).click().perform()
                            console.print("   👉 กดแท็บ Employer สำเร็จ", style="dim")
                            break
                        except: continue
                    time.sleep(5) 

                except Exception as e:
                    console.print(f"   ⚠️ Navigation Warning: {e}", style="dim")

                # 4. Input Scan
                user_input_found = False
                user_sels = ["#login-form-username", "input[name='username']", "input[type='email']"]
                pass_sels = ["#login-form-password", "input[name='password']", "input[type='password']"]

                def scan_and_fill():
                    for us in user_sels:
                        if self.safe_type(us, MY_USERNAME, By.CSS_SELECTOR, timeout=3):
                            for ps in pass_sels:
                                if self.safe_type(ps, MY_PASSWORD, By.CSS_SELECTOR, timeout=2):
                                    try: 
                                        self.driver.find_element(By.CSS_SELECTOR, ps).send_keys(Keys.ENTER)
                                    except: pass
                                    return True
                    return False

                if scan_and_fill():
                    user_input_found = True
                else:
                    iframes = self.driver.find_elements(By.TAG_NAME, "iframe")
                    if iframes:
                        console.print(f"   👀 สแกน {len(iframes)} Iframes...", style="dim")
                        for frame in iframes:
                            try:
                                self.driver.switch_to.default_content()
                                self.driver.switch_to.frame(frame)
                                if scan_and_fill():
                                    console.print("   ✅ เจอช่องใน Iframe!", style="success")
                                    user_input_found = True
                                    break
                            except: continue
                        if not user_input_found: self.driver.switch_to.default_content()

                # 5. Check Success
                if user_input_found:
                    console.print("   📝 กรอกแล้ว รอตรวจสอบ...", style="info")
                    for _ in range(60):
                        time.sleep(1)
                        if "auth.jobthai.com" not in self.driver.current_url and "login" not in self.driver.current_url:
                            console.print(f"🎉 Login สำเร็จ! (รอบที่ {attempt})", style="bold green")
                            return True
                
                console.print(f"   ❌ รอบที่ {attempt} ล้มเหลว", style="bold red")
                self.driver.save_screenshot(f"xvfb_fail_attempt_{attempt}.png")

            except Exception as e:
                console.print(f"   ⚠️ Error รอบที่ {attempt}: {e}", style="warning")
        
        console.print("🔄 ใช้แผนสำรอง Cookie Bypass...", style="bold yellow")
        return self.login_with_cookie()

    def login_with_cookie(self):
        cookies_env = os.getenv("COOKIES_JSON")
        if not cookies_env: 
            console.print("❌ ไม่พบ COOKIES_JSON", style="error")
            return False
            
        try:
            console.print("🍪 กำลังโหลด Cookie...", style="info")
            
            # 1. เข้าหน้าเว็บเปล่าๆ ของ Domain นั้นก่อน (สำคัญมาก เพื่อให้ Domain scope ตรงกัน)
            self.driver.get("https://www.jobthai.com/th/employer")
            self.random_sleep(2, 3)
            
            # 2. ลบ Cookie เดิมที่ติดมากับ Session ใหม่ทิ้งให้หมด
            self.driver.delete_all_cookies()
            
            # 3. แปลงและยัด Cookie
            cookies_list = json.loads(cookies_env)
            for cookie in cookies_list:
                # คัดเฉพาะ Key ที่ Selenium รองรับ (ถ้าเอา key แปลกๆ ไปด้วย จะ Error)
                cookie_dict = {
                    'name': cookie.get('name'),
                    'value': cookie.get('value'),
                    'domain': cookie.get('domain'), # สำคัญ: ต้องตรงกับเว็บที่เปิด
                    'path': cookie.get('path', '/'),
                    # 'secure': cookie.get('secure', False), # บางทีใส่ Secure แล้วพัง ถ้าเว็บไม่ strict ให้ comment ออก
                    # 'expiry': cookie.get('expirationDate') # ไม่ต้องใส่ expiry ก็ได้ ถ้าอยากให้เป็น Session Cookie
                }
                
                # Fix Domain: บางที Cookie มาเป็น .jobthai.com แต่เราเข้า www.jobthai.com
                # ให้ตัดจุดข้างหน้าออกเพื่อความชัวร์
                if 'jobthai' in str(cookie_dict['domain']):
                    try:
                        self.driver.add_cookie(cookie_dict)
                    except Exception as e:
                        # ถ้า add ไม่เข้า ข้ามไป (บางอันเป็น 3rd party cookie)
                        pass
            
            console.print("   ✅ ยัด Cookie เสร็จแล้ว -> Refresh หน้าจอ", style="dim")
            
            # 4. Refresh เพื่อให้ Cookie ทำงาน
            self.driver.refresh()
            self.wait_for_page_load()
            self.random_sleep(3, 5)

            # 5. เช็คว่าเข้าได้จริงไหม
            if "login" not in self.driver.current_url and "dashboard" in self.driver.current_url:
                console.print("🎉 Bypass Login สำเร็จด้วย Cookie!", style="success")
                return True
            else:
                # ลองไปหน้า Resume โดยตรงอีกทีเพื่อความชัวร์
                self.driver.get("https://www3.jobthai.com/findresume/findresume.php?l=th")
                self.random_sleep(2, 3)
                if "login" not in self.driver.current_url:
                     console.print("🎉 Bypass Login สำเร็จ! (Check Step 2)", style="success")
                     return True

        except Exception as e:
            console.print(f"❌ Cookie Error: {e}", style="error")
        
        return False

    def step2_search(self, keyword):
        search_url = "https://www3.jobthai.com/findresume/findresume.php?l=th"
        console.print(f"2️⃣   ค้นหา: '[bold]{keyword}[/]' ...", style="info")
        
        try:
            reset_success = False
            try:
                if self.safe_click('//*[@id="company-search-resume"]', By.XPATH, timeout=5):
                    reset_success = True
                    self.wait_for_page_load()
                    self.random_sleep(3, 5)
            except: pass
            
            if not reset_success:
                self.driver.get(search_url)
                self.wait_for_page_load()
                self.random_sleep(3, 5)

            kw_element = WebDriverWait(self.driver, 20).until(EC.presence_of_element_located((By.ID, "KeyWord")))
            self.driver.execute_script("arguments[0].value = '';", kw_element)
            time.sleep(0.5)
            self.driver.execute_script("arguments[0].value = arguments[1];", kw_element, keyword)
            console.print(f"   ✍️ พิมพ์ '{keyword}' เรียบร้อย", style="dim")
            time.sleep(1)
            
            if not self.safe_click('buttonsearch', By.ID):
                search_btn = self.driver.find_element(By.ID, "buttonsearch")
                self.driver.execute_script("arguments[0].click();", search_btn)
            
            console.print("   🔍 รอผลลัพธ์...", style="dim")
            time.sleep(5) 

            # 🟢 [แก้] เช็ค 0 Results ให้แม่นขึ้น (ดูที่เนื้อหา ไม่ใช่ Source รวม)
            try:
                no_data = self.driver.find_elements(By.XPATH, "//*[contains(text(), 'ไม่พบข้อมูล') or contains(text(), 'No data found')]")
                if no_data and no_data[0].is_displayed():
                    console.print(f"   ⚠️ ไม่พบข้อมูล (0 Results) สำหรับ: {keyword}", style="warning")
                    return True 
            except: pass

            try:
                WebDriverWait(self.driver, 15).until(lambda d: "ResumeDetail" in d.page_source or "KeyWord" in d.current_url)
                console.print(f"   ✅ เจอผลการค้นหา!", style="success")
                return True
            except:
                console.print("   ❌ Timeout: หน้าเว็บไม่เปลี่ยน", style="error")
                return False

        except Exception as e:
            console.print(f"❌ Search Error ({keyword}): {e}", style="error")
            return False

    def step3_collect_all_links(self):
        collected_links = []
        page_num = 1
        console.rule("[bold yellow]3️⃣  โหมดเก็บลิงก์[/]")
        
        while True:
            console.print(f"   📄 หน้าที่ {page_num}...", style="info")
            try:
                try: WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, 'ResumeDetail')]")))
                except: pass 
                
                all_anchors = self.driver.find_elements(By.XPATH, "//a[contains(@href, 'ResumeDetail') or contains(@href, '/resume/')]")
                
                count_before = len(collected_links)
                for a in all_anchors:
                    try:
                        href = a.get_attribute("href")
                        if href and href not in collected_links:
                            collected_links.append(href)
                    except: continue
                
                new_count = len(collected_links) - count_before
                console.print(f"      -> เก็บเพิ่ม: {new_count} (รวม {len(collected_links)})", style="success")

            except Exception as e:
                console.print(f"      ❌ Error เก็บลิงก์: {e}", style="error")

            if len(collected_links) == 0: break
            if new_count == 0: break

            try:
                next_btn_xpath = '//*[@id="content-l"]/div[2]/div[1]/table/tbody/tr/td[8]/a'
                next_btns = self.driver.find_elements(By.XPATH, next_btn_xpath)
                if next_btns and next_btns[0].is_displayed():
                    self.driver.execute_script("arguments[0].click();", next_btns[0])
                    page_num += 1
                    time.sleep(3)
                    self.wait_for_page_load()
                else: break
            except: break
            
        console.print(f"[bold green]📦 สรุปยอดรวม: {len(collected_links)} ลิงก์[/]")
        return collected_links

    def scrape_detail_from_json(self, url, keyword, progress_console=None):
        printer = progress_console if progress_console else console
        self.set_random_user_agent()
        
        max_retries = 3
        load_success = False
        for attempt in range(max_retries):
            try:
                self.driver.get(url)
                self.wait_for_page_load()
                load_success = True
                break 
            except: self.random_sleep(5, 10)

        if not load_success: return None, 999, None
        
        try: self.human_scroll() 
        except: pass
        self.random_sleep(2.0, 5.0)
        
        data = {'Link': url}
        try: full_text = self.driver.find_element(By.CSS_SELECTOR, "#mainTableTwoColumn").text
        except: full_text = ""
        
        def get_val(sel, xpath=False):
            try:
                elem = self.driver.find_element(By.XPATH, sel) if xpath else self.driver.find_element(By.CSS_SELECTOR, sel)
                return elem.text.strip()
            except: return ""

        edu_tables_xpath = '//*[@id="mainTableTwoColumn"]/tbody/tr/td[1]/table/tbody/tr[7]/td[2]/table'
        try:
            edu_tables = self.driver.find_elements(By.XPATH, edu_tables_xpath)
            total_degrees = len(edu_tables)
        except: total_degrees = 0
        matched_uni = ""; matched_faculty = ""; matched_major = ""; is_qualified = False
        highest_degree_text = "-"; max_degree_score = -1
        degree_score_map = {"ปริญญาเอก": 3, "ดุษฎีบัณฑิต": 3, "Doctor": 3, "Ph.D": 3, "ปริญญาโท": 2, "มหาบัณฑิต": 2, "Master": 2, "ปริญญาตรี": 1, "บัณฑิต": 1, "Bachelor": 1}
        
        def check_fuzzy(scraped_text, target_list, threshold=85): # ลด Threshold
            if not target_list: return True
            if not scraped_text: return False
            best_score = 0
            for target in target_list:
                score = fuzz.partial_ratio(target.lower(), scraped_text.lower())
                if score > best_score: best_score = score
            if best_score >= threshold: return True
            return False 

        debug_edu_list = [] # เพิ่ม Debug

        for i in range(1, total_degrees + 1):
            base_xpath = f'//*[@id="mainTableTwoColumn"]/tbody/tr/td[1]/table/tbody/tr[7]/td[2]/table[{i}]'
            curr_uni = get_val(f'{base_xpath}/tbody/tr[2]/td/div', True)
            if not curr_uni: curr_uni = get_val(f'{base_xpath}/tbody/tr[1]/td/div', True)
            
            curr_degree = get_val(f'{base_xpath}//td[contains(., "ระดับการศึกษา")]/following-sibling::td[1]', True)
            if not curr_degree: curr_degree = get_val(f'{base_xpath}/tbody/tr[1]/td', True)
            
            curr_faculty = get_val(f'{base_xpath}//td[contains(., "คณะ")]/following-sibling::td[1]', True)
            curr_major = get_val(f'{base_xpath}//td[contains(., "สาขา")]/following-sibling::td[1]', True)
            
            debug_edu_list.append(f"[{curr_degree}] {curr_uni} / {curr_faculty} / {curr_major}")

            score = 0
            for key, val in degree_score_map.items():
                if key in str(curr_degree): score = val; break
            if score > max_degree_score: max_degree_score = score; highest_degree_text = curr_degree
            elif score == max_degree_score and highest_degree_text == "-": highest_degree_text = curr_degree

            if not is_qualified:
                uni_pass = check_fuzzy(curr_uni, TARGET_UNIVERSITIES)
                fac_pass = check_fuzzy(curr_faculty, TARGET_FACULTIES)
                major_pass = check_fuzzy(curr_major, TARGET_MAJORS)
                if uni_pass and (fac_pass or major_pass):
                    is_qualified = True; matched_uni = curr_uni; matched_faculty = curr_faculty; matched_major = curr_major

        if not is_qualified:
            # เปิด Debug เพื่อดูว่าทำไมไม่ผ่าน (ถ้าต้องการ)
            # printer.print(f"   ❄️ (Skip) {debug_edu_list}", style="dim")
            return None, 999, None
        
        data['ระดับการศึกษา'] = highest_degree_text; data['มหาลัย'] = matched_uni; data['คณะ'] = matched_faculty; data['สาขา'] = matched_major
        data['รหัสใบสมัคร'] = get_val("#ResumeViewDiv [align='left'] span.white")
        
        try:
            img_element = self.driver.find_element(By.ID, "DefaultPictureResume2Column")
            app_id_clean = data['รหัสใบสมัคร'].strip() if data['รหัสใบสมัคร'] else f"unknown_{int(time.time())}"
            img_filename = f"{app_id_clean}.png"
            save_path = os.path.join(RESUME_IMAGE_FOLDER, img_filename)
            img_element.screenshot(save_path)
            data['รูปภาพ'] = save_path
        except: data['รูปภาพ'] = ""

        raw_update_date = get_val('//*[@id="ResumeViewDiv"]/table/tbody/tr[2]/td[3]/span[2]', xpath=True)
        
        def calculate_last_update(date_str):
            if not date_str: return "-"
            try:
                parts = date_str.split()
                if len(parts) < 3: return "-"
                day = int(parts[0])
                month_str = parts[1]
                year_be = int(parts[2])
                year_ad = year_be - 543
                thai_months = {'มกราคม': 1, 'กุมภาพันธ์': 2, 'มีนาคม': 3, 'เมษายน': 4, 'พฤษภาคม': 5, 'มิถุนายน': 6, 'กรกฎาคม': 7, 'สิงหาคม': 8, 'กันยายน': 9, 'ตุลาคม': 10, 'พฤศจิกายน': 11, 'ธันวาคม': 12}
                month = thai_months.get(month_str, 1)
                update_dt = datetime.datetime(year_ad, month, day)
                diff = relativedelta(datetime.datetime.now(), update_dt)
                txt = []
                if diff.years > 0: txt.append(f"{diff.years}ปี")
                if diff.months > 0: txt.append(f"{diff.months}เดือน")
                if diff.days > 0: txt.append(f"{diff.days}วัน")
                if not txt: return "วันนี้"
                return " ".join(txt)
            except: return "-"
            
        data['อัพเดทล่าสุด'] = calculate_last_update(raw_update_date)

        data['ชื่อ'] = get_val("#mainTableTwoColumn td > span.head1")
        data['นามสกุล'] = get_val("span.black:nth-of-type(3)")
        age_match = re.search(r"อายุ\s*[:]?\s*(\d+)", full_text)
        data['อายุ'] = age_match.group(1) if age_match else ""
        data['เพศ'] = re.search(r"เพศ\s*[:]?\s*(ชาย|หญิง|Male|Female)", full_text).group(1) if re.search(r"เพศ\s*[:]?\s*(ชาย|หญิง|Male|Female)", full_text) else ""
        data['เบอร์โทร'] = get_val("#mainTableTwoColumn div:nth-of-type(6) span.black")
        data['Email'] = get_val("#mainTableTwoColumn a")
        data['ที่อยู่'] = get_val("#mainTableTwoColumn div:nth-of-type(1) span.head1")
        data['จังหวัดที่อยู่'] = get_val("#mainTableTwoColumn table [width][align='left'] div span.headNormal")
        
        pos1 = get_val('//*[@id="mainTableTwoColumn"]/tbody/tr/td[1]/table/tbody/tr[5]/td[2]/table/tbody/tr[3]/td/span[2]', xpath=True)
        pos2 = get_val('//*[@id="mainTableTwoColumn"]/tbody/tr/td[1]/table/tbody/tr[5]/td[2]/table/tbody/tr[3]/td/span[4]', xpath=True)
        pos3 = get_val('//*[@id="mainTableTwoColumn"]/tbody/tr/td[1]/table/tbody/tr[5]/td[2]/table/tbody/tr[3]/td/span[6]', xpath=True)
        data['ตำแหน่งที่ต้องการสมัคร_1'] = pos1; data['ตำแหน่งที่ต้องการสมัคร_2'] = pos2; data['ตำแหน่งที่ต้องการสมัคร_3'] = pos3
        combined_positions = ", ".join([p for p in [pos1, pos2, pos3] if p])
        data['เงินเดือนที่ต้องการ'] = get_val("//td[contains(., 'เงินเดือนที่ต้องการ')]/following-sibling::td[1]", True)
        
        salary_min_txt = "-"
        salary_max_txt = "-"
        raw_salary = data.get('เงินเดือนที่ต้องการ', '')
        try:
            if raw_salary and 'ปิดข้อมูล' not in str(raw_salary):
                s = str(raw_salary).lower().replace(',', '')
                s = re.sub(r'(\d+(\.\d+)?)\s*k', lambda m: str(float(m.group(1)) * 1000), s)
                nums = re.findall(r'\d+(?:\.\d+)?', s)
                nums = [float(n) for n in nums]
                if nums:
                    mn, mx = nums[0], nums[0]
                    if len(nums) >= 2: mn, mx = nums[0], nums[1]
                    if mx > 1000 and mn < 1000 and mn > 0: mn *= 1000
                    salary_min_txt = f"{int(mn):,}"
                    salary_max_txt = f"{int(mx):,}"
        except: pass
        
        data['Salary_Min'] = salary_min_txt
        data['Salary_Max'] = salary_max_txt

        all_work_history = []
        try:
            if "ประวัติการทำงาน/ฝึกงาน" in full_text:
                history_text = full_text.split("ประวัติการทำงาน/ฝึกงาน")[1].split("ความสามารถ")[0]
            else: history_text = ""
            thai_months_str = "มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม"
            raw_chunks = re.split(f"({thai_months_str})\\s+\\d{{4}}\\s+-\\s+", history_text)
            jobs = []
            if len(raw_chunks) > 1:
                for k in range(1, len(raw_chunks), 2):
                    if k+1 < len(raw_chunks): jobs.append(raw_chunks[k] + raw_chunks[k+1]) 
            i = 0
            while True:
                check_xpath = f'//*[@id="mainTableTwoColumn"]/tbody/tr/td[2]/table/tbody/tr[2]/td[2]/table[{i+1}]'
                try:
                    if len(self.driver.find_elements(By.XPATH, check_xpath)) == 0: break
                except: break
                suffix = f"_{i+1}"
                company = get_val(f'{check_xpath}/tbody/tr[3]/td/div/span', True)
                if not company: company = get_val(f'{check_xpath}/tbody/tr[3]/td', True)
                if i < len(jobs):
                    block = jobs[i]
                    if not company:
                        comp_match = re.search(r"^.*(บริษัท|Ltd|Inc|Group|Organization|หจก|Limited).*$", block, re.MULTILINE | re.IGNORECASE)
                        company = comp_match.group(0).strip() if comp_match else ""
                data[f'ชื่อบริษัทที่เคยทำงาน{suffix}'] = company
                if company: all_work_history.append(company.strip())
                i += 1
        except: pass
        
        competitor_str = ", ".join(all_work_history)
        data['เคยทำบริษัทคู่แข่ง'] = competitor_str

        today_date = datetime.date.today()
        update_date = self.parse_thai_date_exact(raw_update_date)
        days_diff = 999
        if update_date: days_diff = (today_date - update_date).days

        app_id = data.get('รหัสใบสมัคร', '').strip()
        full_name = f"{data.get('ชื่อ', '')} {data.get('นามสกุล', '')}"
        
        person_data = {
            "keyword": keyword, 
            "company": competitor_str,
            "degree": highest_degree_text,
            "salary_min": salary_min_txt,
            "salary_max": salary_max_txt,
            "id": app_id,
            "name": full_name,
            "age": data.get('อายุ', '-'),
            "positions": combined_positions, 
            "last_update": data['อัพเดทล่าสุด'],
            "link": url,
            "image_path": data.get('รูปภาพ', '')
        }

        printer.print(f"   🔥 เจอ: {highest_degree_text} | มหาลัย: {matched_uni} | วันที่: {days_diff} วันก่อน", style="bold green")
        return data, days_diff, person_data
    
    # ... (ส่วน send_single_email, send_batch_email, save_to_google_sheets คงเดิม) ...
    def send_single_email(self, subject_prefix, people_list, col_header="เคยทำงานบริษัท"):
        sender = os.getenv("EMAIL_SENDER")
        password = os.getenv("EMAIL_PASSWORD")
        receiver_list = []
        if MANUAL_EMAIL_RECEIVERS and len(MANUAL_EMAIL_RECEIVERS) > 0: receiver_list = MANUAL_EMAIL_RECEIVERS
        else:
             rec_env = os.getenv("EMAIL_RECEIVER")
             if rec_env: receiver_list = [rec_env]
        
        if not sender or not password or not receiver_list: return

        if "สรุป" in subject_prefix or "HOT" in subject_prefix: subject = subject_prefix
        elif len(people_list) > 1: subject = f"🔥 {subject_prefix} ({len(people_list)} คน)"
        else: subject = subject_prefix 

        body_html = f"""
        <html>
        <head>
        <style>
            table {{ border-collapse: collapse; width: 100%; font-size: 14px; }}
            th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
            th {{ background-color: #f2f2f2; }}
            tr:nth-child(even) {{ background-color: #f9f9f9; }}
            .btn {{
                background-color: #28a745; 
                color: #ffffff !important; 
                padding: 5px 10px;
                text-align: center; 
                text-decoration: none; 
                display: inline-block;
                border-radius: 4px; 
                font-size: 12px;
                font-weight: bold;
            }}
            .btn:hover, .btn:visited, .btn:active {{ color: #ffffff !important; }}
        </style>
        </head>
        <body>
            <h3>{subject}</h3>
            <table>
                <tr>
                    <th style="width: 10%;">รูปภาพ</th>
                    <th style="width: 15%;">{col_header}</th>
                    <th style="width: 10%;">ระดับการศึกษาสูงสุด</th>
                    <th style="width: 10%;">รหัสใบสมัคร</th>
                    <th style="width: 15%;">ชื่อ-นามสกุล</th>
                    <th style="width: 5%;">อายุ</th>
                    <th style="width: 15%;">ตำแหน่งที่สมัคร</th>
                    <th style="width: 8%;">เงินเดือนขั้นต่ำ</th> <th style="width: 8%;">เงินเดือนสูงสุด</th> <th style="width: 10%;">อัพเดทล่าสุด</th>
                    <th style="width: 10%;">ลิงก์</th>
                </tr>
        """
        
        images_to_attach = []
        for person in people_list:
            cid_id = f"img_{person['id']}"
            if person['image_path'] and os.path.exists(person['image_path']):
                img_html = f'<img src="cid:{cid_id}" width="80" style="border-radius: 5px;">'
                images_to_attach.append({'cid': cid_id, 'path': person['image_path']})
            else:
                img_html = '<span style="color:gray;">No Image</span>'

            company_display = person['company']
            if company_display == "University Target" or company_display == "-":
                company_display = "-"
                company_style = "font-weight: bold;" 
            else:
                company_style = "font-weight: normal;"

            body_html += f"""
                <tr>
                    <td style="text-align: center;">{img_html}</td>
                    <td style="{company_style}">{company_display}</td>
                    <td>{person.get('degree', '-')}</td> 
                    <td>{person['id']}</td>
                    <td>{person['name']}</td>
                    <td>{person['age']}</td>
                    <td>{person['positions']}</td>
                    <td>{person.get('salary_min', '-')}</td> <td>{person.get('salary_max', '-')}</td> <td>{person['last_update']}</td>
                    <td style="text-align: center;">
                        <a href="{person['link']}" target="_blank" class="btn" style="color: #ffffff; text-decoration: none;">เปิดดู</a>
                    </td>
                </tr>
            """
            
        body_html += "</table><br><p><i>ระบบอัตโนมัติ JobThai Scraper (Google Sheets Edition)</i></p></body></html>"

        try:
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(sender, password)
            
            msg_root = MIMEMultipart('related')
            msg_root['From'] = sender
            msg_root['Subject'] = subject
            
            msg_alternative = MIMEMultipart('alternative')
            msg_root.attach(msg_alternative)
            msg_alternative.attach(MIMEText(body_html, 'html'))
            
            for img_data in images_to_attach:
                try:
                    with open(img_data['path'], 'rb') as f:
                        msg_img = MIMEImage(f.read())
                        msg_img.add_header('Content-ID', f"<{img_data['cid']}>")
                        msg_img.add_header('Content-Disposition', 'inline', filename=os.path.basename(img_data['path']))
                        msg_root.attach(msg_img)
                except: pass

            for rec in receiver_list:
                if 'To' in msg_root: del msg_root['To']
                msg_root['To'] = rec
                server.send_message(msg_root)
                console.print(f"   ✅ ส่งเมล '{subject}' -> {rec}", style="success")
            server.quit()
        except Exception as e:
            console.print(f"❌ ส่งอีเมลล้มเหลว: {e}", style="error")

    def send_batch_email(self, batch_candidates, keyword):
        self.send_single_email(f"สรุปผู้สมัครรายสัปดาห์: {keyword} ({len(batch_candidates)} คน)", batch_candidates)

    def save_to_google_sheets(self):
        if not self.all_scraped_data:
            console.print("⚠️ ไม่มีข้อมูลใหม่ให้บันทึก", style="yellow")
            return

        console.rule("[bold green]📊 เริ่มต้นการอัพโหลดขึ้น Google Sheets[/]")
        
        try:
            if not G_SHEET_KEY_JSON or not G_SHEET_NAME:
                console.print("❌ ไม่พบ Key หรือชื่อไฟล์ Google Sheet ใน Secrets", style="error")
                return

            creds_dict = json.loads(G_SHEET_KEY_JSON)
            scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
            client = gspread.authorize(creds)
            
            sheet = client.open(G_SHEET_NAME)
            console.print(f"✅ เชื่อมต่อไฟล์ '{G_SHEET_NAME}' สำเร็จ", style="success")
            
            today_str = datetime.datetime.now().strftime("%d-%m-%Y")
            try:
                worksheet = sheet.worksheet(today_str)
                console.print(f"ℹ️ พบ Tab '{today_str}' อยู่แล้ว -> จะทำการต่อท้ายข้อมูล (Append)", style="info")
            except:
                worksheet = sheet.add_worksheet(title=today_str, rows="100", cols="20")
                console.print(f"🆕 สร้าง Tab ใหม่: '{today_str}'", style="success")
                
                headers = [
                    "Link", "Keyword", "รหัสใบสมัคร", "ชื่อ-นามสกุล", "อายุ", "เพศ", 
                    "เบอร์โทร", "Email", "ที่อยู่", "ระดับการศึกษา", "มหาลัย", "คณะ", "สาขา",
                    "ตำแหน่งที่สมัคร", "เงินเดือนที่ขอ (Raw)", "เงินเดือนต่ำสุด", "เงินเดือนสูงสุด",
                    "เคยทำบริษัทคู่แข่ง", "อัพเดทล่าสุด"
                ]
                worksheet.append_row(headers)

            data_rows = []
            for item in self.all_scraped_data:
                row = [
                    item.get('Link', ''),
                    item.get('Keyword', ''),
                    item.get('รหัสใบสมัคร', ''),
                    f"{item.get('ชื่อ','')} {item.get('นามสกุล','')}",
                    item.get('อายุ', ''),
                    item.get('เพศ', ''),
                    re.sub(r'\D', '', str(item.get('เบอร์โทร', ''))),
                    str(item.get('Email', '')).replace('Click', '').strip(),
                    item.get('จังหวัดที่อยู่', ''),
                    item.get('ระดับการศึกษา', ''),
                    item.get('มหาลัย', ''),
                    item.get('คณะ', ''),
                    item.get('สาขา', ''),
                    f"{item.get('ตำแหน่งที่ต้องการสมัคร_1','')} {item.get('ตำแหน่งที่ต้องการสมัคร_2','')}",
                    item.get('เงินเดือนที่ต้องการ', ''),
                    item.get('Salary_Min', '-'), 
                    item.get('Salary_Max', '-'), 
                    item.get('เคยทำบริษัทคู่แข่ง', ''),
                    item.get('อัพเดทล่าสุด', '')
                ]
                data_rows.append(row)
            
            if data_rows:
                worksheet.append_rows(data_rows)
                console.print(f"✅ บันทึกข้อมูล {len(data_rows)} แถว เรียบร้อย!", style="bold green")
                
        except Exception as e:
            console.print(f"❌ Google Sheets Error: {e}", style="error")

    def run(self):
        self.email_report_list = []
        if not self.step1_login(): return
        
        today = datetime.date.today()
        is_monday = (today.weekday() == 0)
        is_manual_run = (os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch")
        
        console.print(f"📅 Status Check: Today is Monday? [{'Yes' if is_monday else 'No'}] | Manual Run? [{'Yes' if is_manual_run else 'No'}]", style="bold yellow")
        
        master_data_list = [] 
        
        for index, keyword in enumerate(SEARCH_KEYWORDS):
            console.rule(f"[bold magenta]🔍 เริ่มดำเนินการคำค้นที่ {index+1}/{len(SEARCH_KEYWORDS)}: {keyword}[/]")
            
            current_keyword_batch = []
            if self.step2_search(keyword):
                links = self.step3_collect_all_links()
                if links:
                    console.print(f"\n🚀 เริ่มดูดข้อมูลสำหรับ '{keyword}' จำนวน {len(links)} รายการ ...")
                    with Progress(
                        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                        BarColumn(), TaskProgressColumn(), TimeElapsedColumn(), TimeRemainingColumn(),
                        console=console
                    ) as progress:
                        task_id = progress.add_task(f"[cyan]Processing {keyword}...", total=len(links))
                        
                        for i, link in enumerate(links):
                            if self.total_profiles_viewed > 0 and self.total_profiles_viewed % 33 == 0:
                                progress.console.print(f"[yellow]☕ ครบ {self.total_profiles_viewed} คนแล้ว... พักเบรก 4 นาที[/]")
                                time.sleep(240)

                            try:
                                d, days_diff, person_data = self.scrape_detail_from_json(link, keyword, progress_console=progress.console)
                                self.total_profiles_viewed += 1 
                                
                                if d is not None:
                                    d['Keyword'] = keyword
                                    self.all_scraped_data.append(d)
                                    
                                    should_add = False
                                    if days_diff <= 30:
                                        should_add = True
                                        if EMAIL_USE_HISTORY and person_data['id'] in self.history_data:
                                            try:
                                                last_notify = datetime.datetime.strptime(self.history_data[person_data['id']], "%Y-%m-%d").date()
                                                if (today - last_notify).days < 7: should_add = False
                                            except: pass
                                        if should_add: current_keyword_batch.append(person_data)

                                    if days_diff <= 1:
                                        should_hot = True
                                        if EMAIL_USE_HISTORY and person_data['id'] in self.history_data:
                                             try:
                                                 last_notify = datetime.datetime.strptime(self.history_data[person_data['id']], "%Y-%m-%d").date()
                                                 if (today - last_notify).days < 1: should_hot = False
                                             except: pass
                                        if should_hot:
                                            hot_subject = f"🔥 [HOT] พบผู้สมัครด่วน ({keyword}): {person_data['name']}"
                                            progress.console.print(f"   🚨 พบผู้สมัคร HOT -> ส่งเมลทันที!", style="bold red")
                                            self.send_single_email(hot_subject, [person_data], col_header="ประวัติบริษัท")
                                            if EMAIL_USE_HISTORY: self.history_data[person_data['id']] = str(today)

                                    if days_diff > 30 and (is_monday or is_manual_run):
                                        if current_keyword_batch:
                                             progress.console.print(f"\n[bold green]📨 เจอคนเก่า ({days_diff} วัน) -> ถึงรอบส่งเมลสรุป ({len(current_keyword_batch)} คน)![/]")
                                             self.send_batch_email(current_keyword_batch, keyword)
                                             if EMAIL_USE_HISTORY:
                                                 for p in current_keyword_batch: self.history_data[p['id']] = str(today)
                                             current_keyword_batch = []

                            except Exception as e: progress.console.print(f"[bold red]❌ Error Link {i+1}: {e}[/]")
                            progress.advance(task_id)
                
                if current_keyword_batch and (is_monday or is_manual_run):
                    self.send_batch_email(current_keyword_batch, keyword)
                    if EMAIL_USE_HISTORY:
                         for p in current_keyword_batch: self.history_data[p['id']] = str(today)

            console.print("⏳ พัก 3 วินาที ก่อนคำต่อไป...", style="dim")
            time.sleep(3)
        
        self.save_to_google_sheets()
        self.save_history()
        console.rule("[bold green]🏁 จบการทำงาน JobThai (Google Sheets Mode)[/]")
        try: self.driver.quit()
        except: pass

if __name__ == "__main__":
    console.print("[bold green]🚀 Starting JobThai Scraper (Google Sheets Edition)...[/]")
    if not MY_USERNAME or not MY_PASSWORD:
        console.print(f"\n[bold red]❌ [CRITICAL ERROR] ไม่พบ User/Pass ในไฟล์ .env[/]")
        exit()
    scraper = JobThaiRowScraper()
    scraper.run()
