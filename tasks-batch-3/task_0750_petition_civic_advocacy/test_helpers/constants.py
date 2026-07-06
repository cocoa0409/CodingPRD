"""Domain thresholds — numeric constants from PRD §3 calculations."""

# Promotion price (PRD §3.7)
BASE_RATE_CENTS = {"STANDARD": 5000, "PREMIUM": 12000, "SPOTLIGHT": 25000}
CATEGORY_DEMAND = {
    "ENVIRONMENT": 1.5,
    "POLITICS": 2.0,
    "HEALTH": 1.2,
    "EDUCATION": 1.0,
    "OTHER": 1.0,
}
MIN_PRICE_CENTS = 5000
MAX_PRICE_CENTS = 200000
LISTING_FEE_CENTS = 1500

# Donation fee split (PRD §3.6)
PLATFORM_FEE_PCT = 0.029
FIXED_FEE_CENTS = 30

# Milestone ladder (PRD §3.3)
DEFAULT_FIRST_MILESTONE = 100

# Promotion slot capacity per category (PRD §3.7)
PROMO_SLOTS_PER_CATEGORY = 2

# Delivery-meeting buffer, minutes (PRD §3.5)
BUFFER_MINUTES = 15

# Default logical clock before any set call (PRD §2.9)
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

TEST_DEFAULTS = {
    "CAMPAIGN_GOAL_CENTS": 100000,
    "PETITION_GOAL": 10,
    "JURISDICTION": "US-CA-12",
}
