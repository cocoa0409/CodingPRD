"""Business constants and enum vocabularies drawn from the PRD.

Every literal in this module is quoted from the specification rather than
guessed, so a single edit here propagates to every test that depends on it.
"""

# ---------------------------------------------------------------------------
# API root
# ---------------------------------------------------------------------------
# "The service is mounted under `/duct-sealing`".
API_PREFIX = "/duct-sealing"

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
# "On startup the logical clock reads exactly `2026-08-01T00:00:00Z`".
CLOCK_STARTUP_ISO = "2026-08-01T00:00:00Z"
# The same instant as it is rendered back on `*_at` fields: "an ISO 8601 UTC
# timestamp with three fractional digits".
CLOCK_STARTUP_STAMP = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_FIELD_TECHNICIAN = "FieldTechnician"
ROLE_QA_VERIFIER = "QAVerifier"
ROLE_UTILITY_INSPECTOR = "UtilityInspector"

ALL_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_FIELD_TECHNICIAN,
    ROLE_QA_VERIFIER,
    ROLE_UTILITY_INSPECTOR,
)

# ---------------------------------------------------------------------------
# Leakage normalization (PRD 3.3)
# ---------------------------------------------------------------------------
# "multiplying `measured_leakage_cfm` by the ratio of 25 to `test_pressure_pa`
# raised to the power of the flow exponent 0.60".
FLOW_EXPONENT = 0.60
REFERENCE_PRESSURE_PA = 25
# "`test_pressure_pa` ... must lie between 10 and 100 inclusive".
MIN_TEST_PRESSURE_PA = 10
MAX_TEST_PRESSURE_PA = 100
# "half an hour before its `window_start_at` to half an hour after".
STABILIZATION_BUFFER_MINUTES = 30

# ---------------------------------------------------------------------------
# Guarantee and rebate arithmetic (PRD 3.7, 3.8)
# ---------------------------------------------------------------------------
# "80.00 percent when `utility_program_id` is null".
GUARANTEE_DEFAULT_MIN_PCT = 80.00
# "`admin_fee_cents` is five percent of `capped_subtotal_cents`".
ADMIN_FEE_RATE = 0.05
# "`tier_bonus_pct` is 0.20 when ... at least 90.00, otherwise 0.10 when it is
# at least 75.00, otherwise 0.05 when it is at least 60.00, otherwise 0.00".
TIER_BONUS_BANDS = ((90.00, 0.20), (75.00, 0.10), (60.00, 0.05))
TIER_BONUS_NONE = 0.00
# "`inspector_outcome` becomes `FAIL` when `inspector_variance_pct` is strictly
# above 10.00 percent".
INSPECTOR_TOLERANCE_PCT = 10.00

# ---------------------------------------------------------------------------
# Injection run (PRD 3.6)
# ---------------------------------------------------------------------------
# "The cutoff fires when `injection_pressure_pa` is strictly above 1000.0".
MAX_INJECTION_PA = 1000.0
# "When the computed rate is strictly below half a CFM per minute".
MIN_SEAL_RATE_CFM_PER_MIN = 0.50
# "a fixed **three-sample backward window**".
STALL_WINDOW_SAMPLES = 3

# ---------------------------------------------------------------------------
# Combustion safety (PRD 3.4)
# ---------------------------------------------------------------------------
# "Spillage is limited to 60 seconds for every appliance class".
SPILLAGE_MAX_SECONDS = 60
# "the draft is considered weak below 1.0 pascal".
DRAFT_MIN_PA = 1.0

APPLIANCE_ATMOSPHERIC_WATER_HEATER = "ATMOSPHERIC_WATER_HEATER"
APPLIANCE_FURNACE = "FURNACE"
APPLIANCE_BOILER = "BOILER"
APPLIANCE_RANGE = "RANGE"

# "For an `ATMOSPHERIC_WATER_HEATER`, a `FURNACE` or a `BOILER` the
# carbon-monoxide ceiling is 100 ppm, the carbon-monoxide warning level is
# 50 ppm, and the worst-case depressurization limit is 5.0 pascals. A `RANGE`
# is held to looser numbers: an 800 ppm ceiling, a 400 ppm warning level, and a
# depressurization limit of 999.0 pascals".
CO_MAX_PPM = {
    APPLIANCE_ATMOSPHERIC_WATER_HEATER: 100.0,
    APPLIANCE_FURNACE: 100.0,
    APPLIANCE_BOILER: 100.0,
    APPLIANCE_RANGE: 800.0,
}
CO_WARN_PPM = {
    APPLIANCE_ATMOSPHERIC_WATER_HEATER: 50.0,
    APPLIANCE_FURNACE: 50.0,
    APPLIANCE_BOILER: 50.0,
    APPLIANCE_RANGE: 400.0,
}
WCD_LIMIT_PA = {
    APPLIANCE_ATMOSPHERIC_WATER_HEATER: 5.0,
    APPLIANCE_FURNACE: 5.0,
    APPLIANCE_BOILER: 5.0,
    APPLIANCE_RANGE: 999.0,
}

# ---------------------------------------------------------------------------
# Warranty and comfort complaints (PRD 3.9)
# ---------------------------------------------------------------------------
# "sets `retest_due_at` to one year — 365 whole days — after".
RETEST_INTERVAL_DAYS = 365
# "The house default the crews work to is 10.00 percent".
DEFAULT_TOLERANCE_PCT = 10.00
MIN_TOLERANCE_PCT = 0.00
MAX_TOLERANCE_PCT = 50.00

# ---------------------------------------------------------------------------
# Project intake floors (PRD 3.1)
# ---------------------------------------------------------------------------
# "`conditioned_floor_area_sqft` ... must be at least 100".
MIN_FLOOR_AREA_SQFT = 100
# "`pct_of_invoice_bps` ... must fall between 0 and 10000 inclusive".
MAX_PCT_OF_INVOICE_BPS = 10000

# ---------------------------------------------------------------------------
# Enumeration vocabularies declared by the PRD
# ---------------------------------------------------------------------------
# --- UtilityProgram -------------------------------------------------------
REBATE_BASIS_PER_CFM = "PER_CFM"
REBATE_BASIS_PERCENT_OF_INVOICE = "PERCENT_OF_INVOICE"
REBATE_BASIS_LESSER_OF_BOTH = "LESSER_OF_BOTH"
REBATE_BASES = (
    REBATE_BASIS_PER_CFM,
    REBATE_BASIS_PERCENT_OF_INVOICE,
    REBATE_BASIS_LESSER_OF_BOTH,
)

# --- Technician -----------------------------------------------------------
CERT_PENDING = "PENDING"
CERT_ACTIVE = "ACTIVE"
CERT_SUSPENDED = "SUSPENDED"
CERT_REVOKED = "REVOKED"
CERT_STATUSES = (CERT_PENDING, CERT_ACTIVE, CERT_SUSPENDED, CERT_REVOKED)

# --- Project --------------------------------------------------------------
PROJECT_ACTIVE = "ACTIVE"
PROJECT_SAFETY_HOLD = "SAFETY_HOLD"

# --- DuctSystem -----------------------------------------------------------
MATERIAL_SHEET_METAL = "SHEET_METAL"
MATERIAL_FLEX = "FLEX"
MATERIAL_DUCT_BOARD = "DUCT_BOARD"
MATERIAL_ASBESTOS_WRAP = "ASBESTOS_WRAP"
DUCT_MATERIALS = (
    MATERIAL_SHEET_METAL,
    MATERIAL_FLEX,
    MATERIAL_DUCT_BOARD,
    MATERIAL_ASBESTOS_WRAP,
)

GRADE_A = "A"
GRADE_B = "B"
GRADE_C = "C"
GRADE_FAIL = "FAIL"
CONDITION_GRADES = (GRADE_A, GRADE_B, GRADE_C, GRADE_FAIL)

SCREENING_PENDING = "PENDING"
SCREENING_CLEARED = "CLEARED"
SCREENING_SUSPECT = "SUSPECT"
SCREENING_CONFIRMED = "CONFIRMED"
SCREENING_RESULTS = (
    SCREENING_PENDING,
    SCREENING_CLEARED,
    SCREENING_SUSPECT,
    SCREENING_CONFIRMED,
)

ELIGIBILITY_PENDING_SCREENING = "PENDING_SCREENING"
ELIGIBILITY_ELIGIBLE = "ELIGIBLE"
ELIGIBILITY_EXCLUDED = "EXCLUDED"

SEAL_STATUS_SEAL_PENDING = "SEAL_PENDING"
SEAL_STATUS_SEALING = "SEALING"
SEAL_STATUS_SEALED = "SEALED"
SEAL_STATUS_VERIFIED = "VERIFIED"

EXCLUSION_STRUCTURAL_DAMAGE = "STRUCTURAL_DAMAGE"
EXCLUSION_MATERIAL_NOT_SEALABLE = "MATERIAL_NOT_SEALABLE"
EXCLUSION_INACCESSIBLE = "INACCESSIBLE"
EXCLUSION_ASBESTOS_CONFIRMED = "ASBESTOS_CONFIRMED"
# "it takes an `exclusion_reason` drawn from `STRUCTURAL_DAMAGE`,
# `MATERIAL_NOT_SEALABLE` or `INACCESSIBLE`".
ADMIN_EXCLUSION_REASONS = (
    EXCLUSION_STRUCTURAL_DAMAGE,
    EXCLUSION_MATERIAL_NOT_SEALABLE,
    EXCLUSION_INACCESSIBLE,
)

# --- LeakageTest ----------------------------------------------------------
PHASE_PRE = "PRE"
PHASE_POST = "POST"

METHOD_PRESSURE_PAN = "PRESSURE_PAN"
METHOD_DUCT_BLASTER = "DUCT_BLASTER"
METHOD_AEROSEAL_INTERNAL = "AEROSEAL_INTERNAL"
TEST_METHODS = (METHOD_PRESSURE_PAN, METHOD_DUCT_BLASTER, METHOD_AEROSEAL_INTERNAL)

RING_1 = "RING_1"
RING_2 = "RING_2"
RING_3 = "RING_3"
FAN_RING_CONFIGS = (RING_1, RING_2, RING_3)

TEST_DRAFT = "DRAFT"
TEST_PRESSURIZED = "PRESSURIZED"
TEST_RECORDED = "RECORDED"
TEST_ACCEPTED = "ACCEPTED"
TEST_REJECTED = "REJECTED"

DECISION_ACCEPT = "ACCEPT"
DECISION_REJECT = "REJECT"

# --- CombustionTest -------------------------------------------------------
VERDICT_PASS = "PASS"
VERDICT_MARGINAL = "MARGINAL"
VERDICT_FAIL = "FAIL"

# --- SealJob --------------------------------------------------------------
JOB_SCHEDULED = "SCHEDULED"
JOB_MASKING = "MASKING"
JOB_INJECTING = "INJECTING"
JOB_PAUSED = "PAUSED"
JOB_SEALED = "SEALED"
JOB_VERIFIED = "VERIFIED"
JOB_RETEST_REQUIRED = "RETEST_REQUIRED"
JOB_RETEST_CLOSED = "RETEST_CLOSED"
JOB_ABORTED_MANUAL = "ABORTED_MANUAL"
JOB_ABORTED_SAFETY = "ABORTED_SAFETY"
JOB_ABORTED_EXCLUSION = "ABORTED_EXCLUSION"
JOB_ABORTED_SUPERSEDED = "ABORTED_SUPERSEDED"
# "Five terminal statuses exist for a run and none of them accepts any further
# action: `RETEST_CLOSED`, `ABORTED_MANUAL`, `ABORTED_SAFETY`,
# `ABORTED_EXCLUSION` and `ABORTED_SUPERSEDED`."
JOB_TERMINAL_STATUSES = (
    JOB_RETEST_CLOSED,
    JOB_ABORTED_MANUAL,
    JOB_ABORTED_SAFETY,
    JOB_ABORTED_EXCLUSION,
    JOB_ABORTED_SUPERSEDED,
)
# "runs whose status is `SCHEDULED`, `MASKING`, `INJECTING` or `PAUSED`".
JOB_OPEN_STATUSES = (JOB_SCHEDULED, JOB_MASKING, JOB_INJECTING, JOB_PAUSED)

WARRANTY_NOT_REGISTERED = "NOT_REGISTERED"
WARRANTY_REGISTERED = "REGISTERED"
WARRANTY_SUSPENDED = "SUSPENDED"
WARRANTY_LAPSED = "LAPSED"

ABORT_REASON_SUPERSEDED = "superseded by a newer scheduled job"
ABORT_REASON_ASBESTOS = "asbestos confirmed"
ABORT_REASON_PRESSURE_CUTOFF = "injection pressure cutoff"
ABORT_REASON_COMBUSTION = "combustion spillage failure"

# --- VerificationReport ---------------------------------------------------
REPORT_DRAFT = "DRAFT"
REPORT_ISSUED = "ISSUED"
REPORT_CORRECTION_REQUIRED = "CORRECTION_REQUIRED"
REPORT_VOIDED = "VOIDED"

# --- RebateClaim ----------------------------------------------------------
CLAIM_SUBMITTED = "SUBMITTED"
CLAIM_APPROVED = "APPROVED"
CLAIM_RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
CLAIM_PAID = "PAID"
CLAIM_WITHDRAWN = "WITHDRAWN"

INSPECTOR_PENDING = "PENDING"
INSPECTOR_PASS = "PASS"
INSPECTOR_FAIL = "FAIL"

# --- ComfortComplaint -----------------------------------------------------
COMPLAINT_TOO_HOT = "TOO_HOT"
COMPLAINT_TOO_COLD = "TOO_COLD"
COMPLAINT_NOISE = "NOISE"
COMPLAINT_ODOR = "ODOR"
COMPLAINT_DUST = "DUST"
COMPLAINT_TYPES = (
    COMPLAINT_TOO_HOT,
    COMPLAINT_TOO_COLD,
    COMPLAINT_NOISE,
    COMPLAINT_ODOR,
    COMPLAINT_DUST,
)

COMPLAINT_OPEN = "OPEN"
COMPLAINT_DIAGNOSED = "DIAGNOSED"
COMPLAINT_BALANCING = "BALANCING"
COMPLAINT_RESOLVED = "RESOLVED"

DIAG_UNDERSIZED_BRANCH = "UNDERSIZED_BRANCH"
DIAG_DAMPER_MISADJUSTED = "DAMPER_MISADJUSTED"
DIAG_BLOCKED_REGISTER = "BLOCKED_REGISTER"
DIAG_EXCESS_BYPASS = "EXCESS_BYPASS"
DIAG_RESIDUAL_LEAKAGE = "RESIDUAL_LEAKAGE"
DIAGNOSIS_CODES = (
    DIAG_UNDERSIZED_BRANCH,
    DIAG_DAMPER_MISADJUSTED,
    DIAG_BLOCKED_REGISTER,
    DIAG_EXCESS_BYPASS,
    DIAG_RESIDUAL_LEAKAGE,
)
