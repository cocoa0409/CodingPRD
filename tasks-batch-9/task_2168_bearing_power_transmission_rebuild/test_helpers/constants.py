"""Domain thresholds and shared literals taken from the PRD narrative."""

# Money and rounding
LABOR_RATE_CENTS_PER_HOUR = 14500          # $145.00 per bench hour
EMERGENCY_CALLOUT_CENTS = 25000            # flat $250.00 emergency callout
EXPEDITE_TIER_LOW_FLOOR_CENTS = 100000     # $1,000.00
EXPEDITE_TIER_HIGH_FLOOR_CENTS = 500000    # $5,000.00
EXPEDITE_PCT_BELOW_LOW = 0.30
EXPEDITE_PCT_MID = 0.22
EXPEDITE_PCT_HIGH = 0.15
CORE_CREDIT_CAP_PCT = 0.40
MANUAL_CREDIT_CEILING_CENTS = 2000000
REBUILD_DECAY_PCT = 0.08

GRADE_MULTIPLIERS = {
    "GRADE_A": 1.00,
    "GRADE_B": 0.75,
    "GRADE_C": 0.45,
    "GRADE_D": 0.20,
    "SCRAP": 0.00,
}

# Remaining-life banding floors (inclusive)
LIFE_GRADE_FLOORS = [(80, "GRADE_A"), (60, "GRADE_B"), (35, "GRADE_C"), (15, "GRADE_D")]

# ISO severity zone floors
ZONE_B_FLOOR = 1.40
ZONE_C_FLOOR = 2.80
ZONE_D_FLOOR = 4.50
ZONE_PENALTIES = {"A": 0, "B": 5, "C": 15, "D": 30}
REBUILD_PENALTY_PER_REBUILD = 6

# Failure-cause ladder
DEFECT_RATIO_FLOOR = 3.0

# Warranty
WARRANTY_MONTH_DAYS = 30
CHANGEOVER_BUFFER_HOURS = 24

# Pagination
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# The logical shop clock reads this at startup.
CLOCK_START = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# The recurring reman spec used across the suite.  BORE is the only required
# feature code; the four bands mirror the shop's published SKF-22324-CCK spec.
# --------------------------------------------------------------------------
BAND_BORE = {
    "feature_code": "BORE", "min_um": 40, "max_um": 90,
    "rework_extension_um": 15, "deduction_pct": 0.10, "weight": 0.40,
}
BAND_JOURNAL = {
    "feature_code": "JOURNAL", "min_um": 25, "max_um": 60,
    "rework_extension_um": 10, "deduction_pct": 0.07, "weight": 0.30,
}
BAND_HOUSING_FIT = {
    "feature_code": "HOUSING_FIT", "min_um": 10, "max_um": 45,
    "rework_extension_um": 10, "deduction_pct": 0.05, "weight": 0.20,
}
BAND_END_PLAY = {
    "feature_code": "END_PLAY", "min_um": 50, "max_um": 150,
    "rework_extension_um": 20, "deduction_pct": 0.03, "weight": 0.10,
}

FOUR_BANDS = [BAND_BORE, BAND_JOURNAL, BAND_HOUSING_FIT, BAND_END_PLAY]
ONE_BAND = [BAND_BORE]

TEST_DEFAULTS = {
    "BASE_CORE_VALUE_CENTS": 90000,
    "MAX_REBUILD_COUNT": 3,
    "WARRANTY_HOURS": 8000,
    "WARRANTY_MONTHS": 18,
    "MODEL_CODE": "SKF-22324-CCK",
    "LABOR_HOURS": 6.5,
    "OEM_PART_NO": "BRG-22324",
    "OEM_QTY": 2,
    "OEM_UNIT_COST_CENTS": 38500,
}

# Canonical derived figures for the recurring fixture
# (labour 6.5 h -> 94250, one approved OEM line 2 x 38500 -> 77000).
CANONICAL_LABOR_CENTS = 94250
CANONICAL_PARTS_SUBTOTAL_CENTS = 77000
CANONICAL_PRE_CREDIT_SUBTOTAL_CENTS = 171250
CANONICAL_COVERED_BASE_CENTS = 171250
