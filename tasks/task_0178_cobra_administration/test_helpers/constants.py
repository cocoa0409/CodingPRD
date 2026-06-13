"""Domain thresholds — numeric constants from the COBRA Administration PRD
(§3.1, §3.5, §3.6, §3.8).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Plan defaults (PRD §3.1)
PLAN_DEFAULTS = {
    "STANDARD_ADMIN_FEE_PCT": 0.02,        # 2% -> 102% of applicable premium
    "DISABILITY_ADMIN_FEE_PCT": 0.50,      # 50% -> 150% of applicable premium
    "EMPLOYER_NOTICE_DAYS": 30,
    "ELECTION_NOTICE_DAYS": 14,
    "ELECTION_WINDOW_DAYS": 60,
    "INITIAL_PREMIUM_GRACE_DAYS": 45,
    "RECURRING_PREMIUM_GRACE_DAYS": 30,
    "INSIGNIFICANT_SHORTFALL_FLOOR_CENTS": 5000,
}

# Calculation thresholds (PRD §3.5, §3.6, §3.8)
THRESHOLDS = {
    "SHORTFALL_FLOOR_CENTS": 5000,         # $50 floor (PRD §3.6)
    "SHORTFALL_PCT": 0.10,                 # 10% of beneficiary_owed (PRD §3.6)
    "DETERMINATION_WINDOW_DAYS": 60,       # first 60 days of coverage (PRD §3.8)
    "EXTENSION_MONTHS": 11,                # 18 -> 29 months (PRD §3.8)
    "BASE_MONTHS_18": 18,                  # TERMINATION / REDUCTION_OF_HOURS
    "BASE_MONTHS_36": 36,                  # DIVORCE / DEATH / MEDICARE / AGE_OUT
}

# Canonical "Plan A" fixture values used throughout the design indices.
# applicable_premium 60000 @2% => monthly premium 61200.
# disability @50% => 90000.
TEST_DEFAULTS = {
    "APPLICABLE_PREMIUM_CENTS": 60000,
    "MONTHLY_PREMIUM_CENTS": 61200,        # round_half_up(60000 * 1.02)
    "DISABILITY_PREMIUM_CENTS": 90000,     # round_half_up(60000 * 1.50)
    "INSIGNIFICANT_ALLOWANCE_CENTS": 6120,  # max(5000, round_half_up(0.10 * 61200))
}

# Pagination contract (PRD §2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}
