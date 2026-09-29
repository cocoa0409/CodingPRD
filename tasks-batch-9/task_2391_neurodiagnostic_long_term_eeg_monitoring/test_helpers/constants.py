"""
Business constants for the Neurodiagnostic EMU API test suite.

Every value here is copied from the PRD so that tests never carry bare magic
numbers. Names mirror the vocabulary the PRD uses.
"""

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

API_PREFIX = "/neurodiagnostics"
CLOCK_PATH = "/_clock/set_current_utc"

# ---------------------------------------------------------------------------
# The logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

# "It maintains a logical UTC clock whose value at process startup is exactly
#  `2026-08-01T00:00:00Z`"
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# Instants the suite reuses so that arithmetic in docstrings stays checkable.
T_ADMIT = "2026-08-02T00:00:00Z"
T_ADMIT_PLUS_1D = "2026-08-03T00:00:00Z"
T_ADMIT_PLUS_2D = "2026-08-04T00:00:00Z"
T_ADMIT_PLUS_3D = "2026-08-05T00:00:00Z"
T_COMPLETE = "2026-08-04T12:00:00Z"
T_PRELIM = "2026-08-05T10:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ---------------------------------------------------------------------------
# Numeric precision (PRD §2.8)
# ---------------------------------------------------------------------------

STORAGE_DECIMALS = 2
TURNAROUND_DECIMALS = 2
CAPTURE_DECIMALS = 3
DAILY_RISK_DECIMALS = 1

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

ROLE_UNIT_COORDINATOR = "UnitCoordinator"
ROLE_TECHNOLOGIST = "Technologist"
ROLE_NURSE = "Nurse"
ROLE_EPILEPTOLOGIST = "Epileptologist"
ROLE_PAYER_REVIEWER = "PayerReviewer"

ALL_ROLES = [
    ROLE_UNIT_COORDINATOR,
    ROLE_TECHNOLOGIST,
    ROLE_NURSE,
    ROLE_EPILEPTOLOGIST,
    ROLE_PAYER_REVIEWER,
]

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

SETTING_INPATIENT = "INPATIENT_VEEG"
SETTING_AMBULATORY = "AMBULATORY_VEEG"
SETTINGS = [SETTING_INPATIENT, SETTING_AMBULATORY]

RISK_LOW = "LOW"
RISK_MODERATE = "MODERATE"
RISK_HIGH = "HIGH"
RISK_TIERS = [RISK_LOW, RISK_MODERATE, RISK_HIGH]

POSTURE_OPEN = "OPEN"
POSTURE_COVERAGE_CONSTRAINED = "COVERAGE_CONSTRAINED"
POSTURE_STORAGE_LOCKED = "STORAGE_LOCKED"

BED_AVAILABLE = "AVAILABLE"
BED_OCCUPIED = "OCCUPIED"
BED_TURNOVER = "TURNOVER"

SHIFT_SCHEDULED = "SCHEDULED"
SHIFT_ACTIVE = "ACTIVE"
SHIFT_CLOSED = "CLOSED"

AUTH_DRAFT = "DRAFT"
AUTH_SUBMITTED = "SUBMITTED"
AUTH_PENDED = "PENDED"
AUTH_APPROVED = "APPROVED"
AUTH_DENIED = "DENIED"

OUTCOME_APPROVE = "APPROVE"
OUTCOME_PEND = "PEND"
OUTCOME_DENY = "DENY"

CLINICAL_SCHEDULED = "SCHEDULED"
CLINICAL_ADMITTED = "ADMITTED"
CLINICAL_CAPTURE_TARGET_MET = "CAPTURE_TARGET_MET"
CLINICAL_DISCHARGED = "DISCHARGED"

AUTH_STATE_PENDING = "AUTH_PENDING"
AUTH_STATE_ACTIVE = "AUTH_ACTIVE"
AUTH_STATE_EXHAUSTED = "AUTH_EXHAUSTED"
AUTH_STATE_CLOSED = "AUTH_CLOSED"

DISPOSITION_ROUTINE = "ROUTINE"
DISPOSITION_SURGICAL_EVALUATION = "SURGICAL_EVALUATION"
DISPOSITION_TERMINATED_EARLY = "TERMINATED_EARLY"

TAPER_ACTIVE = "ACTIVE"
TAPER_HELD = "HELD"
TAPER_COMPLETED = "COMPLETED"
TAPER_ABORTED = "ABORTED"

ACQ_PREPARING = "PREPARING"
ACQ_ACQUIRING = "ACQUIRING"
ACQ_PAUSED = "PAUSED"
ACQ_COMPLETED = "COMPLETED"

DATA_ONLINE = "ONLINE"
DATA_EXPORT_HELD = "EXPORT_HELD"
DATA_ARCHIVED = "ARCHIVED"
DATA_PURGED = "PURGED"

ALERT_SOURCE_ALGORITHM = "ALGORITHM"
ALERT_SOURCE_TECHNOLOGIST = "TECHNOLOGIST"
ALERT_SOURCE_PATIENT_PUSH_BUTTON = "PATIENT_PUSH_BUTTON"

TRIAGE_DETECTED = "DETECTED"
TRIAGE_CONFIRMED_CLINICAL = "CONFIRMED_CLINICAL"
TRIAGE_CONFIRMED_SUBCLINICAL = "CONFIRMED_SUBCLINICAL"
TRIAGE_REJECTED_ARTIFACT = "REJECTED_ARTIFACT"
TRIAGE_CLOSED = "CLOSED"

RESPONSE_AWAITING = "AWAITING_RESPONSE"
RESPONSE_ON_TIME = "RESPONDED_ON_TIME"
RESPONSE_LATE = "RESPONDED_LATE"

CLASSIFICATION_CLINICAL = "CLINICAL"
CLASSIFICATION_SUBCLINICAL = "SUBCLINICAL"
CLASSIFICATION_ARTIFACT = "ARTIFACT"

INTERVENTION_POSITIONING = "POSITIONING"
INTERVENTION_SUCTION = "SUCTION"
INTERVENTION_OXYGEN = "OXYGEN"
INTERVENTION_SEIZURE_TESTING = "SEIZURE_TESTING"
INTERVENTION_VITALS = "VITALS"
INTERVENTION_RESCUE_MEDICATION = "RESCUE_MEDICATION"
INTERVENTION_PHYSICIAN_NOTIFIED = "PHYSICIAN_NOTIFIED"

EVENT_CLINICAL_SEIZURE = "CLINICAL_SEIZURE"
EVENT_SUBCLINICAL_SEIZURE = "SUBCLINICAL_SEIZURE"
EVENT_SPIKE_BURST = "SPIKE_BURST"
EVENT_ARTIFACT = "ARTIFACT"

MARKING_PROPOSED = "PROPOSED"
MARKING_ADJUDICATED = "ADJUDICATED"
MARKING_RETRACTED = "RETRACTED"

REPORT_PRELIM_DRAFT = "PRELIM_DRAFT"
REPORT_PRELIM_ISSUED = "PRELIM_ISSUED"
REPORT_ADDENDUM_OPEN = "ADDENDUM_OPEN"
REPORT_FINAL_ISSUED = "FINAL_ISSUED"

EXPORT_QUEUED = "QUEUED"
EXPORT_BLOCKED = "BLOCKED"
EXPORT_BUILT = "BUILT"
EXPORT_DELIVERED = "DELIVERED"
EXPORT_REVOKED = "REVOKED"
EXPORT_PURGED = "PURGED"

CASE_DRAFT = "DRAFT"
CASE_PRESENTED = "PRESENTED"
CASE_CANDIDATE = "CANDIDATE"
CASE_NON_CANDIDATE = "NON_CANDIDATE"
CASE_DEFERRED = "DEFERRED"

SPECIALTY_EPILEPTOLOGY = "EPILEPTOLOGY"
SPECIALTY_NEUROSURGERY = "NEUROSURGERY"
SPECIALTY_NEUROPSYCHOLOGY = "NEUROPSYCHOLOGY"
SPECIALTY_NEURORADIOLOGY = "NEURORADIOLOGY"

VOTE_CANDIDATE = "CANDIDATE"
VOTE_NON_CANDIDATE = "NON_CANDIDATE"
VOTE_DEFER = "DEFER"

EXTENSION_GRANTED = "GRANTED"
EXTENSION_DENIED_RISK = "DENIED_RISK"
EXTENSION_DENIED_AUTH_DAYS = "DENIED_AUTH_DAYS"
EXTENSION_DENIED_TARGET_MET = "DENIED_TARGET_MET"

MAINTENANCE_ELECTRODE_REGEL = "ELECTRODE_REGEL"

# Literal blocked_reason values (PRD §3.9)
BLOCKED_REASON_STUDY_EXPORT_HELD = "STUDY_EXPORT_HELD"
BLOCKED_REASON_UNIT_STORAGE_LOCKED = "UNIT_STORAGE_LOCKED"

# Literal retraction_reason written by the ARTIFACT branch (PRD §3.6)
RETRACTION_REASON_ARTIFACT = "ALERT_REJECTED_AS_ARTIFACT"

# ---------------------------------------------------------------------------
# Bed turnover (PRD §3.1)
# ---------------------------------------------------------------------------

TURNOVER_BUFFER_MINUTES = 90

# ---------------------------------------------------------------------------
# Study storage volume (PRD §3.5)
# ---------------------------------------------------------------------------

GB_PER_CHANNEL_MINUTE = 0.0004
MODALITY_FACTOR = {SETTING_INPATIENT: 2.5, SETTING_AMBULATORY: 1.0}
MIN_CHANNEL_COUNT = 8
IMPEDANCE_LIMIT_KOHM = 10.00

# ---------------------------------------------------------------------------
# Unit storage pressure and posture (PRD §2.11)
# ---------------------------------------------------------------------------

STORAGE_LOCK_PCT = 90.00

# ---------------------------------------------------------------------------
# Interpretation turnaround (PRD §3.8)
# ---------------------------------------------------------------------------

READING_WINDOW_START_HOUR_UTC = 8
READING_WINDOW_END_HOUR_UTC = 18
SLA_PRELIM_COVERAGE_HOURS = 8
MAX_ADDENDA = 2

# ---------------------------------------------------------------------------
# Capture adequacy (PRD §3.7)
# ---------------------------------------------------------------------------

CLASS_WEIGHT = {
    EVENT_CLINICAL_SEIZURE: 1.0,
    EVENT_SUBCLINICAL_SEIZURE: 0.5,
    EVENT_SPIKE_BURST: 0.0,
    EVENT_ARTIFACT: 0.0,
}
TAPER_PROVOKED_DISCOUNT = 0.75
TAPER_DISCOUNT_MIN_STEP = 2
DEFAULT_MARKING_DURATION_SECONDS = 60
CAPTURE_TARGET_MET_INDEX = 1.000

# ---------------------------------------------------------------------------
# Length-of-stay extension (PRD §3.7)
# ---------------------------------------------------------------------------

RISK_ALLOWANCE_UNITS = 24
BASE_RISK = {RISK_LOW: 2, RISK_MODERATE: 3, RISK_HIGH: 5}
TAPER_RISK_PER_STEP = 1.5
POSTURE_CONSTRAINED_RISK_ADD = 2

# ---------------------------------------------------------------------------
# Alert response deadline (PRD §3.6)
# ---------------------------------------------------------------------------

TIER_BASE_DEADLINE_MINUTES = {RISK_LOW: 10, RISK_MODERATE: 6, RISK_HIGH: 3}
DEADLINE_TAPER_STEP_SUBTRACT = 1
DEADLINE_COVERAGE_CONSTRAINED_ADD = 2
DEADLINE_NIGHT_ADD = 1
DEADLINE_NIGHT_FROM_HOUR = 22
DEADLINE_NIGHT_TO_HOUR = 5
DEADLINE_FLOOR_MINUTES = 2
DEADLINE_CEILING_MINUTES = 15

# ---------------------------------------------------------------------------
# Authorization day ledger (PRD §3.2)
# ---------------------------------------------------------------------------

MAX_RESUBMISSIONS = 2

# ---------------------------------------------------------------------------
# Retention and conference (PRD §3.9)
# ---------------------------------------------------------------------------

RETENTION_DAYS = 30
QUORUM_MIN_VOTES = 3
QUORUM_MIN_SPECIALTIES = 2
MAX_DEFER_ROUNDS = 2
