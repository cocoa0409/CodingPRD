"""Domain thresholds and canonical test values taken from the PRD narrative."""

# The logical UTC clock starts here on every server boot (PRD 2.4).
CLOCK_START = "2026-08-01T00:00:00Z"

# Sling load-angle factor table - exactly four entries (PRD 3.4).
LOAD_ANGLE_FACTORS = {
    90: 1.000,
    60: 1.155,
    45: 1.414,
    30: 2.000,
}

# Lift-class utilization ladder (PRD 3.4).
UTILIZATION_ENGINEERED_CRITICAL_PCT = 90.00
UTILIZATION_CRITICAL_PCT = 75.00
UTILIZATION_CEILING_PCT = 100.00

# Proximity override threshold, in feet (PRD 3.4).
PROXIMITY_CRITICAL_FT = 20

# Escort threshold, in US tons (PRD 3.4).
ESCORT_CLASS_TONS = 200

# Ground bearing (PRD 3.5).
FINAL_ENGINEERED_SHARE = 0.60
FINAL_ENGINEERED_DYNAMIC_FACTOR = 1.10
MAT_PANEL_SQFT = 32
MAT_PANELS_PER_PLAN_MULTIPLIER = 4

# Wind derate tiers keyed on the rounded sail-area ratio (PRD 3.5).
WIND_DERATE_TIERS = [
    (1.00, 1.00),
    (2.00, 0.85),
    (3.00, 0.70),
    (None, 0.55),
]

# Gear derate (PRD 3.2).
DERATE_PER_REPAIR = 0.05
DERATE_FLOOR = 0.70
DEFAULT_INSPECTION_INTERVAL_DAYS = 30

# Scheduling (PRD 3.4).
CRANE_RELEASE_BUFFER_HOURS = 12
OPERATOR_DAILY_HOUR_CAP = 12.0

# Engineering review (PRD 3.6).
MAX_REVISION_ROUND = 3

# Permit base lead days and base fees, plus the escort adders (PRD 3.7).
PERMIT_BASE_LEAD_DAYS = {
    "ROAD_CLOSURE": 10,
    "OVERSIZE_ESCORT": 7,
    "CRANE_PLACEMENT": 3,
}
PERMIT_ESCORT_EXTRA_LEAD_DAYS = 5
PERMIT_BASE_FEE_CENTS = {
    "ROAD_CLOSURE": 85_000,
    "OVERSIZE_ESCORT": 45_000,
    "CRANE_PLACEMENT": 25_000,
}
PERMIT_ESCORT_EXTRA_FEE_CENTS = 60_000
PERMIT_CANCELLATION_FEE_RATE = 0.40

# Billing (PRD 3.9).
MINIMUM_BILLABLE_HOURS = 4.0
REGULAR_HOURS_CAP = 8.0
OVERTIME_MULTIPLIER = 1.5
STANDBY_RATE_MULTIPLIER = 0.75
TRAVEL_CENTS_PER_MILE = 285
LUMP_SUM_FREE_STANDBY_HOURS = 2.0
DISCOUNT_TIERS = [
    (6_000_000, 0.08),
    (2_500_000, 0.05),
    (1_000_000, 0.02),
]
FUEL_SURCHARGE_RATE = 0.07

# Rigger-level ladder ranks demanded by each lift class at release (PRD 3.8).
RIGGER_LEVEL_RANK = {
    "NONE": 0,
    "BASIC": 1,
    "INTERMEDIATE": 2,
    "ADVANCED": 3,
    "MASTER": 4,
}
RIGGER_LEVEL_REQUIRED_BY_CLASS = {
    "STANDARD": "BASIC",
    "CRITICAL": "ADVANCED",
    "ENGINEERED_CRITICAL": "MASTER",
}

# Pagination (PRD 2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# ---------------------------------------------------------------------------
# Canonical test values shared by fixtures.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    # The 150 ton "standard lift" machine.
    "STD_CRANE_MODEL": "RT-150",
    "STD_CLASS_TONS": 150,
    "STD_GROSS_WEIGHT_LB": 90_000,
    "STD_COUNTERWEIGHT_LB": 40_000,
    "STD_PAD_AREA_SQFT": 30.0,
    "STD_MAX_LINE_PULL_LB": 20_000,
    "STD_RATED_MAX_WIND_MPH": 30,
    "STD_ANNUAL_INSPECTION_EXPIRES_ON": "2027-06-30T00:00:00Z",
    "STD_MOB_DEMOB_CENTS": 250_000,
    "STD_HOURLY_RATE_CENTS": 45_375,
    "STD_SOIL_PSF": 3500,
    "STD_JURISDICTION": "NJ-HUDSON",
    "STD_LOAD_WEIGHT_LB": 60_000,
    "STD_BOOM_LENGTH_FT": 100,
    "STD_RADIUS_FT": 35,
    "STD_CHART_CAPACITY_LB": 100_000,
    # The 275 ton "critical lift" machine.
    "CRIT_CRANE_MODEL": "LTM-1250",
    "CRIT_CLASS_TONS": 275,
    "CRIT_GROSS_WEIGHT_LB": 190_000,
    "CRIT_COUNTERWEIGHT_LB": 100_000,
    "CRIT_PAD_AREA_SQFT": 40.0,
    "CRIT_SOIL_PSF": 2000,
    "CRIT_JURISDICTION": "NJ-BERGEN",
    "CRIT_LOAD_WEIGHT_LB": 73_000,
    "CRIT_BOOM_LENGTH_FT": 120,
    "CRIT_RADIUS_FT": 40,
    # Shared plan/window values.
    "WINDOW_START": "2026-09-10T06:00:00Z",
    "WINDOW_END": "2026-09-10T16:00:00Z",
    "SAIL_AREA_SQFT": 150.0,
    "BLOCK_WEIGHT_LB": 2_000,
    "PARTS_OF_LINE": 8,
    "SLING_WEIGHT_LB": 500,
}
