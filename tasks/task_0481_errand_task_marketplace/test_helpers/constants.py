"""Domain thresholds — numeric constants from PRD calculations (§2.7, §3.5–§3.7)."""

# Service fee percentage applied to labor (§3.2, §3.5).
SERVICE_FEE_PCT = 0.15

# Final-settlement billing increment: actual hours round UP to next quarter hour (§3.5).
BILLING_INCREMENT_HOURS = 0.25

# Cancellation-fee tier breakpoints, in hours-before-start (§3.6).
FREE_THRESHOLD_HOURS = 24
LATE_THRESHOLD_HOURS = 2
LATE_PCT = 0.25
LAST_MINUTE_PCT = 0.50

# Trust score penalties per incident severity (§3.7).
PENALTY_LOW = 5
PENALTY_MEDIUM = 15
PENALTY_HIGH = 35
TRUST_BASE = 100
TRUST_FLOOR = 0

# Trust gate thresholds (§3.7).
SUSPEND_BELOW = 40       # trust_score < 40 -> SUSPENDED
RESTRICT_CEILING = 69    # 40..69 inclusive -> RESTRICTED; >=70 -> ACTIVE

# Travel buffer appended after every booking, in minutes (§3.4).
TRAVEL_BUFFER_MIN = 30

# Reschedule cap (§3.6).
MAX_RESCHEDULES = 3

# Recurring-series day steps (§3.6).
WEEKLY_DAYS = 7
BIWEEKLY_DAYS = 14

# Logical-clock default at server startup (§2.4).
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"

# A clock instant most time-sensitive recipes set first.
CLOCK_BASE = "2026-06-25T08:00:00Z"


TEST_DEFAULTS = {
    "DEFAULT_HOURLY_RATE_CENTS": 4000,
    "TASKER_HOURLY_RATE_CENTS": 5000,
    "FIXED_PRICE_CENTS": 5000,
    "DEFAULT_DURATION_MINUTES": 60,
}
