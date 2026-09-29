"""Domain thresholds and physical constants stated in the PRD."""

# Logical clock (PRD §2.4)
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
CALIBRATION_VALIDITY_HOURS = 26

# Heat input / emissions computation (PRD §3.5)
FC_FACTOR = 1800.0                     # dscf CO2 per mmBtu
K_SO2_LB_PER_SCF_PPM = 0.000000166     # lb SO2 per scf per ppm
K_CO2_LB_PER_SCF = 0.1194              # lb CO2 per scf
CO2_LB_PER_MMBTU = 205.3               # Appendix D CO2 emission factor
SULFUR_TO_SO2_MASS_RATIO = 2.0
LBS_PER_TON = 2000.0

# Calibration verdict ladder (PRD §3.2)
DEFAULT_CALIBRATION_ERROR_SPEC_PCT = 2.5
OUT_OF_CONTROL_MULTIPLIER = 2.0
CONSECUTIVE_FAILURE_LIMIT = 2

# Relative accuracy statistics (PRD §3.3)
MIN_RATA_RUNS = 9
MAX_RATA_RUNS = 12
T_VALUE = {9: 1.860, 10: 1.833, 11: 1.812, 12: 1.796}
RA_PASS_THRESHOLD_PCT = 10.0
LOW_EMITTER_REFERENCE_MEAN = {
    "SO2": 0.300,
    "NOX_RATE": 0.300,
    "FLOW": 0.300,
    "CO2": 5.000,
}

# Missing data substitution and availability (PRD §3.6)
LOOKBACK_HOURS = 20
TIER_1_AVAILABILITY_PCT = 95.0
TIER_2_AVAILABILITY_PCT = 90.0
TIER_3_AVAILABILITY_PCT = 80.0
MAX_POTENTIAL_CONCENTRATION_PPM = 400
DATA_AVAILABILITY_FLOOR_PCT = 80.0

# Rolling windows (PRD §3.8)
BASIS_SPAN_HOURS = {"ROLLING_3_HOUR": 3, "ROLLING_30_DAY": 720, "ANNUAL": 8760}
MIN_WINDOW_SAMPLES = {"ROLLING_3_HOUR": 3, "ROLLING_30_DAY": 24, "ANNUAL": 24}
MIN_PENALTY_DEBIT_TONS = 1

# Allowance true-up (PRD §3.9)
PENALTY_RATIO = 2.0

# Bulk append and pagination bounds (PRD §2.3, §3.5)
BULK_MIN_HOURS = 1
BULK_MAX_HOURS = 200
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# Numeric input ranges enforced by ERR_VALUE_OUT_OF_RANGE (PRD §2.8)
VALUE_RANGES = {
    "op_time_fraction": (0.0, 1.0),
    "co2_conc_pct": (0.0, 20.0),
    "so2_conc_ppm": (0, 2000),
    "nox_rate_lb_mmbtu": (0.0, 2.0),
    "sulfur_content_pct": (0.0, 10.0),
    "gcv_btu_per_lb": (1000, 20000),
    "calibration_error_spec_pct": (0.0, 20.0),
    "max_concurrent_control_outages": (0, 10),
    "quarter": (1, 4),
}

# Values reused across fixtures and tests.
TEST_DEFAULTS = {
    "OPERATOR_ORG": "op_alpha",
    "OTHER_OPERATOR_ORG": "op_beta",
    "PREPARER_ONE": "prep_1",
    "PREPARER_TWO": "prep_2",
    "REPRESENTATIVE_ONE": "dr_1",
    "REPRESENTATIVE_TWO": "dr_2",
    "CERTIFICATION_STATEMENT": (
        "I certify under penalty of law that the submitted data are true and complete."
    ),
}
