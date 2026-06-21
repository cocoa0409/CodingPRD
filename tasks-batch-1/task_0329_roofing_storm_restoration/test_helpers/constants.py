"""Domain thresholds — numeric constants drawn from the PRD calculations (§3).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Material order sizing (PRD §3.4)
MIN_BUNDLES = 12
BUNDLES_PER_SQUARE = 3
SHINGLE_WASTE = 0.15
WEIGHT_PER_BUNDLE_LBS = 80

# Freight tiers (PRD §3.4)
FREIGHT_TIER1_CENTS = 7500        # total_weight_lbs <= 2000
FREIGHT_TIER2_CENTS = 12500       # 2000 < total_weight_lbs <= 4000
FREIGHT_TIER3_BASE_CENTS = 12500  # base above 4000
FREIGHT_TIER3_STEP_CENTS = 3000   # per whole (or part) 1000 lbs above 4000

# Permit-final inspection spacing buffer (PRD §3.5)
BUFFER_HOURS = 24

# Warranty refund (PRD §3.10)
SHORT_RATE_FACTOR = 0.90
DEFAULT_TERM_MONTHS = 120

# Job retainage (PRD §2.6)
DEFAULT_RETAINAGE_PCT = 0.10
RETAINAGE_PCT_MAX = 0.20

# Estimate (PRD §3.2)
DEFAULT_AERIAL_CONTINGENCY_PCT = 0.08
DEFAULT_WASTE_FACTOR_PCT = 0.10

# Crew (PRD §3.6)
DEFAULT_MAX_SQUARES_PER_DAY = 30

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


TEST_DEFAULTS = {
    "CONTRACT_VALUE_CENTS": 110_000,   # single SHINGLE 10sq@10000 waste0.10 FIELD estimate
    "UNIT_PRICE_CENTS": 10_000,
    "SQUARES": 10,
}
