"""Domain thresholds and constants from the PRD's calculation rules."""

# --- winterization quote (PRD: "Work Order Intake, Allowable Pinning, and Dispatch") ---
BASE_WINTERIZATION_CENTS = 15000
PER_FIXTURE_CENTS = 1200
POOL_CENTS = 9000
HEATING_MULT = {"NONE": 1.00, "FORCED_AIR": 1.00, "HOT_WATER": 1.50, "STEAM": 1.75}
SEASONAL_MULT = 1.20
HEATING_SEASON_MONTHS = {10, 11, 12, 1, 2, 3}

# --- prompt-pay discount (PRD: "Invoicing, Allowable Reimbursement, and Servicer Settlement") ---
PROMPT_PAY_RATE = 0.02

# --- year-to-date review threshold ---
PROPERTY_YTD_REVIEW_THRESHOLD_CENTS = 200000

# --- volume rebate tiers ---
TIER1_GROSS_CENTS = 500000
TIER1_RATE = 0.010
TIER2_GROSS_CENTS = 1000000
TIER2_RATE = 0.015

# --- personal property hold days by state ---
HOLD_DAYS = {"OH": 30, "MI": 28}
HOLD_DAYS_DEFAULT = 30

# --- disposal authority limit (cents) ---
DISPOSAL_AUTHORITY_LIMIT_CENTS = 50000

# --- condition score deductions ---
VIOLATION_CLASS_DEDUCT = {"MINOR": 15, "MAJOR": 25, "HAZARDOUS": 40}
VIOLATION_DEDUCT_CAP = 45
REGISTRATION_LAPSED_DEDUCT = 20
EXTERIOR_DAMAGE_DEDUCT_EACH = 10
EXTERIOR_DAMAGE_DEDUCT_CAP = 20
INTERIOR_DAMAGE_DEDUCT_EACH = 15
INTERIOR_DAMAGE_DEDUCT_CAP = 30
STALE_INSPECTION_DEDUCT = 10
POSTURE_CLEAR_MIN = 80
POSTURE_AT_RISK_MIN = 50

# --- photo completeness minimums per order type (unflagged counts) ---
PHOTO_MINIMUMS = {
    "SECURING": {"BEFORE": 2, "DURING": 1, "AFTER": 2, "SERIAL_NUMBER": 1},
    "WINTERIZATION": {"BEFORE": 1, "DURING": 2, "AFTER": 1},
    "DEWINTERIZATION": {"BEFORE": 1, "AFTER": 1},
    "GRASS_CUT": {"BEFORE": 1, "AFTER": 1},
    "SNOW_REMOVAL": {"BEFORE": 1, "AFTER": 1},
    "DEBRIS_REMOVAL": {"BEFORE": 2, "AFTER": 2},
    "PERSONAL_PROPERTY": {"BEFORE": 1, "DOCUMENT": 2},
    "CODE_CURE": {"BEFORE": 1, "DURING": 1, "AFTER": 2},
    "BOARD_UP": {"BEFORE": 1, "AFTER": 2},
    "DAMAGE_REPAIR": {"BEFORE": 1, "DURING": 1, "AFTER": 1},
    "INSPECTION": {"STREET_SCENE": 1},
}

# --- order_type -> item_code mapping ---
ORDER_TYPE_TO_ITEM_CODE = {
    "INSPECTION": "INSPECTION",
    "SECURING": "LOCK_CHANGE",
    "WINTERIZATION": "WINTERIZATION",
    "DEWINTERIZATION": "DEWINTERIZATION",
    "GRASS_CUT": "GRASS_CUT",
    "SNOW_REMOVAL": "SNOW_REMOVAL",
    "DEBRIS_REMOVAL": "DEBRIS_REMOVAL",
    "CODE_CURE": "CODE_CURE",
    "BOARD_UP": "BOARD_UP",
    "PERSONAL_PROPERTY": "PERSONAL_PROPERTY",
    "DAMAGE_REPAIR": "DAMAGE_REPAIR",
}

TEST_DEFAULTS = {
    "CLOCK": "2026-08-01T00:00:00Z",
    "MUNICIPALITY": "COL",
    "STATE": "OH",
    "ZIP": "43215",
    "DUE_DATE": "2026-08-10",
    "SCHEDULED_DATE": "2026-08-02",
    "EFFECTIVE_FROM": "2026-01-01",
}
