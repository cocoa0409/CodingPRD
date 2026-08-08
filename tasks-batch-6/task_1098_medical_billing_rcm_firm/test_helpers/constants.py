"""Domain thresholds and test defaults derived from the PRD calculations."""

# Statement aging bucket day boundaries (PRD §3.7): the boundary falls on the
# lower bucket -- day 30 is CURRENT, day 90 is DAYS_61_90, day 91 is OVER_90.
AGING = {
    "CURRENT_MAX_DAYS": 30,
    "MID_MAX_DAYS": 60,
    "LATE_MAX_DAYS": 90,
    "SECONDS_PER_DAY": 86400,
}

# Appeal cycle limit (PRD §3.5): a claim may not exceed two appeal rounds.
MAX_APPEAL_LEVEL = 2

# Pagination defaults (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# The logical clock reads this before any client sets it (PRD §2.10).
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

# Values reused across many fixtures/tests.
TEST_DEFAULTS = {
    "TIMELY_FILING_DAYS": 90,
    "APPEAL_WINDOW_DAYS": 60,
    "BILLING_FEE_PCT": 0.06,
    "FAR_FUTURE_EXPIRATION": "2027-01-01T00:00:00Z",
}
