"""Domain thresholds — numeric constants from PRD calculations (§2.6, §3.2, §3.5, §3.7)."""

# Travel fee (PRD §3.2)
TRAVEL_FREE_RADIUS_MILES = 25
TRAVEL_RATE_PER_MILE = 1.50

# Overtime cap shared by quote and final settlement (PRD §3.2, §3.5)
OVERTIME_DAILY_CAP = 750.00

# Cancellation refund day tiers (PRD §3.7)
TIER_FULL_DAYS = 60
TIER_HALF_DAYS = 30

# Pagination defaults (PRD §2.3)
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# Common package shape used across fixtures (chosen so quote math is PRD-derivable).
# base_price 1200.00, included_hours 4, included_prints 300, rates per PRD examples.
TEST_DEFAULTS = {
    "BASE_PRICE": 1200.00,
    "INCLUDED_HOURS": 4,
    "INCLUDED_PRINTS": 300,
    "OVERTIME_RATE_PER_HOUR": 150.00,
    "IDLE_RATE_PER_HOUR": 75.00,
    "OVERAGE_PRINT_RATE": 0.40,
}
