"""Domain thresholds — numeric constants from PRD business rules."""

# --- Eligibility scoring (PRD §3.4) ---
ELIGIBILITY_ACCEPT_THRESHOLD = 75.0
INCOME_BAND_1 = 0.50   # ratio <= 0.50 -> 100
INCOME_BAND_2 = 0.80   # 0.50 < ratio <= 0.80 -> 75
INCOME_BAND_3 = 1.00   # 0.80 < ratio <= 1.00 -> 50; > 1.00 -> 0
WEIGHT_INCOME = 0.30
WEIGHT_AGE = 0.20
WEIGHT_CATEGORY = 0.25
WEIGHT_LANGUAGE = 0.15
WEIGHT_ACCESSIBILITY = 0.10
URGENCY_MULT_ROUTINE = 1.00
URGENCY_MULT_PRIORITY = 1.20
URGENCY_MULT_EMERGENCY = 1.50

# --- Travel burden (PRD §3.4) ---
DEG_TO_KM = 111.0
WINDING_FACTOR = 1.35
SPEED_KPH = {
    "PUBLIC_TRANSIT": 25.0,
    "CAR": 40.0,
    "WALKING": 5.0,
    "AGENCY_SHUTTLE": 20.0,
}

# --- Capacity posture (PRD §3.4) ---
RESTRICTED_THRESHOLD_RATIO = 0.80
CLOSED_THRESHOLD_RATIO = 1.00

# --- Transport plan buffer (PRD §3.6) ---
TRANSPORT_BUFFER_SECONDS = 30 * 60  # 30 minutes

# --- Service cost (PRD §3.7) ---
RAW_BASELINE_UNMET = 0.50
RAW_BASELINE_MET = 0.50
RAW_HOURS_COEFFICIENT = 0.10

# --- Consent expiry (PRD §3.3) ---
CONSENT_LIFETIME_DAYS = 90
