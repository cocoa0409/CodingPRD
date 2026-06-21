"""Domain thresholds — numeric constants from PRD calculations."""

# Poverty guideline base (cents per year) for the one-person guideline.
POVERTY_BASE_CENTS = {
    "CONTIGUOUS_48": 1_558_000,
    "ALASKA":        1_947_000,
    "HAWAII":        1_791_000,
}

# Per-additional-family-member increment (cents per year).
POVERTY_PER_MEMBER_CENTS = {
    "CONTIGUOUS_48": 548_000,
    "ALASKA":        686_000,
    "HAWAII":        630_000,
}

# Plan multipliers for discretionary income computation.
DISCRETIONARY_MULTIPLIER_IBR_PAYE = 1.50
DISCRETIONARY_MULTIPLIER_SAVE = 2.25

# Annual obligation rates.
IBR_RATE = 0.15
PAYE_RATE = 0.10
SAVE_RATE = 0.10

# 10-year amortization for STANDARD plan.
STANDARD_TERM_MONTHS = 120

# Daily-accrual divisor.
DAYS_PER_YEAR = 365

# Default-declaration delinquency threshold (days).
DEFAULT_DELINQUENCY_THRESHOLD = 270

# Rehabilitation precondition: number of post-default APPLIED payments required.
REHABILITATION_PAYMENT_COUNT = 9

# PSLF discharge precondition: number of qualifying payments required.
PSLF_QUALIFYING_PAYMENT_THRESHOLD = 120

# Qualifying employer types for PSLF.
QUALIFYING_EMPLOYER_TYPES = ["GOVERNMENT", "NONPROFIT_501C3"]
