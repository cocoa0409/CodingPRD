"""Domain constants and defaults for the ERAP API tests."""

# Server logical-clock default (PRD §3.1); tests set a fixed clock for determinism.
DEFAULT_CLOCK_UTC = "2026-02-15T00:00:00Z"
SERVER_DEFAULT_CLOCK_UTC = "2026-03-01T00:00:00Z"

# Program defaults (PRD §3.1). months_cap defaults to 18, eligibility_ami_pct to 0.80.
DEFAULT_MONTHS_CAP = 18
DEFAULT_ELIGIBILITY_AMI_PCT = 0.80

# A generous income-limit table keyed by household size (cents/month).
DEFAULT_INCOME_LIMIT_BY_SIZE = {
    "1": 500000,
    "2": 566667,
    "3": 641667,
    "4": 708334,
}

TEST_DEFAULTS = {
    "FUNDING_POOL_TOTAL_CENTS": 100_000_000,
    "PER_MONTH_MAX_CENTS": 250_000,
    "UNIT_RENT_CENTS": 200_000,
    "APP_RENT_CENTS": 200_000,
}
