"""Business constants for the Nurse Triage Call Center API (PRD §2 and §3).

Every value here is quoted or derived from the PRD text; nothing is invented.
"""

# ── Roles (PRD §2.1) ────────────────────────────────────────────────────────
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_INTAKE_AGENT = "IntakeAgent"
ROLE_TRIAGE_NURSE = "TriageNurse"
ROLE_CHARGE_NURSE = "ChargeNurse"
ROLE_COMPLIANCE_AUDITOR = "ComplianceAuditor"
ROLE_PRACTICE_LIAISON = "PracticeLiaison"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_INTAKE_AGENT,
    ROLE_TRIAGE_NURSE,
    ROLE_CHARGE_NURSE,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_PRACTICE_LIAISON,
)

# ── The logical clock (PRD §2.4) ────────────────────────────────────────────
# "On a freshly started server the logical clock reads 2026-08-01T00:00:00Z"
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# 2026-08-03 is a Monday; 2026-08-01 is a Saturday.
CLOCK_MONDAY_IN_HOURS = "2026-08-03T14:30:00Z"
CLOCK_SATURDAY_AFTER_HOURS = "2026-08-01T14:30:00Z"

# ── Pagination (PRD §2.3) ───────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── Practice defaults (PRD §3.1) ────────────────────────────────────────────
DEFAULT_OFFICE_OPEN_HHMM = "13:00"
DEFAULT_OFFICE_CLOSE_HHMM = "22:00"
DEFAULT_PER_MINUTE_RATE_MILLICENTS = 4225
DEFAULT_WEEKEND_IS_AFTER_HOURS = True
DEFAULT_CONSENT_RECORDING_REQUIRED = False
DEFAULT_VARIANCE_REVIEW_THRESHOLD = 2

PRACTICE_STATUSES = ("ACTIVE", "SUSPENDED")
COMPLIANCE_POSTURES = ("NORMAL", "UNDER_REVIEW")

# ── Patient (PRD §3.1) ─────────────────────────────────────────────────────
SEXES = ("FEMALE", "MALE", "UNKNOWN")
PREGNANCY_STATUSES = ("NOT_APPLICABLE", "NOT_PREGNANT", "PREGNANT", "POSTPARTUM_6W")
DEFAULT_PREGNANCY_STATUS = "NOT_APPLICABLE"

# ── Symptom protocol (PRD §3.1) ────────────────────────────────────────────
PROTOCOL_STATUSES = ("ACTIVE", "RETIRED")
DEFAULT_INFANT_MODIFIER_POINTS = 20

# ── Nurse, licence and shift (PRD §3.2) ────────────────────────────────────
INTAKE_ELIGIBILITIES = ("ON_ROTATION", "OFF_ROTATION")
LICENSE_STATUSES = ("ACTIVE", "EXPIRED")
SHIFT_STATUSES = ("SCHEDULED", "ACTIVE", "ENDED")

# ── Coverage windows (PRD §3.2) ────────────────────────────────────────────
COVERAGE_KINDS = ("NIGHTS", "WEEKEND", "HOLIDAY", "OVERFLOW")
COVERAGE_WINDOW_STATUSES = ("DRAFT", "ACTIVE", "EXPIRED", "BLOCKED")
COVERAGE_BUFFER_MINUTES = 30
SUSPEND_REASON_COMPLIANCE_REVIEW = "PRACTICE_UNDER_COMPLIANCE_REVIEW"

# ── Triage call (PRD §3.3) ─────────────────────────────────────────────────
CALLER_RELATIONSHIPS = (
    "SELF",
    "PARENT_GUARDIAN",
    "SPOUSE",
    "CAREGIVER",
    "HEALTHCARE_PROXY",
    "OTHER",
)
CALL_STATUSES = (
    "INTAKE",
    "IDENTIFIED",
    "CONSENTED",
    "ASSIGNED",
    "ASSESSING",
    "DISPOSITIONED",
    "CLOSED",
    "ABANDONED",
)
MATCH_METHODS = ("DOB_AND_NAME", "PHONE_AND_NAME", "MRN")
MIN_MATCH_CONFIDENCE_PCT = 80
CONSENT_TYPES = ("PATIENT_SELF", "GUARDIAN", "HEALTHCARE_PROXY")
MINOR_AGE_YEARS = 18

# ── Assessment and acuity (PRD §3.5) ───────────────────────────────────────
CONFIRMATION_MODES = ("PROVISIONAL", "CONFIRMED")
ASSESSMENT_STATUSES = ("ACTIVE", "SUPERSEDED")

RED_FLAG_WEIGHT = 8
RED_FLAG_CAP = 24
PEDIATRIC_AGE_YEARS = 12
PEDIATRIC_POINTS = 10
GERIATRIC_AGE_YEARS = 65
GERIATRIC_POINTS = 12
PREGNANT_POINTS = 15
POSTPARTUM_POINTS = 8
ACUITY_MIN = 0
ACUITY_MAX = 100

# ── Disposition levels and bands (PRD §3.6) ────────────────────────────────
DISPOSITION_LEVELS = (
    "EMERGENCY_911",
    "ED_NOW",
    "URGENT_CARE_24H",
    "OFFICE_APPT_72H",
    "HOME_CARE",
)
LEVEL_ORDINAL = {
    "EMERGENCY_911": 5,
    "ED_NOW": 4,
    "URGENT_CARE_24H": 3,
    "OFFICE_APPT_72H": 2,
    "HOME_CARE": 1,
}
BAND_EMERGENCY_911_MIN = 85
BAND_ED_NOW_MIN = 70
BAND_URGENT_CARE_24H_MIN = 50
BAND_OFFICE_APPT_72H_MIN = 30

OVERRIDE_REASON_CODES = (
    "CALLER_REFUSED_ED",
    "TRANSPORT_UNAVAILABLE",
    "CLINICIAN_DIRECTED",
    "PROTOCOL_MISMATCH",
    "LANGUAGE_BARRIER",
)
MIN_OVERRIDE_NARRATIVE_CHARS = 40
ADVICE_STATUSES = ("AUTHORIZED", "OVERRIDDEN", "VOIDED")
AUDIT_STATUSES = (
    "AWAITING_OUTCOME",
    "OUTCOME_RECORDED",
    "CONCORDANT_CLOSED",
    "VARIANCE_ESCALATED",
)

# A narrative long enough to satisfy the forty-character documentation rule.
VALID_OVERRIDE_NARRATIVE = (
    "Caller declined emergency department transport twice and agreed to the "
    "alternative plan documented here."
)
SHORT_OVERRIDE_NARRATIVE = "Too short to document."

# ── Callback tasks (PRD §3.6 and §3.8) ─────────────────────────────────────
CALLBACK_RISK_CLASSES = ("HIGH_RISK", "STANDARD", "NEXT_DAY")
CALLBACK_STATUSES = (
    "PENDING",
    "ATTEMPTED",
    "REACHED",
    "VERIFIED",
    "ESCALATED",
    "EXPIRED",
    "CANCELLED",
)
HIGH_RISK_MIN_LEVEL_ORDINAL = 4
HIGH_RISK_DUE_HOURS = 2
STANDARD_DUE_HOURS = 12
HIGH_RISK_MAX_ATTEMPTS = 3
STANDARD_MAX_ATTEMPTS = 2
ATTEMPT_OUTCOMES = ("NO_ANSWER", "BUSY", "REACHED")
PATIENT_CONDITIONS = ("IMPROVED", "UNCHANGED", "WORSENED")

# ── Warm transfer (PRD §3.7) ───────────────────────────────────────────────
LOCATION_SOURCES = ("CALLER_STATED", "DEVICE_GPS", "PRACTICE_RECORD")
TRANSFER_STATUSES = (
    "INITIATED",
    "LOCATION_CONFIRMED",
    "ACCEPTED_BY_PSAP",
    "REJECTED_BY_PSAP",
    "HANDOFF_COMPLETE",
)
MIN_LOCATION_CONFIDENCE_PCT = 75

# ── Billing (PRD §3.9) ─────────────────────────────────────────────────────
BILLING_INCREMENT_MINUTES = 5
MIN_HANDLE_MINUTES = 1
MAX_HANDLE_MINUTES = 240
REOPEN_WINDOW_HOURS = 72

# ── Outcome audit (PRD §3.10) ──────────────────────────────────────────────
REPORTED_OUTCOMES = (
    "ED_ADMITTED",
    "ED_TREATED_RELEASED",
    "URGENT_CARE_VISIT",
    "OFFICE_VISIT",
    "SELF_CARE_RESOLVED",
)
OUTCOME_ORDINAL = {
    "ED_ADMITTED": 5,
    "ED_TREATED_RELEASED": 4,
    "URGENT_CARE_VISIT": 3,
    "OFFICE_VISIT": 2,
    "SELF_CARE_RESOLVED": 1,
}
OUTCOME_SOURCES = ("EHR_CLAIM", "PATIENT_REPORT", "ED_FEED")
VARIANCE_CLASSES = ("CONCORDANT", "UNDERTRIAGE", "OVERTRIAGE")
UNDERTRIAGE_POINTS_PER_ORDINAL = 7
OVERTRIAGE_POINTS_PER_ORDINAL = 3

# ── After-hours invoice (PRD §3.10) ────────────────────────────────────────
ESCALATION_UNIT_CENTS = 2500
CREDIT_TIER_LOW_MAX_CENTS = 99
CREDIT_TIER_MID_MAX_CENTS = 999
CREDIT_PCT_LOW = 0
CREDIT_PCT_MID = 5
CREDIT_PCT_HIGH = 10

# ── Staffing adequacy (PRD §3.10) ──────────────────────────────────────────
AVG_HANDLE_MINUTES = 14
TARGET_OCCUPANCY_PCT = 80
STAFFING_POSTURES = ("ADEQUATE", "STRAINED", "CRITICAL")
POSTURE_ADEQUATE_MIN_PCT = 100.0
POSTURE_STRAINED_MIN_PCT = 80.0

# ── Common resource properties (PRD §2.5) ──────────────────────────────────
# Resources that carry updated_at and version.
VERSIONED_ENTITIES = (
    "Practice",
    "Nurse",
    "CoverageWindow",
    "Patient",
    "SymptomProtocol",
    "TriageCall",
    "ProtocolAssessment",
    "Disposition",
    "WarmTransfer",
    "CallbackTask",
)
# Resources that are immutable and carry only id and created_at.
IMMUTABLE_ENTITIES = ("NurseLicense", "NurseShift", "ComplianceAuditRecord")
