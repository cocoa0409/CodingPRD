"""Literal constants the PRD states, plus the default values tests build from."""

# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------

CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_START_RENDERED = "2026-08-01T00:00:00.000Z"

# --------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------

FITTING_CROSS_ALLOWANCE_MM = 4.0
SPECIALTY_ALLOWANCE_MM = 2.0
CHUCK_ALLOWANCE_MM = 2.0
MAX_BLANK_DIAMETER_MM = 85.0

# --------------------------------------------------------------------------
# Route determination
# --------------------------------------------------------------------------

STOCK_SPHERE_ABS_MAX = 6.00
STOCK_CYLINDER_ABS_MAX = 2.00

# --------------------------------------------------------------------------
# Turnaround and expedite
# --------------------------------------------------------------------------

BASE_TAT_HOURS = {"ECONOMY": 120, "STANDARD": 72, "PREMIUM": 48}
SURFACING_TAT_PENALTY_HOURS = 24
EXPEDITE_FACTOR = 0.5
BACKORDER_EXTENSION_HOURS = 48

# Ordered bands: the first row whose hour ceiling covers the promise wins.
EXPEDITE_FEE_BANDS = ((24, 0.30), (48, 0.20), (72, 0.12))
EXPEDITE_FEE_BEYOND_BANDS = 0.00

# --------------------------------------------------------------------------
# Money
# --------------------------------------------------------------------------

SURFACING_SURCHARGE_CENTS = 4500

COATING_PRICE_CENTS = {
    "HARDCOAT": 2495,
    "AR_STANDARD": 5995,
    "AR_PREMIUM": 10995,
    "POLARIZED": 11995,
    "PHOTOCHROMIC": 13995,
}

BENEFIT_PERIOD_MONTHS = 12

# --------------------------------------------------------------------------
# Inspection
# --------------------------------------------------------------------------

AXIS_RELEVANCE_CYL_MIN = 0.25
MAX_REWORK_CYCLES = 2
FAILED_METRIC_ORDER = ("SPHERE", "CYLINDER", "AXIS", "PRISM", "COSMETIC")

# --------------------------------------------------------------------------
# Remake
# --------------------------------------------------------------------------

MIXED_DEFECT_LAB_SHARE_PCT = 50
REMAKE_WRITEOFF_PCT = {1: 0.25, 2: 0.60}
MAX_REMAKES_PER_ORDER = 2
WARRANTY_DAYS = 90

LAB_ATTRIBUTABLE_DEFECTS = (
    "POWER_OUT_OF_TOL",
    "AXIS_OUT_OF_TOL",
    "PRISM_OUT_OF_TOL",
    "COSMETIC_DEFECT",
    "WRONG_MATERIAL",
    "WRONG_COATING",
)
STORE_ATTRIBUTABLE_DEFECTS = (
    "WRONG_PD",
    "WRONG_FITTING_HEIGHT",
    "WRONG_FRAME",
    "PATIENT_NONADAPT",
    "RX_TRANSCRIPTION",
)

# --------------------------------------------------------------------------
# Registry defaults
# --------------------------------------------------------------------------

DEFAULT_MAX_RX_VALIDITY_MONTHS = 12
DEFAULT_CALIBRATION_BUFFER_MINUTES = 15
DEFAULT_BENEFIT_PERIOD_START = "2026-01-01"

# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0
MAX_LIMIT = 100

# --------------------------------------------------------------------------
# Occupation windows
# --------------------------------------------------------------------------

MAX_OPERATION_WINDOW_HOURS = 8

# --------------------------------------------------------------------------
# Fixed test data used across the suite
# --------------------------------------------------------------------------

TEST_DEFAULTS = {
    "npi_primary": "1234567893",
    "npi_secondary": "1234567802",
    "npi_tertiary": "1679576722",
    "npi_alternate": "1245319599",
    "license_state": "CA",
    "prescriber_name": "Dr Iris Vance",
    "self_pay_patient_name": "Owen Pike",
    "self_pay_patient_dob": "1981-11-09",
    "insured_patient_name": "Nora Ellis",
    "insured_patient_dob": "1974-05-02",
    "member_number": "M-88120",
    "issued_on": "2026-03-01",
    "verification_note": "NPI and license match the prescriber record",
}

# A syntactically valid UUID that no row ever carries.
UNISSUED_UUID = "00000000-0000-4000-8000-0000000000ff"
UNISSUED_DESIGN_UUID = "00000000-0000-4000-8000-0000000000aa"
