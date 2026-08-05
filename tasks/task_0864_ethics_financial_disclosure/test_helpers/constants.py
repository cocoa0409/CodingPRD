"""Domain thresholds — numeric constants from the PRD calculations and policies."""

# Late-filing penalty formula (PRD section 3.4).
PENALTY = {
    "TIER1_MAX_DAYS": 30,
    "TIER2_MAX_DAYS": 90,
    "TIER2_MULT": 2,
    "TIER3_MULT": 3,
    "CATEGORY_MULTIPLIER": {
        "ELECTED": 2.0,
        "APPOINTED": 1.5,
        "SENIOR_STAFF": 1.0,
        "CANDIDATE": 1.0,
    },
}

# Compliance / delinquency gate (PRD section 2.9).
DELINQUENCY_BLOCK_THRESHOLD_CENTS = 10000

# Travel valuation (PRD section 3.6).
MILEAGE_RATE_CENTS_PER_MILE = 65.5

# Training validity window (PRD section 3.9).
TRAINING_VALIDITY_DAYS = 365

# Jurisdiction policy defaults (PRD section 3.1).
JURISDICTION_DEFAULTS = {
    "gift_single_limit_cents": 5000,
    "gift_annual_source_limit_cents": 25000,
    "penalty_base_fee_cents": 5000,
    "penalty_daily_rate_cents": 250,
    "penalty_cap_cents": 50000,
}

# Pagination bounds (PRD section 2.3).
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100}

# Startup logical-clock default (PRD section 2.10).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
