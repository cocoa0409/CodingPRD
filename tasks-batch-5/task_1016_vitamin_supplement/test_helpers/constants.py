"""Domain thresholds and constants declared in the PRD.

All values below are stated verbatim in the PRD prose (Sections 2.5, 3.3, 3.5,
3.6, 3.7) and are safe for tests to depend on.
"""

# Loyalty tier thresholds (PRD §3.3) — inclusive at the boundary.
TIER_SILVER_THRESHOLD = 500
TIER_GOLD_THRESHOLD = 1000

# One-off purchase discount by loyalty tier (PRD §3.6).
LOYALTY_PURCHASE_DISCOUNT = {"BRONZE": 0.00, "SILVER": 0.05, "GOLD": 0.10}

# Auto-ship per-line discount by cadence (PRD §3.5).
AUTOSHIP_DISCOUNT = {30: 0.05, 60: 0.08, 90: 0.10}

# Loyalty earning (PRD §3.6).
POINTS_PER_DOLLAR_CENTS = 100
TIER_EARN_MULTIPLIER = {"BRONZE": 1.0, "SILVER": 1.25, "GOLD": 1.5}
AUTOSHIP_EARN_BONUS = 0.25
POINTS_PER_ORDER_CAP = 2000

# Point redemption (PRD §3.6): 1 point = 1 cent.
POINT_REDEMPTION_VALUE_CENTS = 1

# Return restocking fee for the UNWANTED variant (PRD §3.7).
RESTOCK_FEE_PCT = 0.15

# Subscription scheduling buffer (PRD §3.5): 7 days.
SUBSCRIPTION_BUFFER_DAYS = 7

# Logical clock startup default (PRD §2.12).
CLOCK_STARTUP_DEFAULT = "2026-07-01T00:00:00Z"

# Valid cadence values (PRD §3.5).
VALID_CADENCE_DAYS = [30, 60, 90]
