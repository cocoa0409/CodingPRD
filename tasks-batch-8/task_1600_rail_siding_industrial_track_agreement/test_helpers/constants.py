"""Domain constants — canonical agreement terms and calculation anchors (PRD §2.4, §3)."""

# --- Canonical agreement terms used across test setups (PRD §3.1) ---
SHIPPER_USER_ID = "shipper-user-1"
OTHER_SHIPPER_USER_ID = "shipper-user-2"
TERM_START_DATE = "2026-08-01"  # a Saturday
TERM_END_DATE = "2027-07-31"
RENEWAL_NOTICE_DAYS = 90
RENEWAL_TERM_MONTHS = 12
SHIPPER_COST_SHARE_PCT = 40
LIABILITY_CAP_CENTS = 100000
SHIPPER_INDEMNITY_DEFAULT_PCT = 50
FREE_TIME_HOURS = 48
DEMURRAGE_BASE_RATE_CENTS = 7500
DEMURRAGE_ESCALATED_RATE_CENTS = 15000
STORAGE_RATE_PER_CAR_MONTH_CENTS = 10012
INSPECTION_CADENCE_DAYS = 90
REMOVAL_PERIOD_DAYS = 90
REMOVAL_PENALTY_PER_DAY_CENTS = 5000
SERVICE_DAYS_OF_WEEK = ["MON", "WED", "FRI"]
MAX_SWITCHES_PER_DAY = 1

# --- Logical clock (PRD §2.4) ---
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# --- Calendar anchors derived from the canonical term ---
# Renewal window closes term_end_date - renewal_notice_days (PRD §3.1).
RENEWAL_WINDOW_CLOSE_DATE = "2027-05-02"  # 2027-07-31 minus 90 days
RENEWAL_WINDOW_CLOSED_CLOCK = "2027-05-03T00:00:00Z"  # one day past the close
RENEWED_TERM_END_DATE = "2028-07-31"  # 2027-07-31 + 12 months (PRD §3.1 example)
PAST_TERM_END_CLOCK = "2027-08-01T00:00:00Z"  # past term_end_date -> EXPIRED

# Service-day reference dates: 2026-08-03 is a Monday, 2026-08-04 a Tuesday,
# 2026-08-05 a Wednesday (2026-08-01 is a Saturday).
MONDAY_DATE = "2026-08-03"
TUESDAY_DATE = "2026-08-04"
WEDNESDAY_DATE = "2026-08-05"

# --- Demurrage calculation constants (PRD §3.5) ---
TIER1_MAX_DAYS = 2
MINUTES_PER_DAY = 1440
PRIVATE_CAR_FREE_TIME_MULTIPLIER = 2

# --- Storage charge constants (PRD §3.6) ---
DAYS_PER_MONTH_DIVISOR = 30
MINIMUM_DAYS_CHARGED = 1
# round_half_up(10012 / 30, 2) — the pinned daily-rate rounding.
STORAGE_DAILY_RATE_CENTS = 333.73

# --- Abandonment anchors (PRD §3.8) ---
ABANDONMENT_NOTICE_DATE = "2026-09-01"
REMOVAL_DEADLINE_DATE = "2026-11-30"  # notice date + 90 days
