"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock default (PRD section on the logical clock)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Semolina grading (grade score blend and bands)
PROTEIN_FLOOR = 10.0
PROTEIN_SPAN = 4.0
FALLING_FLOOR_S = 200.0
FALLING_SPAN_S = 200.0
MOISTURE_CEIL = 16.0
MOISTURE_SPAN = 6.0
GRADE_A_MIN = 70.0
GRADE_B_MIN = 50.0

# Lot acceptance safety cap
MOISTURE_SAFETY_CAP = 15.0

# Settlement pricing volume tiers
TIER2_MIN_KG = 20000
TIER3_MIN_KG = 50000
TIER2_DISCOUNT = 0.02
TIER3_DISCOUNT = 0.05
SPOT_BLEND_WINDOW_DAYS = 30

# Changeover composition
CHANGEOVER_BASE_NONE = 45
CHANGEOVER_BASE_SAME_FAMILY = 30
CHANGEOVER_BASE_LONG_SHORT = 60
CHANGEOVER_BASE_INTO_SPECIALTY = 90
CHANGEOVER_BASE_OUT_OF_SPECIALTY = 75
WEAR_TIER2 = 0.50
WEAR_TIER3 = 0.80
WEAR_ADDER_T2 = 15
WEAR_ADDER_T3 = 40
ALLERGEN_ADDER = 20

# Drying curves (total hours) and remedial hours per redry
DRYING_TOTAL_HOURS = {"STANDARD": 18, "HIGH_TEMP": 9, "LOW_TEMP": 36}
REMEDIAL_HOURS = 4
CRACK_RISK_MOISTURE = 32.0

# Case planning
PARTIAL_CASE_MIN_UNITS = 6

# Standard certificate / lab measurement sets used across fixtures
CERT_DEFAULTS = {
    "cert_protein_pct": 13.0,
    "cert_moisture_pct": 14.5,
    "cert_gluten_index": 80,
    "cert_falling_number_s": 300,
}
LAB_DEFAULTS = {
    "lab_protein_pct": 13.8,
    "lab_moisture_pct": 13.0,
    "lab_gluten_index": 88,
    "lab_falling_number_s": 340,
}

# Standard run window used by most fixtures (clock default is 2026-08-01).
RUN_START_ISO = "2026-08-10T00:00:00Z"
RUN_END_ISO = "2026-08-11T00:00:00Z"
# Clock instants that satisfy the STANDARD curve's 18h requirement and beyond.
STANDARD_FINISH_CLOCK = "2026-08-10T18:00:00Z"
NEXT_DAY_CLOCK = "2026-08-11T00:00:00Z"
