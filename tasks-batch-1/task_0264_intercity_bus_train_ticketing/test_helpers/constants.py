"""Domain thresholds — numeric constants stated in the PRD's pricing,
settlement, and fee rules. Generic NON_EXISTENT_UUID comes from the framework.
"""

# Demand-pricing tiers (PRD §3.4): load-factor lower-inclusive thresholds.
DEMAND_TIER_MID = 0.5          # lf >= 0.5 enters the 1.25 tier
DEMAND_TIER_HIGH = 0.8         # lf >= 0.8 enters the 1.60 tier
DEMAND_MULT_LOW = 1.00
DEMAND_MULT_MID = 1.25
DEMAND_MULT_HIGH = 1.60

# Advance-window tiers (PRD §3.4): whole-day calendar difference thresholds.
ADV_DAYS_EARLY = 14           # >= 14 days -> 0.90
ADV_DAYS_MID = 7              # >= 7 -> 1.00
ADV_DAYS_LATE = 3            # >= 3 -> 1.15
ADV_FACTOR_EARLY = 0.90
ADV_FACTOR_MID = 1.00
ADV_FACTOR_LATE = 1.15
ADV_FACTOR_LAST = 1.40       # < 3 days

# Cancellation penalty tiers (PRD §3.6): days-before-departure thresholds.
PENALTY_FREE_DAYS = 7         # >= 7 -> 0.00
PENALTY_MID_DAYS = 1         # >= 1 -> 0.25
PENALTY_PCT_MID = 0.25
PENALTY_PCT_LAST = 0.50      # same-day, < 1 day
CREDIT_LENIENCY_PCT = 0.10   # travel-credit is 10 percentage points more lenient

# Baggage overweight fee (PRD §3.11).
FREE_BAG_KG = 23.0
OVERWEIGHT_RATE_CENTS_PER_KG = 500

# Operator policy defaults (PRD §3.1).
DEFAULT_CONNECTION_BUFFER_MIN = 30
DEFAULT_EXCHANGE_FEE_CENTS = 1000

# Pagination bounds (PRD §2.3).
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_MIN = 0
