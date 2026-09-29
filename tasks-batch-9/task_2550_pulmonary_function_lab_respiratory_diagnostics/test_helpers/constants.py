"""Business constants for the hospital pulmonary function laboratory API.

Every value here is stated in the PRD and is copied from it verbatim so that
tests never re-derive a threshold they are supposed to be checking.
"""

# ---------------------------------------------------------------- API prefix
API_PREFIX = "/pft-lab"

# ------------------------------------------------------------- logical clock
# Before the clock has ever been set the server reads this instant.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# The instant nearly every scenario in this suite pins the clock to.
MORNING_CLOCK = "2026-08-03T08:00:00Z"

# A syntactically valid UUID that matches no row of any type.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"

# ------------------------------------------------ BTPS correction (calibration)
SYRINGE_VOLUME_L = 3.000
CAL_TOLERANCE_PCT = 3.00
BODY_TEMP_K = 310.15
KELVIN_OFFSET = 273.15
PH2O_BODY_KPA = 6.27

# Saturated water-vapour pressure in kPa, keyed by whole ambient degrees C.
PH2O_BY_TEMP_C = {
    20: 2.34,
    21: 2.49,
    22: 2.64,
    23: 2.81,
    24: 2.98,
    25: 3.17,
    26: 3.36,
    27: 3.57,
}
AMBIENT_TEMP_MIN_C = 20
AMBIENT_TEMP_MAX_C = 27
BAROMETRIC_MIN_KPA = 80.00
BAROMETRIC_MAX_KPA = 110.00

# ------------------------------------------------------ biologic control (BCS)
BASELINE_VALIDITY_DAYS = 180
ROLLING_WINDOW_SIZE = 3
BCS_PASS_PCT = 5.00
BCS_WARN_PCT = 10.00

# --------------------------------------------------------- reference equations
Z_LLN = 1.645

# ------------------------------------------------------- maneuver acceptability
BEV_ABS_ML = 100
BEV_FRAC = 0.05
EOFE_MIN_SEC = 15.0
REPEAT_TIGHT_ML = 150
REPEAT_LOOSE_ML = 200
MAX_REJECTION_ROUNDS = 2

# ----------------------------------------------------- bronchodilator response
BD_PCT_BASELINE_MIN = 12.0
BD_ML_MIN = 200
BD_PCT_PREDICTED_MIN = 10.0

# ---------------------------------------------------------- interpretation
FVC_NORMAL_PCT = 80.0
TEMPLATE_VERSION = "PFT-2026.1"
SEVERITY_MILD_MIN = 70.0
SEVERITY_MODERATE_MIN = 60.0
SEVERITY_MODERATELY_SEVERE_MIN = 50.0
SEVERITY_SEVERE_MIN = 35.0

# ------------------------------------------------------------------ SLA policy
SLA_BASE_MINUTES = {
    "ROUTINE_CLINICAL": 1440,
    "OCCUPATIONAL_SURVEILLANCE": 2880,
    "DISABILITY_EVALUATION": 4320,
}
TEST_CONTEXTS = tuple(SLA_BASE_MINUTES)
LOAD_NORMAL_PCT = 50.00
LOAD_ELEVATED_PCT = 80.00
LOAD_MULTIPLIER_NORMAL = 1.00
LOAD_MULTIPLIER_ELEVATED = 1.50
LOAD_MULTIPLIER_SURGE = 2.00

# ------------------------------------------------------- challenge / rescue lot
PC20_THRESHOLD_PCT = 20.00
MAX_CUMULATIVE_DOSE_UNITS = 400
CHALLENGE_MIN_FEV1_PCT = 60.0
RESCUE_RESERVE_DOSES = 4
RESCUE_ADMIN_DOSES = 4

# ------------------------------------------------------------ resource windows
DEVICE_TURNAROUND_MINUTES = 20
TECH_MAX_CONCURRENT_SESSIONS = 2

# --------------------------------------------------------- infection control
MIN_DWELL_MINUTES = 20

# ------------------------------------------------------------ medication holds
HOLD_HOURS_BY_CLASS = {
    "SABA": 6,
    "SAMA": 8,
    "LABA": 24,
    "LAMA": 36,
    "ICS_LABA": 24,
    "ANTIHISTAMINE": 72,
    "CAFFEINE": 8,
}

# ------------------------------------------------------------------- enum sets
MODALITIES = ("SPIROMETRY", "DLCO", "PLETHYSMOGRAPHY")
DEVICE_STATUSES = ("NEW", "AVAILABLE", "SOILED", "QUARANTINED", "RETIRED")
QUALITY_EVENT_TYPES = (
    "VOLUME_CALIBRATION",
    "LEAK_CHECK",
    "BIOLOGIC_CONTROL",
    "FILTER_REPLACEMENT",
    "HIGH_LEVEL_DISINFECT",
)
QUALITY_OUTCOMES = ("PASS", "WARN", "FAIL", "COMPLETE", "INCOMPLETE")
DEVIATION_VARIANTS = ("ABSOLUTE_BASELINE", "ROLLING_MEAN")
BD_CRITERIA = ("PCT_BASELINE_2005", "PCT_PREDICTED_2021")
ORDER_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "INDICATION_REJECTED",
    "MED_HOLD_ISSUED",
    "READY",
    "IN_TESTING",
    "COMPLETED",
    "CANCELLED",
)
SESSION_STATUSES = (
    "SCHEDULED",
    "IN_PROGRESS",
    "ACCEPTED",
    "REJECTED",
    "ABORTED",
    "REPORTED",
)
CUSTODY_STATUSES = (
    "NOT_APPLICABLE",
    "CUSTODY_OPEN",
    "CUSTODY_ID_VERIFIED",
    "CUSTODY_SEALED",
    "CUSTODY_BROKEN",
)
CUSTODY_EVENT_TYPES = ("ID_VERIFIED", "SEAL_APPLIED", "SEAL_BROKEN", "WITNESS_SIGNED")
ID_DOCUMENT_TYPES = ("PHOTO_ID", "PASSPORT", "EMPLOYEE_BADGE")
QUALITY_GRADES = ("A", "B", "C", "D", "F")
PATTERNS = ("NORMAL", "OBSTRUCTION", "RESTRICTION", "MIXED")
SEVERITIES = ("NONE", "MILD", "MODERATE", "MODERATELY_SEVERE", "SEVERE", "VERY_SEVERE")
RUN_STATUSES = (
    "ARMED",
    "IN_PROGRESS",
    "STOPPED_PC20",
    "COMPLETED_NEGATIVE",
    "ABORTED_SAFETY",
)
REPORT_STATUSES = ("ASSIGNED", "SIGNED", "AMENDED", "REASSIGNED")
HOLD_STATUSES = ("PENDING", "ATTESTED", "VIOLATED", "SUPERSEDED")
LOT_STATUSES = ("STOCKED", "DEPLETED", "EXPIRED")
