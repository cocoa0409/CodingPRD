"""Domain thresholds — numeric constants from the PRD's pricing, loyalty,
tiering, refund, and allocation computations (PRD §2.5, §2.6, §2.11, §3)."""

# Volume-tier discount on placement (PRD §3.2).
DISCOUNT_TIER_1_MIN_CENTS = 10000
DISCOUNT_TIER_2_MIN_CENTS = 30000
DISCOUNT_TIER_1_RATE = 0.05
DISCOUNT_TIER_2_RATE = 0.10

# Shipping keyed on net-after-loyalty (PRD §3.2).
FREE_SHIP_THRESHOLD_CENTS = 7500
SHIPPING_FLAT_CENTS = 595

# Loyalty (PRD §2.5, §3.3).
POINT_VALUE_CENTS = 1
TIER_MULT_BRONZE = 1.0
TIER_MULT_SILVER = 1.25
TIER_MULT_GOLD = 1.5

# Tier thresholds keyed on lifetime spend (PRD §3.3).
SILVER_MIN_CENTS = 50000
GOLD_MIN_CENTS = 200000

# Return refund (PRD §3.5).
RESTOCK_FEE_ESTIMATE_CENTS = 500
OPENED_RESTOCK_PCT = 0.20

# Allocation window buffer (PRD §3.7).
ALLOCATION_BUFFER_HOURS = 24

# Logical clock startup default (PRD §2.11).
DEFAULT_CLOCK_UTC = "2026-07-01T00:00:00Z"

# Pagination (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def tier_multiplier(tier: str) -> float:
    """Loyalty multiplier keyed on the customer's tier (PRD §3.3)."""
    return {
        "BRONZE": TIER_MULT_BRONZE,
        "SILVER": TIER_MULT_SILVER,
        "GOLD": TIER_MULT_GOLD,
    }[tier]
