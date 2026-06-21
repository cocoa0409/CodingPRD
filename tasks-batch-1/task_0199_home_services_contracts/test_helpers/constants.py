"""Domain thresholds — numeric constants from PRD calculations and common test values.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# The deep-recovery threshold: an equipment unit whose current_charge_grams drops
# below ten percent of nameplate at visit completion is flagged NEEDS_SERVICE,
# and clearing the service flag requires charge >= ten percent of nameplate (PRD §3.8/§3.9).
LOW_CHARGE_RATIO = 0.10

# A UTC instant well before any test window; the standard "now" the fixtures pin the clock to.
BASE_CLOCK = "2026-07-01T00:00:00Z"

# Standard plan economics reused across the suite (a PLUS HVAC plan).
TEST_DEFAULTS = {
    "PLAN_TIER": "PLUS",
    "PLAN_TRADE": "HVAC",
    "ANNUAL_FEE_CENTS": 24000,
    "INCLUDED_VISITS_PER_YEAR": 2,
    "EXTRA_VISIT_FEE_CENTS": 8500,
    "SLA_RESPONSE_HOURS": 4,
    "PARTS_DISCOUNT_PCT": 0.10,
    "NAMEPLATE_CHARGE_GRAMS": 4000,
    "REGION_CODE": "NORTH",
    "DAILY_VISIT_CAPACITY": 5,
}
