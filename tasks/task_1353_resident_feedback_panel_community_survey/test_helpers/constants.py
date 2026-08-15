"""Domain thresholds — numeric constants named in the PRD calculations."""

# Logical clock default at startup (PRD §2.5)
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Incentive award calculation constants (PRD §3.6)
LOCALE_BONUS_PCT = 0.10
MAX_AWARD_CENTS = 10000
SPEEDER_MIN_SECONDS = 120
LOW_EFFORT_MIN_PCT = 50

# Contact discipline (PRD §3.5)
WASHOUT_DAYS = 7
CONTACT_CAP = 3
CONTACT_WINDOW_DAYS = 7
REMINDER_GAP_HOURS = 48
REMINDER_CAP = 2

# Missed-streak lapse threshold (PRD §3.2)
STRIKE_LIMIT = 2

# Weighting trim multiplier (PRD §3.7)
TRIM_MULT = 5.0

# Default publication k-anonymity threshold (PRD §3.7)
DEFAULT_K_THRESHOLD = 5

# Refresh-run default attrition grace (PRD §3.9)
DEFAULT_ATTRITION_GRACE_DAYS = 30

TEST_DEFAULTS = {
    "BASE_INCENTIVE_CENTS": 1000,
    "POOL_TOTAL_CENTS": 100000,
    "MIN_RESPONSE_RATE": 0.5,
    "OPENS_AT": "2026-08-02T00:00:00Z",
    "CLOSES_AT": "2026-08-10T00:00:00Z",
    "FIELDING_NOW": "2026-08-03T00:00:00Z",
    "AFTER_CLOSE": "2026-08-11T00:00:00Z",
}
