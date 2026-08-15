"""Domain thresholds and canonical timeline values from the PRD."""

# --- Merit / need-based aid caps (PRD financial-aid leveraging section) ---
MERIT_MAX_CENTS = 2_500_000
NEED_MAX_CENTS = 3_000_000
NEED_TUITION_COVER_RATE = 0.60
MERIT_TIER_TOP_SCORE = 95
MERIT_TIER_TOP_RATE = 0.50
MERIT_TIER_MID_SCORE = 90
MERIT_TIER_MID_RATE = 0.35
MERIT_TIER_LOW_SCORE = 80
MERIT_TIER_LOW_RATE = 0.20

# --- Melt risk (PRD summer-melt section) ---
MELT_RISK_THRESHOLD = 0.70
TIME_FACTOR_FULL_DAYS = 30
AUTO_ADVISOR_ID = "AUTO_QUEUE"
DISTANCE_FACTORS = {
    "LOCAL": 0.0,
    "REGIONAL": 0.3,
    "NATIONAL": 0.6,
    "INTERNATIONAL": 1.0,
}

# --- Yield forecast bands (PRD forecasting section) ---
BAND_HIGH_SCORE = 90
BAND_HIGH_P = 0.65
BAND_MID_SCORE = 70
BAND_MID_P = 0.45
BAND_LOW_P = 0.25

# --- Waitlist rank weights (PRD waitlist section) ---
ACADEMIC_WEIGHT = 0.6
RECOMMENDATION_WEIGHT = 0.4

# --- Committee quorum (PRD decision workflow section) ---
REVIEW_QUORUM = 2

# --- Advisor scheduling buffer, in minutes (PRD interventions) ---
ADVISOR_BUFFER_MINUTES = 15

# --- Canonical timeline used across fixtures (ISO 8601 UTC) ---
CLOCK_START = "2026-08-01T00:00:00Z"        # logical-clock startup instant
APP_OPENS = "2026-08-01T00:00:00Z"
APP_DEADLINE = "2026-11-01T00:00:00Z"
DEPOSIT_DEADLINE = "2027-05-01T00:00:00Z"
CENSUS = "2027-06-01T00:00:00Z"
DEPOSIT_TIME = "2027-04-01T00:00:00Z"       # before the deposit deadline
REVIEW_WINDOW_START = "2026-08-01T00:00:00Z"
REVIEW_WINDOW_END = "2027-06-01T00:00:00Z"  # wide enough for late-phase reads

TEST_DEFAULTS = {
    "CYCLE_NAME": "Fall 2027",
    "TARGET_CLASS_SIZE": 100,
    "CAPACITY_SEATS": 5,
    "TARGET_ENROLLMENT": 3,
    "TUITION_CENTS": 5_000_000,
    "SCHOLARSHIP_BUDGET_CENTS": 0,
    "DEPOSIT_AMOUNT_CENTS": 50_000,
    "ACADEMIC_SCORE": 80,
    "EFC_CENTS": 5_000_000,
}
