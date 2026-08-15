"""Domain thresholds and numeric constants stated in the PRD.

Only values the PRD states verbatim belong here. Window lengths and the
director-approval threshold are described in the PRD only as configured
values, so no numeric literal for them is assumed anywhere in this suite.
"""

# Logical clock startup instant (PRD section 2.10).
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Severity scoring (PRD section 3.3).
SEVERITY_BASE_SCORES = {
    "UTILITY_CROSSING": 4,
    "STRUCTURE": 3,
    "FENCE": 2,
    "PAVEMENT": 2,
    "VEGETATION": 1,
    "OTHER": 1,
}
AREA_RATIO_TIER_2 = 0.25  # multiplier 2.0 at or above
AREA_RATIO_TIER_1 = 0.10  # multiplier 1.5 at or above, below 0.25
SEVERITY_TIER_THRESHOLDS = {"CRITICAL": 6.0, "SEVERE": 3.5, "MODERATE": 1.8}
SEVERITY_TIER_WEIGHTS = {"MINOR": 1, "MODERATE": 3, "SEVERE": 7, "CRITICAL": 15}
PRESSURE_AGE_CAP_DAYS = 90
PRESSURE_AGE_STEP_PER_DAY = 0.01

# Permit fee schedule (PRD section 3.4).
PERMIT_BASE_RATES_CENTS = {
    "DRIVEWAY": 25000,
    "LANDSCAPING": 10000,
    "FENCE_RETENTION": 15000,
    "STRUCTURE_RETENTION": 50000,
    "UTILITY_CROSSING": 75000,
}
FEE_AREA_BRACKET_1_LIMIT = 500
FEE_AREA_BRACKET_1_RATE = 12
FEE_AREA_BRACKET_2_LIMIT = 2000
FEE_AREA_BRACKET_2_RATE = 8
FEE_AREA_BRACKET_3_RATE = 5
STRUCTURE_RETENTION_BUFFER_DAYS = 30

# Wire-zone strictness (PRD section 3.6): wire-zone limit is half the zone max.
WIRE_ZONE_HEIGHT_FACTOR = 0.5

# Common monetary test defaults.
DEFAULT_CASE = {
    "easement_width_ft": 50,
    "easement_area_sqft": 10000,
    "fair_market_value_per_sqft": 10,
    "acquisition_budget_cents": 50000000,
}
