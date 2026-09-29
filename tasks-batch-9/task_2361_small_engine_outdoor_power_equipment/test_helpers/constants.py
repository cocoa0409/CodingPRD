"""Domain thresholds and pinned literals drawn from the PRD's calculations."""

# -- Emission certification (PRD §3.2) --------------------------------------

MIN_COMPLIANCE_MARGIN_PCT = 5.00

# -- Supplier quality ladder (PRD §3.4) -------------------------------------

PPM_PROBATION_THRESHOLD = 25_000
PPM_SUSPEND_THRESHOLD = 100_000
REDUCED_STREAK = 3
SKIP_LOT_STREAK = 5

SAMPLE_FRACTION_REDUCED = 0.02
SAMPLE_MINIMUM_REDUCED = 5
SAMPLE_FRACTION_NORMAL = 0.05
SAMPLE_MINIMUM_NORMAL = 8
SAMPLE_FRACTION_TIGHTENED = 0.10
SAMPLE_MINIMUM_TIGHTENED = 13
MAJOR_ACCEPTANCE_FRACTION = 0.10

# -- Machining capability (PRD §3.5) ----------------------------------------

MIN_CAPABILITY_SAMPLE = 5
CPK_GATE_CRITICAL = 1.33
CPK_GATE_MAJOR = 1.00
CPK_ZERO_SIGMA_CAP = 9.9999

# -- Assembly (PRD §3.7) ----------------------------------------------------

MAX_REWORK_CYCLES = 2
STANDARD_EMISSION_MULTIPLIER = 1.10
DEVIATION_EMISSION_MULTIPLIER = 1.00

# -- Seasonal planning (PRD §3.6) -------------------------------------------

CARRY_TIER_1_CEILING = 5_000_000
CARRY_TIER_2_CEILING = 20_000_000
CARRY_RATE_SMALL = 0.0040
CARRY_RATE_MEDIUM = 0.0030
CARRY_RATE_LARGE = 0.0020

SEASON_START = {
    "WALK_MOWER": "2027-03-01",
    "RIDING_MOWER": "2027-03-15",
    "SNOW_THROWER": "2026-11-02",
    "GENERATOR": "2027-05-03",
}

# -- Production line audits (PRD §3.8) --------------------------------------

MIN_AUDIT_SAMPLE = 2
AUDIT_SAMPLE_FRACTION = 0.02
MAX_AUDIT_FAILURE_RATE = 0.25
AUDIT_FAILURE_SUSPEND_COUNT = 2

# -- Safety bench tests (PRD §3.3) ------------------------------------------

MAX_BLADE_STOP_MS = 3000
MAX_OPC_STOP_MS = 1000

# -- Service parts (PRD §3.9) -----------------------------------------------

BACKORDER_PROMISE_DAYS = 21
MAX_SUPERSESSION_DEPTH = 5
MIN_COMMITTED_AVAILABILITY_YEARS = 7
DEFAULT_DEALER_LEAD_TIME_DAYS = 2
DEFAULT_MASS_RETAIL_LEAD_TIME_DAYS = 5

# -- Pagination (PRD §2.3) --------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# -- Logical clock (PRD §2.4) ----------------------------------------------

INITIAL_CLOCK_UTC = "2026-08-01T00:00:00Z"

# -- Canonical plant scenario literals -------------------------------------
#
# One coherent set of inputs reused across the suite: an EPA_PHASE3 family
# limited to 8.00 g/kWh with a declared baseline of 4.00 g/kWh over a 500-hour
# durability period, a 208 cc platform torqued to 22.0 Nm +/- 5% over four
# fasteners inside a 3200..3600 rpm hot-test window, and a walk-behind mower
# model costing 21000 cents a unit with a 0.55 dealer share.

CANONICAL_CLOCK_UTC = "2026-08-03T08:00:00Z"

FAMILY_EMISSION_LIMIT = 8.00
FAMILY_DECLARED_BASELINE = 4.00
FAMILY_DURABILITY_HOURS = 500

DURABILITY_INITIAL_EMISSION = 5.00
DURABILITY_FINAL_EMISSION = 6.40
# MULTIPLICATIVE: 6.40 / 5.00 = 1.2800 at full accumulation
EXPECTED_MULTIPLICATIVE_DF = 1.2800
EXPECTED_MULTIPLICATIVE_CERTIFIED = 5.12
EXPECTED_MULTIPLICATIVE_MARGIN = 36.00
# ADDITIVE: 6.40 - 5.00 = 1.4000 at full accumulation
EXPECTED_ADDITIVE_DF = 1.4000
EXPECTED_ADDITIVE_CERTIFIED = 5.40
EXPECTED_ADDITIVE_MARGIN = 32.50

PLATFORM_TORQUE_SPEC_NM = 22.0
PLATFORM_TORQUE_TOLERANCE_PCT = 0.05
PLATFORM_REQUIRED_FASTENER_COUNT = 4
EXPECTED_TORQUE_LOWER_BOUND = 20.90
EXPECTED_TORQUE_UPPER_BOUND = 23.10

HOT_TEST_MIN_RPM = 3200
HOT_TEST_MAX_RPM = 3600
HOT_TEST_NOMINAL_RPM = 3400
HOT_TEST_PASSING_EMISSION = 5.60
# certified 5.12 * 1.10 = 5.632 -> 5.63
EXPECTED_STANDARD_HOT_TEST_THRESHOLD = 5.63
EXPECTED_DEVIATION_HOT_TEST_THRESHOLD = 5.12

MODEL_STANDARD_COST_CENTS = 21_000
MODEL_MSRP_CENTS = 59_900
MODEL_DEALER_SHARE_PCT = 0.55

LOT_QUANTITY = 800
# NORMAL level on 800 pieces: max(8, ceil(800 * 0.05)) = 40
EXPECTED_NORMAL_SAMPLE_SIZE_800 = 40
# MAJOR supplier: floor(40 * 0.10) = 4
EXPECTED_MAJOR_ACCEPTANCE_NUMBER_40 = 4

MACHINING_LSL_MM = 64.98000
MACHINING_USL_MM = 65.02000
CAPABLE_MEASUREMENTS = [65.00000, 65.00200, 64.99800, 65.00400, 64.99600]

IN_BAND_TORQUE_READINGS = [
    {"station": 1, "torque_nm": 22.0},
    {"station": 2, "torque_nm": 22.1},
    {"station": 3, "torque_nm": 21.9},
    {"station": 4, "torque_nm": 22.2},
]
