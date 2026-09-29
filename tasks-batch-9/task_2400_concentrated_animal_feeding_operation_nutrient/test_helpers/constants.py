"""Domain thresholds and coefficients used by the PRD's calculations."""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.5)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Operation sizing (PRD §3.1)
# ---------------------------------------------------------------------------
LARGE_AU_THRESHOLD = 1000
MEDIUM_AU_THRESHOLD = 300

ANIMAL_UNIT_FACTORS = {
    "DAIRY_COW": 1.4,
    "BEEF_FEEDER": 1.0,
    "SWINE_FINISHING": 0.4,
    "LAYER_HEN_LIQUID": 0.033,
    "LAYER_HEN_DRY": 0.0125,
}

ANNUAL_GALLONS_PER_HEAD = {
    "DAIRY_COW": 9000,
    "BEEF_FEEDER": 3600,
    "SWINE_FINISHING": 1400,
    "LAYER_HEN": 30,
}

DILUTION_FACTOR = {"LIQUID": 1.15, "DRY": 1.0}
NET_PRECIPITATION_FT = 0.9
GALLONS_PER_CUBIC_FOOT = 7.4805
DAYS_PER_YEAR = 365

# ---------------------------------------------------------------------------
# Field setbacks (PRD §3.3)
# ---------------------------------------------------------------------------
SETBACK_TILE_INLET_FT = 300
SETBACK_NEAR_WATER_FT = 200
SETBACK_BASE_FT = 100
SLOPE_ADDER_FT = 100
SLOPE_ADDER_THRESHOLD_PCT = 6
SQFT_PER_ACRE = 43560

# ---------------------------------------------------------------------------
# Soil test phosphorus index (PRD §3.3)
# ---------------------------------------------------------------------------
P_INDEX_MEDIUM = 20
P_INDEX_HIGH = 50
P_INDEX_VERY_HIGH = 100
SOIL_TEST_VALIDITY_YEARS = 4

# ---------------------------------------------------------------------------
# Allowable rate (PRD §3.4)
# ---------------------------------------------------------------------------
CROP_N_PER_UNIT = {"CORN_GRAIN": 1.1, "SOYBEAN": 0, "ALFALFA": 0, "GRASS_HAY": 45}
CROP_P_PER_UNIT = {"CORN_GRAIN": 0.37, "SOYBEAN": 0.8, "ALFALFA": 12, "GRASS_HAY": 13}
LEGUME_CREDIT_LBS = {
    "SOYBEAN": 40,
    "ALFALFA": 100,
    "CORN_GRAIN": 0,
    "GRASS_HAY": 0,
    "NONE": 0,
}
P_INDEX_MULTIPLIER = {"LOW": 4.0, "MEDIUM": 2.0, "HIGH": 1.0, "VERY_HIGH": 0.0}

MANURE_N_LBS_PER_1000GAL = {"DAIRY": 24, "BEEF": 32, "SWINE": 40, "LAYER": 60}
MANURE_P2O5_LBS_PER_1000GAL = {"DAIRY": 10, "BEEF": 16, "SWINE": 28, "LAYER": 45}
N_AVAILABILITY_FACTOR = {
    "INJECTION": 0.65,
    "INCORPORATED_24H": 0.55,
    "SURFACE_BROADCAST": 0.40,
    "IRRIGATION": 0.35,
}
ANIMAL_GROUP = {
    "DAIRY_COW": "DAIRY",
    "BEEF_FEEDER": "BEEF",
    "SWINE_FINISHING": "SWINE",
    "LAYER_HEN": "LAYER",
}
RATE_FLOOR_STEP_GALLONS = 100

# ---------------------------------------------------------------------------
# Storage (PRD §3.5)
# ---------------------------------------------------------------------------
DEFAULT_REQUIRED_FREEBOARD_IN = 24
OVERFLOW_FREEBOARD_IN = 6
WINTER_SEASONAL_FACTOR = 1.35
WINTER_SEASONAL_MONTHS = (11, 12, 1, 2, 3)
SEASONAL_STRUCTURE_TYPES = ("EARTHEN_LAGOON", "STACKING_PAD")
MIN_STORAGE_DAYS = 180

# ---------------------------------------------------------------------------
# Permit coverage and renewal fee (PRD §3.2)
# ---------------------------------------------------------------------------
COVERAGE_TERM_YEARS = 5
RENEWAL_WINDOW_DAYS = 180
RENEWAL_DUE_DAYS = 90
BASE_FEE = {"SMALL": 150, "MEDIUM": 400, "LARGE": 900}
PER_AU_FEE = 0.45
CONSERVATION_TIER_1_FLOOR = 500
CONSERVATION_TIER_2_FLOOR = 1500
CONSERVATION_TIER_1_PCT = 0.05
CONSERVATION_TIER_2_PCT = 0.10
LATE_SURCHARGE_PCT = 0.25

# ---------------------------------------------------------------------------
# Land application safeguards (PRD §3.6)
# ---------------------------------------------------------------------------
PRECIPITATION_LIMIT_IN = 0.50
REAPPLICATION_INTERVAL_DAYS = 21
METHOD_SETBACK_MULTIPLIER = {
    "SURFACE_BROADCAST": 1.0,
    "IRRIGATION": 1.5,
    "INCORPORATED_24H": 0.5,
    "INJECTION": 0.25,
}
WINTER_APPLICATION_MONTHS = (12, 1, 2)

# ---------------------------------------------------------------------------
# Incidents and inspections (PRD §3.8)
# ---------------------------------------------------------------------------
MORTALITY_MIN_HEAD = 2
MORTALITY_PCT_OF_HERD = 0.01
RELEASE_NOTIFICATION_GALLONS = 1000
ORAL_NOTIFICATION_HOURS = 24
WRITTEN_REPORT_DAYS = 5
INSPECTION_RESPONSE_DAYS = 30

# ---------------------------------------------------------------------------
# Annual reporting (PRD §3.9)
# ---------------------------------------------------------------------------
VARIANCE_TOLERANCE_PCT = 15.00

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Canonical scenario literals — the "Willow Creek Dairy" reference operation
# whose derived values recur throughout the suite.
# ---------------------------------------------------------------------------
WILLOW_CREEK = {
    # inputs
    "name": "Willow Creek Dairy",
    "county": "Linn",
    "animal_type": "DAIRY_COW",
    "head_count": 300,
    "manure_handling": "LIQUID",
    "open_lot_area_sqft": 40000,
    "discharge_potential": "CONTINUOUS",
    "has_conservation_plan": True,
    # derived
    "animal_units": 420.00,
    "size_class": "MEDIUM",
    "permit_required": True,
    "design_annual_manure_gallons": 3374298.00,
    "daily_production_gallons": 9244.65,
}

LAGOON_1 = {
    # inputs
    "structure_name": "Lagoon 1",
    "structure_type": "EARTHEN_LAGOON",
    "surface_area_sqft": 60000,
    "total_depth_in": 144,
    "required_freeboard_in": 24,
    # derived
    "design_capacity_gallons": 5385960.00,
    "freeboard_reserve_gallons": 897660.00,
    "operating_capacity_gallons": 4488300.00,
}

NORTH_40 = {
    # inputs
    "field_name": "North 40",
    "total_acres": 42.5,
    "distance_to_water_ft": 150,
    "has_tile_inlet": False,
    "slope_pct": 4.0,
    "water_frontage_ft": 900,
    # derived
    "required_setback_ft": 200,
    "excluded_acres": 4.13,
    "net_applicable_acres": 38.37,
}
