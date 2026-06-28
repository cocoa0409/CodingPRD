"""Domain thresholds — numeric constants from the PRD calculations (all integer cents)."""

# IRS contribution-limit figures (PRD §3.3).
ANNUAL_LIMITS = {
    "SELF_ANNUAL": 432000,      # $4,320.00
    "FAMILY_ANNUAL": 862500,    # $8,625.00
    "CATCHUP_ANNUAL": 100000,   # $1,000.00
}

# Account defaults at open (PRD §3.2).
ACCOUNT_DEFAULTS = {
    "INVEST_THRESHOLD_CENTS": 200000,   # liquid floor kept un-sweepable
    "SWEEP_INCREMENT_CENTS": 10000,     # whole-multiple sweep granularity
}

DEFAULT_PLAN_YEAR = 2026

# Logical clock startup default (PRD §3.11).
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"
