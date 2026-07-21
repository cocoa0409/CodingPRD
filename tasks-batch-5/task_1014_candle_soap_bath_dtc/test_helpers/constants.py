"""Domain thresholds — numeric constants from the PRD pricing, loyalty, and inventory rules."""

# Pricing (PRD §3.7)
BULK_TIER1_MIN = 50           # >= 50 units -> 10% bulk discount
BULK_TIER2_MIN = 100          # >= 100 units -> 20% bulk discount
BULK_TIER1_PCT = 0.10
BULK_TIER2_PCT = 0.20
SILVER_PCT = 0.05
GOLD_PCT = 0.10
MAX_DISCOUNT_PCT = 0.25       # combined bulk+loyalty cap
FREE_SHIP_THRESHOLD_CENTS = 5000
SHIPPING_FLAT_CENTS = 800

# Bulk order minimum quantity at checkout (PRD §3.7)
BULK_MIN_QUANTITY = 50

# Loyalty (PRD §2.5, §3.5)
CENTS_PER_POINT = 100
SILVER_MIN = 500              # loyalty_tier SILVER lower bound (inclusive)
GOLD_MIN = 2000              # loyalty_tier GOLD lower bound (inclusive)

# Startup default logical clock (PRD §2.8)
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"

THRESHOLDS = {
    "BULK_TIER1_MIN": BULK_TIER1_MIN,
    "BULK_TIER2_MIN": BULK_TIER2_MIN,
    "MAX_DISCOUNT_PCT": MAX_DISCOUNT_PCT,
    "FREE_SHIP_THRESHOLD_CENTS": FREE_SHIP_THRESHOLD_CENTS,
    "SHIPPING_FLAT_CENTS": SHIPPING_FLAT_CENTS,
    "BULK_MIN_QUANTITY": BULK_MIN_QUANTITY,
    "CENTS_PER_POINT": CENTS_PER_POINT,
    "SILVER_MIN": SILVER_MIN,
    "GOLD_MIN": GOLD_MIN,
}
