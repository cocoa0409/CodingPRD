"""Domain thresholds and shared values — numeric constants from PRD §2.5–§3."""

# Logical clock startup default (PRD §2.5)
CLOCK_START = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # Extraordinary fee schedule (PRD §3.8)
    "FEE_TIER1_HOURS": 10,
    "FEE_TIER2_MULTIPLIER": 1.5,
    "FEE_CAP_MULTIPLE": 4,
    # Collateral haircuts in basis points (PRD §3.7)
    "HAIRCUT_REAL_ESTATE_BPS": 2000,
    "HAIRCUT_EQUIPMENT_BPS": 3000,
    "HAIRCUT_SECURITIES_BPS": 500,
    "HAIRCUT_GUARANTEE_BPS": 4000,
    "SUBSTITUTE_HAIRCUT_HIGH_TIER_BPS": 1000,
    "SUBSTITUTE_HAIRCUT_STANDARD_BPS": 2500,
    "HIGH_TIER_RATIO": 2.0,
    "MIN_COVERAGE_BPS": 12500,
    "VALUATION_FRESHNESS_DAYS": 180,
    # Direction quorum rules (PRD §3.5): supporting*4 >= eligible (inclusive 25%),
    # rescind: supporting*2 > eligible (strict 50%)
    "ACCELERATE_QUORUM_NUMERATOR": 1,
    "ACCELERATE_QUORUM_DENOMINATOR": 4,
    "RESCIND_QUORUM_NUMERATOR": 1,
    "RESCIND_QUORUM_DENOMINATOR": 2,
    # Consent cross-multiplication constant (PRD §3.6)
    "CONSENT_CROSS_MULTIPLY": 10000,
    # Defaults (PRD §3.1, §3.3)
    "DEFAULT_NOTICE_PERIOD_DAYS": 30,
    "DEFAULT_GRACE_PERIOD_DAYS": 10,
    # Covenant breach auto-case cure window (PRD §3.3)
    "BREACH_CASE_CURE_DAYS": 30,
}

TEST_DEFAULTS = {
    "ANNUAL_ADMIN_FEE_CENTS": 2500000,
    "EXTRAORDINARY_HOURLY_RATE_CENTS": 45000,
    "DEFAULT_HOURLY_RATE_CENTS": 65000,
    "GOVERNING_LAW": "NY",
    "INITIAL_TRUSTEE_REF": "trustee-alpha",
    "INTEREST_RATE_BPS": 500,
    "MATURITY_DATE": "2030-12-15",
    # Canonical interest accrual window used across tests
    "INTEREST_PERIOD_START": "2026-06-15",
    "INTEREST_PERIOD_END": "2026-12-15",
    "INTEREST_PAYMENT_DATE": "2026-12-15",
    "CURE_DEADLINE": "2026-12-31T00:00:00Z",
    "DIRECTION_EXPIRY": "2026-12-31T00:00:00Z",
}
