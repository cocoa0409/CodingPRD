"""Domain thresholds — numeric constants from the PRD's pricing, loyalty,
refund, and delivery rules."""

# Markdown cadence (PRD §3.1)
REGULAR_TIER_WEEKS = [4, 8, 12]           # FULL / MARKDOWN_1 / MARKDOWN_2 / CLEARANCE breakpoints
REGULAR_PCT = [0.00, 0.15, 0.30, 0.50]
TREASURE_TIER_WEEKS = [8]                 # FULL / CLEARANCE breakpoint
TREASURE_PCT = [0.00, 0.40]

# Loyalty tiers (PRD §3.3)
SILVER_MIN_CENTS = 50_000
GOLD_MIN_CENTS = 200_000

# Checkout discount by tier (PRD §3.4)
TIER_DISCOUNT_PCT = {"STANDARD": 0.00, "SILVER": 0.05, "GOLD": 0.10}

# Points-earning multiplier by tier (PRD §3.4)
TIER_RATE = {"STANDARD": 1, "SILVER": 2, "GOLD": 3}

# Returns (PRD §3.7)
RESTOCK_FEE_PCT = 0.15
RETURN_WINDOW_DAYS = 30

# Special orders (PRD §3.9)
DEPOSIT_PCT = 0.25

# Logical clock startup default (PRD §2.6)
CLOCK_DEFAULT = "2026-07-01T00:00:00Z"

TEST_DEFAULTS = {
    "BASE_PRICE_CENTS": 1000,
    "CLEARANCE_FLOOR_CENTS": 100,
    "ALLOCATED_QTY": 10,
}
