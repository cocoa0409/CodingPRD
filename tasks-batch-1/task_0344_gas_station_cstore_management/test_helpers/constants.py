"""Domain thresholds — numeric constants from PRD calculations and policies."""

# Fuel pump price (PRD §3.7): per-gallon loyalty discount by tier, capped.
TIER_DISCOUNT_CENTS = {"BRONZE": 0, "SILVER": 3, "GOLD": 5}
MAX_DISCOUNT_CENTS = 10

# Loyalty points accrual (PRD §3.7).
POINTS_PER_GALLON = 10
POINTS_PER_DOLLAR = 2
TIER_MULTIPLIER = {"BRONZE": 1.0, "SILVER": 1.25, "GOLD": 1.5}
SILVER_THRESHOLD = 2000
GOLD_THRESHOLD = 5000

# Car-wash pricing (PRD §3.9).
WASH_LIST_CENTS = {"BASIC": 800, "DELUXE": 1200, "SUPREME": 1600}
TIER_WASH_DISCOUNT_PCT = {"BRONZE": 0.0, "SILVER": 0.10, "GOLD": 0.20}
CODE_TTL_DAYS = 30

# Station policy defaults (PRD §3.1).
DEFAULT_TAX_RATE_BP = 825
DEFAULT_CASH_VARIANCE_TOLERANCE_CENTS = 200

# Convenience test constants reused across fixtures.
TEST_DEFAULTS = {
    "OPENING_FLOAT": 20000,
    "STANDARD_PRICE": 419,
    "STANDARD_CAPACITY": 10000,
    "STANDARD_REORDER": 1500,
}

# Amount of CARD store subtotal cents that pushes a member to GOLD in a single
# settle: floor(250000/100)*2 = 5000 lifetime points == GOLD_THRESHOLD.
GOLD_SEED_SUBTOTAL_CENTS = 250000
