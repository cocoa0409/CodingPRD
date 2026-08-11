"""Domain thresholds and numeric constants from PRD §3.

Logical clock: at server startup the logical clock reads 2026-05-01T00:00:00Z
(PRD §2.6). Tests that drive time forward use CLOCK_START as their baseline.
"""

CLOCK_START = "2026-05-01T00:00:00Z"

# Age-neutral classification thresholds (PRD §3.1)
ABV_NON_ALCOHOLIC_MAX_BPS = 50      # at or below 50 bps is federally non-alcoholic
ABV_MAX_ALLOWED_BPS = 500           # creation above 500 is rejected outright

# Loyalty tier thresholds on lifetime points (PRD §3.3)
SILVER_MIN_POINTS = 5000
GOLD_MIN_POINTS = 20000
PLATINUM_MIN_POINTS = 50000

# Tier multipliers applied to point accrual (PRD §3.3)
TIER_MULTIPLIER = {
    "BRONZE": 1.0,
    "SILVER": 1.25,
    "GOLD": 1.5,
    "PLATINUM": 2.0,
}

# Order charge components (PRD §3.8)
LOYALTY_REDEEM_CENTS_PER_POINT = 1   # each point redeemed is one cent of discount
DTC_BASE_SHIPPING_CENTS = 500        # flat base for DTC orders
DTC_PER_BOTTLE_CENTS = 150           # per bottle (sum of qty across lines)

# Special order loyalty bonus (PRD §3.10)
SPECIAL_ORDER_BONUS_POINTS_PER_BOTTLE = 10

# Club billing cadence in months (PRD §3.7)
CADENCE_MONTHS = {"MONTHLY": 1, "QUARTERLY": 3, "ANNUAL": 12}
