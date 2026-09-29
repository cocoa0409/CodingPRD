"""Domain thresholds and canonical test inputs from the PRD calculations."""

# The logical clock reads exactly this instant before any client sets it.
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# An id that is a syntactically valid UUID but is never minted by the server.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

THRESHOLDS = {
    # Liner CQA conformance
    "DESTRUCTIVE_SAMPLE_INTERVAL_FT": 500.0,
    "DEFECT_FREE_ALLOWANCE_PER_PANEL": 0.05,
    "DEFECT_PENALTY_SLOPE": 4.0,
    "DEFECT_PENALTY_CAP": 30.0,
    "QA_SCORE_APPROVAL_MINIMUM": 85.0,
    "MAX_REVISION_ROUNDS": 3,
    # Airspace / density
    "DENSITY_FLOOR_TONS_PER_CY": 0.55,
    "DENSITY_TARGET_TONS_PER_CY": 0.85,
    "FULL_CELL_FRACTION": 0.98,
    "RESTRICTED_LIFE_YEARS": 2.0,
    # Leachate invoicing
    "SURCHARGE_TIER1_FLOOR": 500.00,
    "SURCHARGE_TIER2_FLOOR": 1200.00,
    "SURCHARGE_PCT_NONE": 0.00,
    "SURCHARGE_PCT_TIER1": 0.06,
    "SURCHARGE_PCT_TIER2": 0.10,
    "GALLONS_PER_KGAL": 1000.0,
    # Wellfield specification
    "OXYGEN_CRITICAL_PCT": 12.0,
    "METHANE_SPEC_MIN_PCT": 45.0,
    "OXYGEN_SPEC_MAX_PCT": 5.0,
    "VACUUM_SPEC_MIN_IN_H2O": 10.0,
    "SCAN_EXCEEDANCE_PPM": 500.0,
    # Aerial surveys
    "SURVEY_MIN_SPACING_DAYS": 90,
}

# Daily cover factors: how much of the day's airspace the cover itself consumes.
COVER_FACTORS = {
    "SOIL_6IN": 0.92,
    "ALTERNATIVE_TARP": 1.00,
    "ADC_FOAM": 0.97,
    "AUTO_SHRED_FINES": 0.88,
}

# Working-face penalty factors keyed on working_face_area_sf.
FACE_PENALTY = {
    "OVER_15000_SF": 0.90,
    "OVER_8000_SF": 0.96,
    "AT_OR_UNDER_8000_SF": 1.00,
}
FACE_PENALTY_LARGE_SF = 15000.0
FACE_PENALTY_MEDIUM_SF = 8000.0

# Defaults the server applies when the optional input is omitted.
DECLARED_DEFAULTS = {
    "daily_load_limit": 200,
    "piggyback_over_cell_id": None,
    "concurrent_slot_capacity": 2,
    "post_closure_years": 30,
}

# Pagination contract.
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

TEST_DEFAULTS = {
    "LANDFILL_NAME": "Ridgeview MSW",
    "PERMIT_NUMBER": "MSW-4417",
    "PERMITTED_TOTAL_AIRSPACE_CY": 5000000,
    "DESIGN_FOOTPRINT_SF": 400000,
    "PLANNED_DENSITY_TONS_PER_CY": 0.9,
    "ANNUAL_TONNAGE_FORECAST": 300000,
    "CELL_CODE": "C-1",
    "DESIGN_AIRSPACE_CY": 1000000,
    "DESIGN_AREA_SF": 120001,
    "COMMUNITY_NAME": "Ridgeview Township",
    "POSTED_TIPPING_FEE_PER_TON": 42.5,
    "HOST_FEE_PER_TON": 3.75,
    "TIER1_MONTHLY_TONS": 100,
    "ROYALTY_TIER1_PCT": 0.04,
    "ROYALTY_TIER2_PCT": 0.07,
    "MINIMUM_ANNUAL_PAYMENT": 250000,
    "CLOSURE_UNIT_COST_PER_SF": 1.855,
    "POST_CLOSURE_ANNUAL_COST": 95000.0,
    "INFLATION_PCT": 0.03,
    "ESTIMATE_YEAR": 2026,
    "OPERATING_DATE": "2026-08-01T00:00:00Z",
    "WORKING_FACE_AREA_SF": 5000,
    "FACILITY_NAME": "Cedar Valley POTW",
    "DAILY_GALLON_CAP": 20000,
    "BASE_HAUL_FEE": 350.0,
    "TREATMENT_RATE_PER_KGAL": 62.5,
}
