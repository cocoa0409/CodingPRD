"""Domain thresholds — numeric constants from PRD calculations (PRD §3)."""

# Tiered mileage overage (PRD §3.6): first 200 billable miles are tier one.
OVERAGE_TIER1_LIMIT = 200

# Early cancel forward-looking penalty (PRD §3.12): 50% on projected unfulfilled months.
EARLY_PENALTY_PCT = 0.50

# Eligibility scoring weights (PRD §3.3).
W_CREDIT = 0.5
W_INCOME = 0.3
W_HISTORY = 0.2
INCOME_RATIO_CAP = 5

# Swap fee charged when swaps_used >= included_swaps_per_term (PRD §3.9).
SWAP_FEE_CENTS = 7500

# Pagination bounds (PRD §2.3).
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Default plan parameters used by most fixtures (PLUS tier).
TEST_DEFAULTS = {
    "PLUS_MONTHLY_FEE": 80000,
    "PLUS_INCLUDED_MILES": 1000,
    "PLUS_BUFFER_MILES": 50,
    "PLUS_TIER1_RATE": 25,
    "PLUS_TIER2_RATE": 38,
    "PLUS_INCLUDED_SWAPS": 1,
    "PLUS_MIN_TERM": 6,
    "PLUS_DEPOSIT_BASE": 80000,
    "PREMIUM_MONTHLY_FEE": 95000,
    "PREMIUM_DEPOSIT_BASE": 100000,
}
