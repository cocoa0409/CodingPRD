"""Domain thresholds — numeric constants from the PRD."""

# Platform withholds 10% of each paid invoice (PRD §3.5, §2.6).
PLATFORM_FEE_PCT = 10

# The logical clock reads this at startup until an operator moves it (PRD §2.5).
CLOCK_START_UTC = "2026-03-01T00:00:00Z"

# Course-level refund default (PRD §3.2).
DEFAULT_REFUND_WINDOW_DAYS = 14

TEST_DEFAULTS = {
    "ONE_TIME_AMOUNT_CENTS": 20000,
    "REFUND_WINDOW_DAYS": 14,
}

# Pagination envelope defaults (PRD §2.3).
PAGINATION = {"limit": 10, "min": 1, "max": 100, "offset": 0}
