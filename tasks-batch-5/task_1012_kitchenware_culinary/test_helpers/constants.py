"""Domain thresholds — numeric constants from the PRD's pricing, loyalty,
tier, inventory, return, and scheduling rules (PRD §2.7–§2.9, §3.3–§3.6).
"""

# Tier discount percentages keyed off the order's snapshotted tier (PRD §3.3).
TIER_DISCOUNT_PCT = {"STANDARD": 0.00, "SILVER": 0.05, "GOLD": 0.10}

# Tax rate by store jurisdiction (PRD §3.3).
TAX_RATE = {"CA": 0.0875, "OR": 0.00, "NY": 0.08}

# Tier discount is capped so it never exceeds this many cents (PRD §3.3).
DISCOUNT_CAP_CENTS = 20000

# Loyalty points multiplier keyed off the snapshotted tier (PRD §3.3 / §3.4).
POINTS_MULT = {"STANDARD": 1.00, "SILVER": 1.25, "GOLD": 1.50}
POINTS_PER_CENT_DIVISOR = 100

# Loyalty tier thresholds, inclusive at the lower edge (PRD §2.9).
SILVER_THRESHOLD_CENTS = 50000
GOLD_THRESHOLD_CENTS = 150000

# Trailing spend window (PRD §2.9).
SPEND_WINDOW_DAYS = 365

# Return policy window in days (PRD §3.4).
RETURN_WINDOW_DAYS = 30

# Service bar buffer padding, minutes on each side of a ticket (PRD §3.6).
SERVICE_BUFFER_MINUTES = 30

# Logical-clock startup default (PRD §2.5).
CLOCK_DEFAULT = "2026-07-01T00:00:00Z"

TEST_DEFAULTS = {
    "LIST_PRICE_CENTS": 10000,
    "ON_HAND_QTY": 10,
    "CLASS_PRICE_CENTS": 5000,
    "SERVICE_PRICE_CENTS": 1500,
}
