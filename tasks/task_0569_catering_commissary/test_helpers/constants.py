"""Domain thresholds — numeric constants from PRD calculations and defaults."""

# Labor overtime threshold (PRD Section 3.6): regular time up to 8.0h, overtime
# (1.5x) applies only to hours strictly greater than 8.0.
OT_THRESHOLD_HOURS = 8.0
OT_MULTIPLIER = 1.5

# Pagination (PRD Section 2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Canonical event-window datetimes used across fixtures (ISO 8601 UTC).
DATE = "2026-06-01"


def dt(hh, mm=0):
    """Build an ISO 8601 UTC timestamp on the canonical event date."""
    return f"{DATE}T{hh:02d}:{mm:02d}:00Z"


# Default sample values reused across factories/fixtures.
DEFAULTS = {
    "INGREDIENT_UNIT_COST": 10,
    "INGREDIENT_ON_HAND": 100000,
    "MENU_SELL_PRICE": 1000,
    "RECIPE_QTY_PER_PORTION": 5,       # 5 * 10 = 50 -> portion_food_cost 50
    "STATION_CAPACITY": 2,
    "EQUIPMENT_TOTAL_UNITS": 10,
    "EQUIPMENT_RENTAL_PRICE": 500,
    "STAFF_HOURLY_RATE": 2000,
    "VENUE": "1 Palazzo",
}
