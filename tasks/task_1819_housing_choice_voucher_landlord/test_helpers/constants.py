"""Domain thresholds — numeric constants from PRD §2.7, §3.2, §3.4."""

# PRD §2.7: the logical clock reads exactly 2026-08-01T00:00:00Z before any client advances it.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # PRD §2.7: family's minimum share is thirty percent of monthly income.
    "INCOME_RATIO": 0.30,
    # PRD §2.7: rent-reasonableness ceiling is ten percent above the comparable-rent median.
    "COMPARABLE_CAP_RATIO": 1.10,
    # PRD §3.2: comparables must fall within the twelve months preceding the current logical date.
    "COMPARABLE_RECENCY_MONTHS": 12,
    # PRD §3.4: an ordinary item allows the landlord thirty days;
    # a life-threatening item allows only one day.
    "REPAIR_WINDOW_DAYS": 30,
    "LIFE_THREATENING_WINDOW_DAYS": 1,
}

TEST_DEFAULTS = {
    "PAYMENT_STANDARD_CENTS": 150_000,
    "CONTRACT_RENT_CENTS": 150_000,
    "ANNUAL_INCOME_CENTS": 2_400_000,
    "EFFECTIVE_FROM": "2026-01-01",
    "LEASE_START_DATE": "2026-08-01",
}
