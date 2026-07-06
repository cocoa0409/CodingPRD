"""Domain thresholds — numeric constants from the PRD pricing and temporal rules."""

# Grocery markup tiers (PER_WEEK billing, PRD §3.9)
THRESHOLDS = {
    "TIER1_MAX_EXCL": 15000,   # grocery_cost_cents < 15000 -> 15%
    "TIER2_MAX_EXCL": 30000,   # 15000 <= grocery_cost_cents < 30000 -> 12%
    "TIER1_PCT": 15,
    "TIER2_PCT": 12,
    "TIER3_PCT": 10,           # grocery_cost_cents >= 30000 -> 10%
    "PER_HEAD_SURCHARGE_CENTS": 500,
    "SURCHARGE_FREE_HEADS": 2,
    "PER_MEAL_MARKUP_PCT": 20,
    "PERISHABLE_SHELF_DAYS": 3,
    "SHELF_STABLE_SHELF_DAYS": 5,
    "CHEF_BUFFER_MINUTES": 60,
    "STRIKE_LIMIT": 3,
}

# Default logical clock value at server startup (PRD §2.7)
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

TEST_DEFAULTS = {
    "WEEKLY_BASE_FEE_CENTS": 5000,
    "PER_MEAL_FEE_CENTS": 800,
    "WEEKLY_GROCERY_BUDGET_CENTS": 100000,
    "HOURLY_RATE_CENTS": 6000,
    "WEEK_START_DATE": "2026-03-09T00:00:00Z",
}
