"""Domain thresholds — numeric constants from the PRD's pricing, points,
payout, installment, and refund rules (PRD §3.7–§3.12).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Season pricing (PRD §3.7)
MIN_PARTIAL_FLOOR_CENTS = 100000
LOYALTY_BPS = {
    "BRONZE": 0,
    "SILVER": 500,
    "GOLD": 1000,
}

# Loyalty tier boundaries (PRD §3.2): BRONZE < 500 <= SILVER < 1000 <= GOLD
LOYALTY_SILVER_FLOOR = 500
LOYALTY_GOLD_FLOOR = 1000

# Priority-points accrual (PRD §3.8)
SEAT_POINT_VALUE = 100
TENURE_POINT_VALUE = 50
PLAYOFF_BONUS_PER_SEAT = 200

# Resale payout fees (PRD §3.9)
MARKETPLACE_FEE_BPS = 750
PROCESSING_FEE_BPS = 290

# Installment waterfall (PRD §3.10)
DOWN_PAYMENT_BPS = 2500
INSTALLMENT_COUNT_MIN = 2
INSTALLMENT_COUNT_MAX = 12

# Cancellation refund (PRD §3.11)
CANCELLATION_FEE_BPS = 1000

# Basis-point denominator (PRD §2.7)
BPS_DENOMINATOR = 10000

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# A canonical season window used across setups; closed inclusive interval.
SEASON_START = "2026-10-01T00:00:00.000Z"
SEASON_END = "2027-04-01T00:00:00.000Z"
# An adjacent window sharing the endpoint date with the canonical window's end.
SEASON_ADJACENT_START = "2027-04-01T00:00:00.000Z"
SEASON_ADJACENT_END = "2027-09-01T00:00:00.000Z"
