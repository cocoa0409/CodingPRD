"""Domain constants for the School-Based Health Center API.

Every value here traces to PRD.md section 2/3 prose or to SCAFFOLD.yaml
domain_constants.  Nothing in this module is configurable at runtime.
"""

API_PREFIX = "/sbhc"

# --------------------------------------------------------------------------
# Clock and academic calendar (PRD 2.5)
# --------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00.000Z"

SCHOOL_YEARS = {
    "2025-2026": {
        "start_date": "2025-08-01",
        "end_date": "2026-07-31",
        "end_instant": "2026-07-31T23:59:59.000Z",
    },
    "2026-2027": {
        "start_date": "2026-08-01",
        "end_date": "2027-07-31",
        "end_instant": "2027-07-31T23:59:59.000Z",
    },
}
SUPPORTED_SCHOOL_YEARS = ["2025-2026", "2026-2027"]

# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
ROLES = [
    "SbhcAdmin",
    "Registrar",
    "Clinician",
    "CareCoordinator",
    "BillingSpecialist",
    "Guardian",
    "Student",
]

# --------------------------------------------------------------------------
# Consent (PRD 3.4)
# --------------------------------------------------------------------------
SELF_CONSENT_MIN_AGE_YEARS = 14
SELF_CONSENTABLE_CATEGORIES = ["BEHAVIORAL_HEALTH", "CONFIDENTIAL_SERVICES"]
CONSENT_CATEGORIES = [
    "GENERAL_TREATMENT",
    "BEHAVIORAL_HEALTH",
    "CONFIDENTIAL_SERVICES",
    "DENTAL",
    "TELEHEALTH",
]
GRANTED_BY_VALUES = ["GUARDIAN", "STUDENT_SELF"]
CONSENT_STATUSES = ["ACTIVE", "REVOKED", "EXPIRED", "SUPERSEDED"]

# --------------------------------------------------------------------------
# Enrollment (PRD 3.3)
# --------------------------------------------------------------------------
MAX_ENROLLMENT_REINSTATEMENTS = 2
ENROLLMENT_STATUSES = ["PENDING", "ACTIVE", "WITHDRAWN", "TRANSFERRED"]

# --------------------------------------------------------------------------
# Immunization (PRD 3.7)
# --------------------------------------------------------------------------
REQUIRED_SERIES = ["HEPB", "MMR"]
SERIES_REQUIRED_DOSES = {"HEPB": 3, "MMR": 2}
SERIES_DOSE1_MIN_AGE_DAYS = {"HEPB": 0, "MMR": 365}
# interval to the predecessor dose, keyed by (series, dose_number)
SERIES_INTERVAL_DAYS = {
    ("HEPB", 2): 28,
    ("HEPB", 3): 56,
    ("MMR", 2): 28,
}
IMMUNIZATION_GRACE_DAYS = 4
PROVISIONAL_WINDOW_DAYS = 30
DOSE_STATUSES = ["VALID", "INVALID_TOO_EARLY", "VOIDED"]
EXEMPTION_TYPES = ["NONE", "MEDICAL", "RELIGIOUS"]
COMPLIANCE_STATUSES = ["COMPLIANT", "PROVISIONAL", "NON_COMPLIANT"]

# --------------------------------------------------------------------------
# Screening bands (PRD 3.8)
# --------------------------------------------------------------------------
VISION_REFER_DENOMINATOR_MIN = 40
HEARING_REFER_DB_EXCLUSIVE = 25
DENTAL_REFER_CARIES_MIN = 1
BMI_REFER_PERCENTILE_LOW_EXCLUSIVE = 5
BMI_REFER_PERCENTILE_HIGH_INCLUSIVE = 95
BEHAVIORAL_REFER_SCORE_MIN = 10

SCREENING_INSTRUMENTS = ["VISION", "HEARING", "DENTAL", "BMI", "BEHAVIORAL"]
SCREENING_OUTCOMES = ["PASS", "REFER"]
SCREENING_STATUSES = ["RECORDED", "CLOSED_PASS", "REFERRED"]
INSTRUMENT_TO_SPECIALTY = {
    "VISION": "OPHTHALMOLOGY",
    "HEARING": "AUDIOLOGY",
    "DENTAL": "DENTISTRY",
    "BMI": "NUTRITION",
    "BEHAVIORAL": "BEHAVIORAL_HEALTH",
}

# --------------------------------------------------------------------------
# Sports clearance (PRD 3.9)
# --------------------------------------------------------------------------
CLEARANCE_VALIDITY_DAYS = {
    "CLEARED": 365,
    "CLEARED_WITH_RESTRICTIONS": 180,
    "DEFERRED": None,
    "NOT_CLEARED": None,
}
DEFERRAL_REEVALUATION_WINDOW_DAYS = 30
MAX_DEFERRAL_REEVALUATIONS = 2
CLEARANCE_OUTCOMES = [
    "CLEARED",
    "CLEARED_WITH_RESTRICTIONS",
    "DEFERRED",
    "NOT_CLEARED",
]
CLEARANCE_STATUSES = [
    "ACTIVE",
    "PENDING_REEVALUATION",
    "VOIDED",
    "EXPIRED",
    "SUPERSEDED",
]

# --------------------------------------------------------------------------
# Referral (PRD 3.8)
# --------------------------------------------------------------------------
MAX_OUTREACH_ATTEMPTS = 3
REFERRAL_SPECIALTIES = [
    "OPHTHALMOLOGY",
    "AUDIOLOGY",
    "DENTISTRY",
    "BEHAVIORAL_HEALTH",
    "PRIMARY_CARE",
    "NUTRITION",
]
REFERRAL_STATUSES = [
    "OPEN",
    "OUTREACH_IN_PROGRESS",
    "SCHEDULED",
    "REPORT_RECEIVED",
    "CLOSED",
    "LOST_TO_FOLLOW_UP",
]
OUTREACH_OUTCOMES = ["REACHED", "NO_ANSWER"]

# --------------------------------------------------------------------------
# Notification (PRD 3.11)
# --------------------------------------------------------------------------
MAX_NOTIFICATION_DELIVERY_ATTEMPTS = 3
NOTIFICATION_ACK_WINDOW_DAYS = 14
NOTIFICATION_EVENT_TYPES = [
    "VISIT_COMPLETED",
    "CLEARANCE_DETERMINED",
    "CLEARANCE_VOIDED",
    "REFERRAL_CREATED",
    "IMMUNIZATION_NON_COMPLIANT",
]
NOTIFICATION_STATUSES = [
    "QUEUED",
    "SENT",
    "ACKNOWLEDGED",
    "FAILED",
    "UNDELIVERABLE",
    "SUPPRESSED_CONFIDENTIAL",
    "SUPPRESSED_OPT_OUT",
]
DELIVERY_OUTCOMES = ["DELIVERED", "FAILED"]

# --------------------------------------------------------------------------
# Telehealth (PRD 3.6)
# --------------------------------------------------------------------------
TELEHEALTH_TURNAROUND_BUFFER_MINUTES = 15
TELEHEALTH_MIN_DURATION_MINUTES = 15
TELEHEALTH_MAX_DURATION_MINUTES = 60
MAX_SESSION_RESCHEDULES = 2
DEFAULT_TELEHEALTH_CONCURRENT_CAPACITY = 1
MIN_TELEHEALTH_CONCURRENT_CAPACITY = 1
MAX_TELEHEALTH_CONCURRENT_CAPACITY = 4
SESSION_STATUSES = ["SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED"]
SESSION_CLOSE_OUTCOMES = ["NO_SHOW", "CANCELLED"]

# --------------------------------------------------------------------------
# Visit (PRD 3.5)
# --------------------------------------------------------------------------
NO_SHOW_GRACE_MINUTES = 10
VISIT_TYPES = ["ACUTE", "BEHAVIORAL", "DENTAL", "SPORTS_PHYSICAL"]
DELIVERY_MODES = ["IN_PERSON", "TELEHEALTH"]
DISPOSITIONS = [
    "TREATED_RETURNED_TO_CLASS",
    "TREATED_SENT_HOME",
    "REFERRED_OUT",
    "NO_TREATMENT_NEEDED",
]
VISIT_CLINICAL_STATUSES = [
    "SCHEDULED",
    "IN_PROGRESS",
    "COMPLETED",
    "CANCELLED",
    "NO_SHOW",
]
VISIT_BILLING_STATUSES = [
    "NOT_APPLICABLE",
    "PENDING_CHARGES",
    "CHARGES_POSTED",
    "REVERSED",
]
CLOSE_UNFULFILLED_OUTCOMES = ["CANCELLED", "NO_SHOW"]

VISIT_TYPE_TO_CLINICIAN_DISCIPLINE = {
    "ACUTE": "MEDICAL",
    "BEHAVIORAL": "BEHAVIORAL",
    "DENTAL": "DENTAL",
    "SPORTS_PHYSICAL": "MEDICAL",
}
CLINICIAN_DISCIPLINES = ["MEDICAL", "BEHAVIORAL", "DENTAL"]

VISIT_TYPE_TO_SERVICE_CATEGORY = {
    "ACUTE": "ACUTE_OFFICE_VISIT",
    "BEHAVIORAL": "BEHAVIORAL_THERAPY",
    "DENTAL": "DENTAL_PREVENTIVE",
    "SPORTS_PHYSICAL": "SPORTS_PHYSICAL_EXAM",
}

# --------------------------------------------------------------------------
# Sliding fee / billing (PRD 2.8, 3.10)
# --------------------------------------------------------------------------
FPL_BASE_ANNUAL_CENTS = 1560000
FPL_INCREMENT_PER_ADDITIONAL_PERSON_CENTS = 550000
TIER_A_MAX_FPL_PERCENT = "100.00"
TIER_B_MAX_FPL_PERCENT = "138.00"
TIER_C_MAX_FPL_PERCENT = "175.00"
TIER_D_MAX_FPL_PERCENT = "200.00"
DISCOUNT_PCT = {
    "TIER_A": "1.00",
    "TIER_B": "0.80",
    "TIER_C": "0.60",
    "TIER_D": "0.40",
    "TIER_E": "0.00",
}
DISCOUNT_TIERS = ["TIER_A", "TIER_B", "TIER_C", "TIER_D", "TIER_E"]
NOMINAL_FEE_FLOOR_CENTS = 500
PRIVATE_COPAY_CENTS = 2500
MAX_CLAIM_APPEALS = 2
PAYER_ROUTES = ["MEDICAID", "PRIVATE_INSURANCE", "SELF_PAY"]

FEE_SCHEDULE = {
    "ACUTE_OFFICE_VISIT": 12000,
    "BEHAVIORAL_THERAPY": 15000,
    "DENTAL_PREVENTIVE": 9000,
    "SPORTS_PHYSICAL_EXAM": 5000,
    "IMMUNIZATION_ADMIN": 3000,
    "TELEHEALTH_ENCOUNTER": 11000,
}
NO_CHARGE_SERVICE_CATEGORIES = ["IMMUNIZATION_ADMIN"]
SERVICE_CATEGORIES = list(FEE_SCHEDULE.keys())

CHARGE_STATUSES = [
    "PENDING",
    "NO_CHARGE",
    "CLAIM_SUBMITTED",
    "CLAIM_DENIED",
    "CLAIM_APPEALED",
    "PAID",
    "WRITTEN_OFF",
    "REVERSED",
]
TERMINAL_CHARGE_STATUSES = {"NO_CHARGE", "PAID", "WRITTEN_OFF", "REVERSED"}
ADJUDICATION_OUTCOMES = ["PAID", "DENIED"]

# --------------------------------------------------------------------------
# Reporting (PRD 3.12)
# --------------------------------------------------------------------------
REPORT_RATE_PRECISION_DP = 4
MONEY_PRECISION_DP = 0

# --------------------------------------------------------------------------
# Miscellaneous enums
# --------------------------------------------------------------------------
GUARDIAN_RELATIONSHIPS = ["MOTHER", "FATHER", "LEGAL_GUARDIAN", "OTHER"]
PROGRAM_STATUSES = ["ACTIVE", "SUSPENDED"]

# Pagination (PRD 2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
