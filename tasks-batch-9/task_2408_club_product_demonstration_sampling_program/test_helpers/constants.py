"""Pinned business constants quoted by the PRD.

Tests import these rather than repeating bare numbers, but every expected value
in a test is still an independently derived literal — these constants document
the inputs, not the answers.
"""

# --- logical clock (PRD 2.5) -------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- day-part windows and shift geometry (PRD 2.5, 3.4) ---------------------
DAY_PART_WINDOWS = {
    "MORNING": ("09:00", "13:00"),
    "MIDDAY": ("12:00", "16:00"),
    "AFTERNOON": ("15:00", "19:00"),
}
SETUP_LEAD_MINUTES = 45
TEARDOWN_MINUTES = 75
DAY_PART_SHIFTS = {
    "MORNING": ("08:15", "14:15"),
    "MIDDAY": ("11:15", "17:15"),
    "AFTERNOON": ("14:15", "20:15"),
}

# --- attendance windows (PRD 3.6) ------------------------------------------
CHECK_IN_EARLY_MINUTES = 60
NO_SHOW_GRACE_MINUTES = 15
LATE_GRACE_MINUTES = 10

# --- booking calendar (PRD 3.2, 3.3) ---------------------------------------
MIN_BOOKING_LEAD_DAYS = 7
MAX_BOOKING_HORIZON_DAYS = 120
MAX_EVENTS_PER_CATEGORY_PER_DAY = 2

# --- sample allocation (PRD 3.3, 3.7) --------------------------------------
MIN_CASES_FOR_FOOD_SAMPLING = 2
SUPPORT_REQUIRED_CASE_THRESHOLD = 6
VARIANCE_TOLERANCE_PCT = 2.00

# --- reliability (PRD 3.4) -------------------------------------------------
NO_SHOW_PENALTY = 12
LATE_PENALTY = 4
COMPLETION_BONUS = 0.5
NO_SHOW_STRIKE_LIMIT = 3
STRIKE_LOOKBACK_DAYS = 180
ROLLING_WINDOW_DAYS = 90

# --- sales lift (PRD 3.8) --------------------------------------------------
PROVISIONAL_WINDOW_DAYS = 3
SAMPLE_CANNIBALIZATION_RATE = 0.15

# --- equipment (PRD 3.5) ---------------------------------------------------
SANITATION_BUFFER_MINUTES = 30

# --- staffing caps (PRD 3.4) ----------------------------------------------
MAX_ASSIGNMENTS_PER_DEMONSTRATOR_PER_DAY = 2

# --- invoice money (PRD 3.9) ----------------------------------------------
BASE_FEE_BY_EVENT_TYPE = {"FOOD_SAMPLING": 42000, "NON_FOOD_DEMO": 28000}
CLUB_TIER_MULTIPLIER = {"FLAGSHIP": 1.25, "STANDARD": 1.00, "SATELLITE": 0.85}
DAY_PART_MULTIPLIER = {"MORNING": 1.00, "MIDDAY": 1.15, "AFTERNOON": 1.05}
ADDON_FLAT_CENTS = {"EXTRA_TABLE": 5000, "VIDEO_LOOP": 7500, "ALLERGEN_SIGNAGE": 2200}
ADDON_PCT_OF_BASE = {"PREMIUM_PLACEMENT": 0.18, "BILINGUAL_DEMONSTRATOR": 0.12}
ROLE_MULTIPLIER = {"LEAD": 1.20, "SUPPORT": 1.00}
MIN_BILLABLE_HOURS = 4.00
HANDLING_FEE_PER_CASE_CENTS = 900
COLD_CHAIN_SURCHARGE_PER_CASE_CENTS = 350
TIER_BASE_DISCOUNT = {"PLATINUM": 0.06, "GOLD": 0.03, "STANDARD": 0.00}

# --- cancellation credits (PRD 3.9) ---------------------------------------
NOTICE_BRACKET_SPLIT_CENTS = 50000
NOTICE_TIER_HIGH = {"GTE_72": 0.25, "BETWEEN_24_AND_72": 0.50, "LT_24": 0.85}
NOTICE_TIER_LOW = {"GTE_72": 0.15, "BETWEEN_24_AND_72": 0.35, "LT_24": 0.70}
REASON_MULTIPLIER = {
    "CLUB_CANCELLED": 1.00,
    "DEMONSTRATOR_NO_SHOW": 1.00,
    "PRODUCT_SHORT": 0.60,
    "MANUFACTURER_CANCELLED_LATE": 0.00,
    "MANUFACTURER_CANCELLED_EARLY": 0.00,
}

# --- pagination (PRD 2.3) -------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
