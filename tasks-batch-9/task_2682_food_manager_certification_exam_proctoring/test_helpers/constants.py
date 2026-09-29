"""Domain thresholds and literal figures stated by the PRD."""

# Logical clock (PRD 2.4)
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Bundle unit prices, in whole cents (PRD 3.3)
UNIT_PRICE_CENTS = {
    "EXAM_ONLY": 3600,
    "COURSE_PLUS_EXAM": 8900,
}

# Volume discount ladder keyed on a single line's own quantity (PRD 3.3)
VOLUME_DISCOUNT_TIERS = [(100, 0.15), (50, 0.10), (20, 0.05)]

# Restock fee ladder keyed on the gross credit (PRD 3.3)
RESTOCK_FEE_TIERS = [(50000, 0.05), (10000, 0.10)]
RESTOCK_FEE_FLOOR_RATE = 0.15

# Certificate issuance fee (PRD 2.7 / 3.7)
CERTIFICATE_ISSUANCE_FEE_CENTS = 1500

# Session timing (PRD 3.5)
MAX_SESSION_MINUTES = 240
REMOTE_SETUP_MINUTES = 10
SCHEDULE_LEAD_TIME_MINUTES = 1440

# Occupancy arithmetic (PRD 2.9)
PROCTOR_TURNAROUND_BUFFER_MINUTES = 15

# Check-in window (PRD 3.6)
CHECKIN_WINDOW_OPENS_MINUTES_BEFORE = 30
CHECKIN_WINDOW_CLOSES_MINUTES_AFTER = 15
BIOMETRIC_MIN_SCORE = 85

# Incident filing window (PRD 3.9)
INCIDENT_FILING_WINDOW_HOURS = 72

# Proctor audit risk (PRD 3.2)
SEVERITY_WEIGHTS = {"MINOR": 1, "MAJOR": 3, "CRITICAL": 5}
ROLLING_WINDOW_SIZE = 2
PROCTOR_RISK_SUSPEND_THRESHOLD = 10.00

# Certificate window (PRD 3.7)
RECERT_WINDOW_LEAD_DAYS = 180

# Pagination (PRD 2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# Reminder tiers, most-overdue-first (PRD 3.9)
REMINDER_TIER_ORDER = ["T_LAPSED", "T_30", "T_90", "T_180"]

# Shared baseline literals used by the composite fixtures.
TEST_DEFAULTS = {
    "JURISDICTION_NAME": "Travis County Health TX",
    "JURISDICTION_CODE": "TX-TRAVIS",
    "PROVIDER_LEGAL_NAME": "Lone Star Food Safety Institute",
    "PROVIDER_EMAIL": "ops@lonestarfoodsafety.example",
    "PREPAY_CENTS": 500000,
    "FORM_CODE": "FM-EN-01",
    "VERSION_LABEL": "V1",
    "SCORED_ITEM_COUNT": 80,
    "PRETEST_ITEM_COUNT": 10,
    "NATIONAL_CUT_SCORE": 70,
    "BASE_MINUTES": 120,
    "TRANSLATED_EXTRA_MINUTES": 30,
    "SITE_NAME": "Austin Central Testing Centre",
    "SITE_ADDRESS": "500 Congress Ave, Austin TX",
    "SEAT_COUNT": 2,
    "SURCHARGE_PCT": 0.045,
}
