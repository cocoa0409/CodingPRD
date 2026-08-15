"""Domain thresholds and constants from PRD calculations."""

# Statutory resignation notice cap (days after notice_received_date)
NOTICE_CAP_DAYS = 30

# Final-pay deadline variants
CALENDAR_DAY_STATES = ("CA", "CO", "MA")
BUSINESS_DAY_STATES = ("IL", "NY", "WA")
NEXT_PAYDAY_STATES = ("TX", "FL")
SUPPORTED_STATE_CODES = ("CA", "CO", "IL", "MA", "TX", "NY", "WA", "FL")
RESIGNATION_NOTICE_THRESHOLD_HOURS = 72

# PTO payout rules
PTO_PAYOUT_STATES = ("CA", "CO", "IL", "MA")
TIER_1_HOURS = 40   # tenure_years < 2
TIER_2_HOURS = 80   # 2 <= tenure_years < 5
TIER_3_HOURS = 120  # tenure_years >= 5

# Asset deduction constants
DEPRECIATION_PER_DAY_BPS_LAPTOP = 20
DEPRECIATION_PER_DAY_BPS_PHONE = 25
DEPRECIATION_PER_DAY_BPS_DEFAULT = 10
MAX_DEPRECIATION_BPS = 7000
DAMAGE_FRACTION_DEFAULT = 0.5
LATE_FEE_CENTS = 2500
ASSET_RETURN_GRACE_DAYS = 3
ASSET_DEFAULT_GRACE_DAYS = 7

# Late penalty constants
WAITING_TIME_CAP_DAYS = 30
HOURS_PER_DAY = 8

# Revocation scheduling / retry constants
MAX_REVOKE_RETRIES = 3
RETRY_BACKOFF_MINUTES = 60

# Exit interview cap
MAX_INTERVIEW_RESCHEDULES = 2
INTERVIEW_HARD_LIMIT_DAYS = 5

# Benefits notice deadlines (calendar days from determined_last_day)
COBRA_DEADLINE_DAYS = 44
BENEFITS_TERM_DAYS = 30
LIFE_CONVERSION_DAYS = 31

# Covenant reminder offset
COVENANT_REMIND_DAYS = 3

# Benefits notice requeue cap
MAX_NOTICE_FAILURES = 2

# Notification dedupe window
DEDUPE_WINDOW_MINUTES = 60

# Default clock start (PRD §2.4)
CLOCK_START = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "HOURLY_WAGE_CENTS": 5000,
    "REGULAR_WAGES_CENTS": 100000,
}
