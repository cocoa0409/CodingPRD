"""Domain thresholds — numeric constants from PRD calculations."""

# Loyalty tier discount percentages (order_pricing)
TIER_DISCOUNT_PCT = {"BRONZE": 0.00, "SILVER": 0.05, "GOLD": 0.10}

# Loyalty tier point multipliers (loyalty_points_earned)
TIER_MULTIPLIER = {"BRONZE": 1.0, "SILVER": 1.5, "GOLD": 2.0}

# Loyalty tier thresholds (loyalty_balance)
SILVER_MIN = 1000
GOLD_MIN = 5000

# Return restocking fee tiers (return_refund)
RESTOCK_TIER1_MAX = 5000    # gross < 5000 -> 0.00
RESTOCK_TIER2_MAX = 20000   # 5000..19999 -> 0.10; >= 20000 -> 0.15
RESTOCK_TIER1_PCT = 0.00
RESTOCK_TIER2_PCT = 0.10
RESTOCK_TIER3_PCT = 0.15

# Return window
RETURN_WINDOW_DAYS = 30

# Points base
POINTS_PER_DOLLAR_BASE = 1

# Default store event buffer
DEFAULT_EVENT_BUFFER_MINUTES = 30

# Logical clock server default
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"
