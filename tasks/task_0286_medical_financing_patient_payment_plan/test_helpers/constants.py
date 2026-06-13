"""Domain thresholds — numeric constants from the PRD calculation rules (§3.2–§3.8)."""

# Credit-decision constants (PRD §3.2)
CREDIT_DECISION = {
    "INCOME_MULTIPLIER": 0.20,
    "ABSOLUTE_CAP_CENTS": 2_500_000,
    "MIN_VIABLE_LINE_CENTS": 50_000,
    "DEFAULT_HAIRCUT_PER_PRIOR": 0.25,
    "DEFAULT_COUNT_CAP": 3,
}

# Deferred-interest constants (PRD §3.8)
DEFERRED_INTEREST = {
    "DAYS_PER_YEAR": 360,
}

# Volume-tier settlement-fee constants (PRD §3.5)
SETTLEMENT_FEE = {
    "TIER1_THRESHOLD_CENTS": 5_000_000,
    "TIER2_THRESHOLD_CENTS": 1_000_000,
    "TIER1_DELTA": 0.02,
    "TIER2_DELTA": 0.01,
    "MIN_RATE": 0.02,
}

# Minimum-payment constants (PRD §3.7)
MINIMUM_PAYMENT = {
    "FLOOR_PAYMENT_CENTS": 2_500,
}

# Delinquency threshold (PRD §3.7): third strike defaults the account.
DELINQUENCY = {
    "DEFAULT_STRIKE_COUNT": 3,
}

# Field range bounds surfaced as ERR_VALIDATION_AMOUNT (PRD §2.8)
RANGES = {
    "BASE_MERCHANT_DISCOUNT_RATE_MAX": 0.30,
    "PROMO_APR_MAX": 0.3599,
    "DEFERRED_PERIOD_MONTHS_MIN": 1,
    "DEFERRED_PERIOD_MONTHS_MAX": 60,
    "DRAFT_DAY_OF_MONTH_MIN": 1,
    "DRAFT_DAY_OF_MONTH_MAX": 28,
}

# Common test values used across fixtures.
TEST_DEFAULTS = {
    "BASE_RATE": 0.08,
    "INCOME_CENTS": 6_000_000,
    "REQUESTED_LIMIT_CENTS": 500_000,
}
