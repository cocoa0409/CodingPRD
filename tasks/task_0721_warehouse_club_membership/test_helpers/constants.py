"""Domain thresholds — numeric constants from PRD calculations."""

# Term length and no-receipt eligibility window (PRD §3.7, §3.8).
TERM_DAYS = 365
NO_RECEIPT_WINDOW_DAYS = 90
BPS_DIVISOR = 10000

# Server startup default clock instant (PRD §2.11).
DEFAULT_CLOCK_UTC = "2026-03-01T00:00:00Z"

# Reusable test payload defaults.
TEST_DEFAULTS = {
    "BASIC_ANNUAL_FEE": 6000,
    "EXEC_ANNUAL_FEE": 12000,
    "EXEC_REWARD_RATE_BPS": 200,
    "EXEC_REWARD_CAP": 100000,
    "MAX_HOUSEHOLD_CARDS": 1,
    "BASIC_ADDON_FEE": 4000,
    "EXEC_ADDON_FEE": 6000,
    "LIST_PRICE": 10000,
    "MEMBER_PRICE": 8000,
}
