"""Domain thresholds — numeric constants from the PRD's calculations."""

# Sliding-scale price multipliers (PRD §3.2).
SLIDING_SCALE_MULTIPLIER = {
    "SOLIDARITY": 0.80,
    "BASELINE": 1.00,
    "SUSTAINER": 1.25,
}

# Working-share labor credit (PRD §3.9).
WORK_CREDIT_RATE_CENTS_PER_HOUR = 1500
WORK_CREDIT_DAILY_HOUR_CAP = 6

# Waitlist offer window (PRD §3.8): promotion sets offer_expires_at to clock + 48h.
OFFER_WINDOW_HOURS = 48

# Pagination bounds (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Common test defaults used across fixtures.
TEST_DEFAULTS = {
    "WEEK_COUNT": 12,
    "MEDIUM_BASE_PRICE_CENTS": 50000,
    "FIRST_DELIVERY_DATE": "2026-07-01T00:00:00Z",
    "SIGNUP_CLOSE_DATE": "2026-12-30T00:00:00Z",
    "TOTAL_SHARE_CAPACITY": 100,
    "SITE_WEEKLY_CAPACITY": 100,
}
