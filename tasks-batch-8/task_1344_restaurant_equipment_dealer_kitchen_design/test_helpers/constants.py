"""Domain thresholds and pricing constants (PRD §3.3, §3.4, §3.5)."""

# Freight tiers (PRD §3.3 "Freight")
FREIGHT = {
    "TIER_1_CEILING_CENTS": 5_000_000,    # $50,000
    "TIER_2_CEILING_CENTS": 25_000_000,   # $250,000
    "TIER_1_RATE": 0.06,
    "TIER_2_RATE": 0.045,
    "TIER_3_RATE": 0.03,
    "CUSTOM_FAB_SURCHARGE_CENTS": 150_000,  # flat $1,500
}

# Installation (PRD §3.3 "Installation")
INSTALLATION = {
    "BASE_INSTALL_CENTS": 250_000,   # $2,500 per quote
    "PER_ITEM_CENTS": 45_000,        # $450 per unit of quantity
    "HOOD_PREMIUM_CENTS": 120_000,   # $1,200 per requires_hood item
    "COUNTY_UPLIFT_PCT": 0.10,       # 10% uplift when COUNTY_HEALTH
}

# Startup/demo (PRD §3.3 "Startup and demo")
STARTUP = {
    "BASE_CENTS": 180_000,       # $1,800 per project
    "PER_ITEM_CENTS": 30_000,    # $300 per non-cancelled item
}

# Fabrication cost reconciliation (PRD §3.4)
FABRICATION = {
    "SCHEDULE_ALLOWANCE_DAYS": 30,
    "OVERTIME_PENALTY_RATE": 0.04,   # 4% of quoted cost per overrun day
    "MAX_OVERTIME_PENALTY_PCT": 0.40,  # capped at 40% of quoted cost
}

# Permit review cycle cap (PRD §3.5)
MAX_REVIEW_CYCLES = 3

# Startup demo minimum (PRD §3.7)
MIN_DEMO_MINUTES = 15

# Retainage default (PRD §3.1)
DEFAULT_RETAINAGE_PCT = 0.10

TEST_DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 100_000_000,
}
