"""Domain thresholds and constants drawn from the PRD pricing/royalty rules."""

# Size upcharge added to the SMALL base price (§3.5).
SIZE_UPCHARGE_CENTS = {"SMALL": 0, "MEDIUM": 100, "LARGE": 200}

# Ingredient-quantity and calorie scaling factor by size (§3.5, §3.6).
SIZE_QTY_FACTOR = {"SMALL": 1.0, "MEDIUM": 1.5, "LARGE": 2.0}

# Loyalty-tier discount percentage applied to the subsidized base (§3.5).
LOYALTY_TIER_DISCOUNT_PCT = {"BRONZE": 0.00, "SILVER": 0.05, "GOLD": 0.10}

# Order/catering tax rate (§3.5, §3.7).
TAX_RATE = 0.08

# Loyalty tier thresholds on lifetime_points_earned (§3.3).
SILVER_THRESHOLD = 500
GOLD_THRESHOLD = 1500

# One loyalty point per whole dollar of discounted subtotal (§3.6).
POINTS_PER_DOLLAR = 1

# Volume rebate on royalty (§3.8): net sales >= threshold => flat rebate rate.
REBATE_THRESHOLD_CENTS = 50000
REBATE_RATE = 0.05

# Catering per-head service fee (§3.7).
CATERING_SERVICE_FEE_PER_HEAD_CENTS = 200

# Logical clock default before any set call (§2.7).
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
