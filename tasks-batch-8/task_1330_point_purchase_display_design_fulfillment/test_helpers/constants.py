"""Domain thresholds and shared values from the PRD's calculation rules (§3.3, §3.4)."""

# Tiered unit-cost rate table (PRD §3.3): fewer than 100 units bill at 2500
# cents per unit, quantities from 100 up to 499 bill at 2200, and 500 or more
# units bill at 1950. Average-rate-on-whole-quantity, never marginal.
TIER1_MAX_QUANTITY = 100          # production_quantity < 100 -> tier 1
TIER2_MAX_QUANTITY = 500          # production_quantity < 500 -> tier 2
TIER1_UNIT_COST_CENTS = 2500
TIER2_UNIT_COST_CENTS = 2200
TIER3_UNIT_COST_CENTS = 1950

# Delivery grace after ship_window_end (PRD §3.4).
DELIVERY_GRACE_DAYS = 7

# Logical clock startup default (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Canonical ship window used by the shipping/logistics fixtures.
SHIP_WINDOW_START = "2026-08-10T00:00:00Z"
SHIP_WINDOW_END = "2026-08-20T00:00:00Z"
APPOINTMENT_INSIDE_WINDOW = "2026-08-15T10:00:00Z"
TIME_INSIDE_WINDOW = "2026-08-15T08:00:00Z"
TIME_BEFORE_WINDOW = "2026-08-09T00:00:00Z"
APPOINTMENT_BEFORE_WINDOW = "2026-08-09T10:00:00Z"
APPOINTMENT_AFTER_WINDOW = "2026-08-25T00:00:00Z"
APPOINTMENT_ONE_SECOND_AFTER_WINDOW_END = "2026-08-20T00:00:01Z"
# ship_window_end + 7 days exactly, and one second past that grace deadline.
TIME_GRACE_END_EXACT = "2026-08-27T00:00:00Z"
TIME_ONE_SECOND_AFTER_GRACE = "2026-08-27T00:00:01Z"

TEST_DEFAULTS = {
    "CLIENT_NAME": "Acme Corp",
    "CLIENT_EMAIL": "ops@acme.example",
    "RETAILER_NAME": "BigBox",
    "PROGRAM_NAME": "Summer",
    "STORE_COUNT": 200,
    "PROGRAM_REVENUE_CENTS": 12000000,
    "RULE_DIMENSION": "MAX_WIDTH_IN",
    "RULE_LIMIT_VALUE": "48",
    "DESIGN_CODE": "D1",
    "WIDTH_IN": 40,
    "HEIGHT_IN": 60,
    "DEPTH_IN": 24,
    "WEIGHT_LB": 30,
    "MATERIAL": "CORRUGATE",
    "REPORTED_BY": "Store Manager",
}
