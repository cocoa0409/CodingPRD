"""Domain thresholds and pinned constants from the PRD."""

# Logical clock startup default (PRD section 2.5).
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Standard lumber window used across setups (covers the default clock).
INDEX_WINDOW_START = "2026-07-01T00:00:00Z"
INDEX_WINDOW_END = "2026-09-01T00:00:00Z"
PINE_PRICE_PER_MBF_CENTS = 400_000
OAK_PRICE_PER_MBF_CENTS = 600_000

# Grade price book, cents per pallet (PRD section 3.6).
PRICE_NEW_CENTS = 1500
PRICE_A_CENTS = 1100
PRICE_B_CENTS = 800
BASE_MULTIPLIER_BP = 10_000

# New-build overhead tiers by quantity_total (PRD section 3.5).
OVERHEAD_TIER1_MAX = 100     # qty < 100  -> 18%
OVERHEAD_TIER2_MAX = 500     # 100 <= qty < 500 -> 12%; qty >= 500 -> 9%
OVERHEAD_RATE_T1 = 0.18
OVERHEAD_RATE_T2 = 0.12
OVERHEAD_RATE_T3 = 0.09

# Recycled repair cost recipe (PRD section 3.5).
LABOR_RATE_CENTS_PER_MIN = 95
GRADE_A_FACTOR = 1.00
GRADE_B_FACTOR = 0.60

# Batch settlement (PRD section 3.3).
SCRAP_VALUE_CENTS = 0
SHORTAGE_PENALTY_FACTOR = 0.25

# Pool credit tier table, cents per returned unit (PRD section 3.7).
POOL_CREDIT_A_CENTS = 700
POOL_CREDIT_B_CENTS = 350
POOL_CREDIT_SCRAP_CENTS = 0

# Route economics (PRD section 3.8).
ROUTE_COST_PER_MILE_CENTS = 185
STOP_COST_CENTS = 4500

# Heat-treatment dwell requirement (PRD section 3.5).
HT_MIN_DURATION_HOURS = 6

# Canonical spec geometry used across tests (48x40x6, 15 boards, PINE):
# board_feet_per_pallet = 15.75, unit_cube_cuft = 6.6667.
SPEC_CODE_GMA = "GMA-48X40-15B"
SPEC_BOARD_FEET = 15.75
SPEC_UNIT_CUBE_CUFT = 6.6667
SPEC_LENGTH_IN = 48
SPEC_WIDTH_IN = 40
SPEC_HEIGHT_IN = 6.0
SPEC_BOARD_COUNT = 15

DEFAULT_DELIVERY_DATE = "2026-08-10T00:00:00Z"
DEFAULT_ROUTE_DATE = "2026-08-10T00:00:00Z"
