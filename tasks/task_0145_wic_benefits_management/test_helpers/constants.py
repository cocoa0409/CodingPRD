"""Domain thresholds — numeric constants from the PRD's calculation rules.

Generic NON_EXISTENT_UUID comes from the framework. All values here are stated
verbatim in PRD Section 3 (income determination, risk assessment, certification
length, food-package pricing, vendor compliance, appointment overlap).
"""

# --- Income determination (PRD 3.3) ---
WIC_INCOME_PCT = 1.85
FPG_ANNUAL = {1: 15060, 2: 20440, 3: 25820, 4: 31200, 5: 36580, 6: 41960, 7: 47340, 8: 52720}
FPG_INCREMENT = 5380
FREQ_MULT = {"WEEKLY": 52, "BIWEEKLY": 26, "MONTHLY": 12, "ANNUAL": 1}

# --- Nutritional risk scoring (PRD 3.4) ---
RISK_FACTOR_POINTS = {
    "ANEMIA": 40,
    "UNDERWEIGHT": 35,
    "INADEQUATE_DIET": 20,
    "SHORT_STATURE": 15,
    "ELEVATED_LEAD": 50,
    "GEST_DIABETES": 45,
}
HIGH_PRIORITY_FACTORS = ["ELEVATED_LEAD", "GEST_DIABETES"]
RISK_THRESHOLD = {
    "PREGNANT": 30,
    "POSTPARTUM": 30,
    "BREASTFEEDING": 30,
    "INFANT": 25,
    "CHILD": 35,
}

# --- Certification length / priority (PRD 3.5) ---
CERT_LENGTH_DAYS = {
    "PREGNANT": 280,
    "POSTPARTUM": 180,
    "BREASTFEEDING": 365,
    "INFANT": 365,
    "CHILD": 365,
}
PRIORITY_BY_CATEGORY = {
    "PREGNANT": 1,
    "BREASTFEEDING": 1,
    "INFANT": 1,
    "POSTPARTUM": 6,
    "CHILD": 3,
}

# --- Food-package pricing / caps (PRD 3.7) ---
UNIT_PRICE_CENTS = {
    "MILK": 350,
    "EGGS": 300,
    "JUICE": 250,
    "CEREAL": 400,
    "FRUIT_VEG": 200,
    "INFANT_FORMULA": 1200,
    "INFANT_CEREAL": 300,
}
CATEGORY_CAP = {
    "PREGNANT": {"MILK": 4, "EGGS": 2, "JUICE": 2, "CEREAL": 3, "FRUIT_VEG": 11},
    "POSTPARTUM": {"MILK": 4, "EGGS": 2, "JUICE": 2, "CEREAL": 3, "FRUIT_VEG": 9},
    "BREASTFEEDING": {"MILK": 6, "EGGS": 2, "JUICE": 2, "CEREAL": 4, "FRUIT_VEG": 11},
    "INFANT": {"INFANT_FORMULA": 9, "INFANT_CEREAL": 24, "FRUIT_VEG": 8},
    "CHILD": {"MILK": 4, "EGGS": 1, "JUICE": 2, "CEREAL": 4, "FRUIT_VEG": 8},
}

# --- Vendor compliance (PRD 3.9) ---
SUSPENSION_THRESHOLD = 100

# --- Appointment / peer-session overlap (PRD 3.11) ---
SESSION_BUFFER_MINUTES = 15

# --- Pagination (PRD 2.3) ---
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1
DEFAULT_OFFSET = 0

# --- Agency clock default (PRD 2.5) ---
EPOCH_DEFAULT_UTC = "1970-01-01T00:00:00.000Z"
