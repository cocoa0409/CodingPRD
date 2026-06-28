"""Domain thresholds — numeric constants from PRD calculations and defaults.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Program-level defaults (PRD §3.1).
PROGRAM_DEFAULTS = {
    "CURRENCY": "USD",
    "DEFAULT_FEE_RATE_PER_DAY": 0.0005,
    "TIER2_MULTIPLIER": 1.5,
    "TIER3_MULTIPLIER": 2.0,
    "RECOURSE_GRACE_DAYS": 90,
}

# Fee / aging calculation constants (PRD §2.10, §3.6, §3.7).
THRESHOLDS = {
    "DAY_SECONDS": 86400,
    "TIER1_MAX_DAYS": 30,
    "TIER2_MAX_DAYS": 30,   # additional days in tier 2 (days 31-60)
    "BUCKET1_MAX_DPD": 30,  # dpd<=30 -> DPD_1_30
    "BUCKET2_MAX_DPD": 60,  # dpd<=60 -> DPD_31_60
    "BUCKET3_MAX_DPD": 90,  # dpd<=90 -> DPD_61_90
}

# Convenient large headroom values used when a given check must NOT be the
# binding constraint in a test.
TEST_DEFAULTS = {
    "BIG_CREDIT_LIMIT_CENTS": 100_000_000,
    "BIG_CEILING_CENTS": 100_000_000,
    "BIG_CONCENTRATION_PCT": 0.90,
    "ADVANCE_RATE_PCT": 0.85,
}

# The logical clock startup default (PRD §2.4). Funding at the default clock
# stamps funded_at = this value.
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"
