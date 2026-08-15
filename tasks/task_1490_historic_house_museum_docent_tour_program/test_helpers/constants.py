"""Domain thresholds — numeric constants from PRD calculations."""

# Logical clock startup default (PRD section 2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Slot capacity buffers by route kind (PRD section 3.4).
BUFFER_STANDARD = 2
BUFFER_SCHOOL = 0
BUFFER_CANDLELIGHT = 4

# Pricing (PRD section 3.6).
CANDLELIGHT_MULTIPLIER_NUM = 3   # 1.5x
CANDLELIGHT_MULTIPLIER_DEN = 2
SCHOOL_TIER1_LIMIT = 15
SCHOOL_TIER1_PRICE = 800
SCHOOL_TIER2_LIMIT = 30
SCHOOL_TIER2_PRICE = 700
SCHOOL_TIER3_PRICE = 600
EXTRA_CHAPERONE_PRICE = 1000
FREE_CHAPERONE_DIVISOR = 10
FREE_CHAPERONE_DIVISOR_HIGH_VALUE = 8

# Refund tiers in whole hours before slot start (PRD section 3.6).
FULL_REFUND_HOURS = 48
HALF_REFUND_HOURS = 24

# Revenue projection uplift over RESERVED bookings (PRD section 3.6).
PROJECTED_CONVERSION_NUM = 4     # 0.8
PROJECTED_CONVERSION_DEN = 5

# Docent certification thresholds (PRD section 3.3).
CERT_MIN_TRAINING_HOURS = 20
CERT_MIN_SHADOW_TOURS = 3
CERT_MIN_QUIZ_SCORE = 85
CERT_MIN_READINESS_STANDARD = 70
READINESS_HOURS_CAP = 30
READINESS_SHADOW_CAP = 5
SCRIPT_APPROVE_MIN_ACCURACY = 80

# Docent double-booking buffer in minutes (PRD section 3.4).
SHIFT_BUFFER_MINUTES = 30

# Post-visit survey window in days (PRD section 3.8).
SURVEY_WINDOW_DAYS = 14

# Booking hold lifetime in hours after creation (PRD section 3.6).
HOLD_HOURS = 48

TEST_DEFAULTS = {
    "BASE_PRICE_CENTS": 1000,
    "SLOT_START": "2026-09-01T10:00:00Z",
    "DURATION_MINUTES": 60,
}
