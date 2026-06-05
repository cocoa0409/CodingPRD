"""Domain thresholds — numeric constants from PRD calculations and defaults."""

# Fixed penalty / rate constants (PRD §3.7).
CLOPENING_PENALTY_CENTS = 5000        # flat clopening penalty
SHORT_NOTICE_POST_RATE = 0.25         # one quarter
SHORT_NOTICE_CANCEL_RATE = 0.5        # one half

# Worker suspension threshold (PRD §3.1): strikes reach three -> SUSPENDED.
NO_SHOW_STRIKE_CEILING = 3

# Location dial defaults (PRD §3.1).
DEFAULT_ADVANCE_NOTICE_DAYS = 14
DEFAULT_MIN_REST_HOURS = 10
DEFAULT_OVERTIME_WEEKLY_THRESHOLD_HOURS = 40
DEFAULT_OVERTIME_MULTIPLIER = 1.5

# Worker minor-cap defaults (PRD §3.1).
DEFAULT_MINOR_DAILY_CAP_HOURS = 8
DEFAULT_MINOR_WEEKLY_CAP_HOURS = 18

# Common test values used across fixtures.
TEST_DEFAULTS = {
    "BASE_HOURLY_RATE_CENTS": 2000,
    "HIGH_GUARDRAIL_CENTS": 100_000_000,
    "ROLE_NAME": "Cashier",
    "TIME_ZONE": "UTC",
}
