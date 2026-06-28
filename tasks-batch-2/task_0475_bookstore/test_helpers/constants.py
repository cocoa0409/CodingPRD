"""Domain thresholds — numeric constants from PRD calculations (§3)."""

# Buyback offer (§3.6)
BUYBACK_BASE_RATE = 0.30
BUYBACK_DEMAND_BONUS = 0.10
GRADE_MULT = {"LIKE_NEW": 1.00, "GOOD": 0.70, "FAIR": 0.40}

# Order pricing + loyalty (§3.4, §3.5)
GOLD_DISCOUNT_RATE = 0.05
MONTHLY_POINT_CAP = 1000
EARN_DIVISOR = 100

# Consignment payout tiers (§3.9)
CONSIGNMENT_TIER_1_RATE = 0.40
CONSIGNMENT_TIER_2_RATE = 0.35
CONSIGNMENT_TIER_3_RATE = 0.30
CONSIGNMENT_TIER_2_THRESHOLD = 10
CONSIGNMENT_TIER_3_THRESHOLD = 25

# Special-order quote (§3.7)
DISTRIBUTOR_LEAD_DAYS = 7
POD_LEAD_DAYS = 3
POD_MARKUP = 1.20

# Publisher return credit (§3.8)
PUBLISHER_CREDIT_RATE = 0.50

# Event ticket price (§3.10)
HIGH_DEMAND_SURCHARGE = 0.25

# Pagination defaults (§2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# Logical clock startup default (§3.1)
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"
