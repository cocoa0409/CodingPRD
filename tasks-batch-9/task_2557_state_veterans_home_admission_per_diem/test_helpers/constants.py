"""Domain constants for the State Veterans Home admission and per diem API.

Every value here is transcribed from the PRD: role names, enum members, tunable
policy constants and the fixed instant at which the logical clock starts.
"""

API_PREFIX = "/svh"

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_STATE_PROGRAM_ADMIN = "StateProgramAdmin"
ROLE_ADMISSIONS_COORDINATOR = "AdmissionsCoordinator"
ROLE_CLINICAL_ASSESSOR = "ClinicalAssessor"
ROLE_BUSINESS_OFFICE_MANAGER = "BusinessOfficeManager"
ROLE_FEDERAL_PER_DIEM_AUDITOR = "FederalPerDiemAuditor"
ROLE_SURVEY_AGENCY = "SurveyAgency"
ROLE_RESIDENT_REPRESENTATIVE = "ResidentRepresentative"

ALL_ROLES = [
    ROLE_STATE_PROGRAM_ADMIN,
    ROLE_ADMISSIONS_COORDINATOR,
    ROLE_CLINICAL_ASSESSOR,
    ROLE_BUSINESS_OFFICE_MANAGER,
    ROLE_FEDERAL_PER_DIEM_AUDITOR,
    ROLE_SURVEY_AGENCY,
    ROLE_RESIDENT_REPRESENTATIVE,
]

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
RECOGNITION_STATUSES = ["RECOGNIZED", "PROVISIONAL", "SUSPENDED"]
RECOGNITION_ACTIONS = ["GRANT", "SUSPEND", "RESTORE"]
CARE_LEVELS = ["NURSING", "DOMICILIARY", "ADULT_DAY_HEALTH"]
CERTIFICATION_STATUSES = ["CERTIFIED", "CONDITIONAL", "DECERTIFIED"]
OPERATIONAL_POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
DISCHARGE_CHARACTERS = [
    "HONORABLE",
    "GENERAL",
    "OTHER_THAN_HONORABLE",
    "BAD_CONDUCT",
    "DISHONORABLE",
]
APPLICANT_STATUSES = [
    "SUBMITTED",
    "ELIGIBLE",
    "INELIGIBLE",
    "WAITLISTED",
    "ADMITTED",
    "DENIED",
]
PRIORITY_CLASSES = ["CLASS_1", "CLASS_2", "CLASS_3", "CLASS_4"]
ELIGIBILITY_REASON_CODES = [
    "ELIGIBLE",
    "DISCHARGE_CHARACTER_DISQUALIFYING",
    "SERVICE_DAYS_INSUFFICIENT",
    "RESIDENCY_INSUFFICIENT",
]
WAITLIST_STATUSES = ["ACTIVE", "OFFERED", "ADMITTED", "EXPIRED", "CANCELLED"]
ASSESSMENT_STATUSES = ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"]
OCCUPANCY_STATUSES = ["ADMITTED", "HOSPITALIZED", "DISCHARGED"]
BILLING_STATUSES = [
    "PROVISIONAL_COST_SHARE",
    "FINAL_COST_SHARE",
    "CLOSED",
]
DISCHARGE_REASONS = [
    "DEATH",
    "TRANSFER_OUT",
    "VOLUNTARY",
    "ADMINISTRATIVE",
    "BED_HOLD_EXPIRED",
]
INCOME_TYPES = [
    "SSA",
    "VA_PENSION",
    "VA_COMPENSATION",
    "MILITARY_RETIREMENT",
    "OTHER",
]
VERIFICATION_STATUSES = ["UNVERIFIED", "VERIFIED", "REJECTED"]
VERIFICATION_DECISIONS = ["VERIFIED", "REJECTED"]
COST_SHARE_VARIANTS = ["PROVISIONAL", "FINAL"]
COST_SHARE_TIERS = ["TIER_1", "TIER_2", "TIER_3"]
CARE_PLAN_STATUSES = ["DRAFT", "ACTIVE", "REVIEW_DUE", "SUPERSEDED", "VOID"]
ADL_SUPPORT_LEVELS = ["LOW", "MODERATE", "HIGH"]
CENSUS_CLASSES = ["RESIDENT_DAY", "BED_HOLD_DAY", "ABSENT_DAY"]
CLAIM_BASES = ["CENSUS_BASIS", "AUDITED_BASIS"]
CLAIM_STATUSES = ["DRAFT", "SUBMITTED", "PAID", "REJECTED", "VOID"]
REJECTION_CODES = [
    "CENSUS_MISMATCH",
    "RECOGNITION_LAPSE",
    "DUPLICATE_PERIOD",
]
ASSESSMENT_REJECTION_REASONS = ["ADMISSION_DENIED"]
TRUST_TXN_TYPES = [
    "DEPOSIT",
    "WITHDRAWAL",
    "PNA_CREDIT",
    "COST_SHARE_DEBIT",
    "REVERSAL",
]
SURVEY_SCOPES = ["ISOLATED", "PATTERN", "WIDESPREAD"]
SURVEY_SEVERITIES = [
    "MINIMAL",
    "MINIMAL_HARM",
    "ACTUAL_HARM",
    "IMMEDIATE_JEOPARDY",
]
ADJUDICATION_OUTCOMES = ["PAID", "REJECTED"]
RECOGNITION_SUSPENSION_REASONS = ["UNIT_DECERTIFIED"]

# ---------------------------------------------------------------------------
# Eligibility and priority scoring (PRD 3.2, 3.3)
# ---------------------------------------------------------------------------
WARTIME_MIN_SERVICE_DAYS = 90
PEACETIME_MIN_SERVICE_DAYS = 181
DISQUALIFYING_DISCHARGES = ["BAD_CONDUCT", "DISHONORABLE"]
MIN_STATE_RESIDENCY_YEARS = 1
MAX_REDETERMINATIONS = 2

CLASS_1_DISABILITY_PCT_THRESHOLD = 70
CLASS_2_RESIDENCY_YEARS_THRESHOLD = 5
CLASS_3_RESIDENCY_YEARS_THRESHOLD = 2

CLASS_BASE_POINTS = {
    "CLASS_1": 1000,
    "CLASS_2": 700,
    "CLASS_3": 400,
    "CLASS_4": 100,
}
DISABILITY_POINTS_PER_PCT = 3
DISABILITY_POINTS_CAP = 100
RESIDENCY_POINTS_PER_YEAR = 5
RESIDENCY_POINTS_CAP_YEARS = 20
ADL_POINTS_PER_DEPENDENCY = 20
ADL_DEPENDENCY_CAP = 6
COGNITIVE_IMPAIRMENT_POINTS = 40
BEHAVIORAL_RISK_POINTS = -30
TENURE_POINTS_PER_DAY = 1
TENURE_POINTS_CAP_DAYS = 365
DECLINED_OFFER_PENALTY_POINTS = 25

OFFER_WINDOW_DAYS = 7
MAX_DECLINED_OFFERS = 3

# ---------------------------------------------------------------------------
# Clinical assessment and care plans (PRD 3.4, 3.5)
# ---------------------------------------------------------------------------
NURSING_MIN_SKILLED_HOURS = 2.00
CARE_PLAN_REVIEW_DAYS = 90

# ---------------------------------------------------------------------------
# Bed holds (PRD 3.6)
# ---------------------------------------------------------------------------
BED_HOLD_MAX_DAYS = 30

# ---------------------------------------------------------------------------
# Cost share waterfall (PRD 3.7)
# ---------------------------------------------------------------------------
COUNTABLE_RATE_BPS = {
    "SSA": 10000,
    "VA_PENSION": 0,
    "VA_COMPENSATION": 8000,
    "MILITARY_RETIREMENT": 10000,
    "OTHER": 10000,
}
COST_SHARE_TIER_BOUNDS_CENTS = [100000, 250000]
COST_SHARE_TIER_BPS = [4000, 5500, 7000]
MEDICAL_CAP_BY_TIER_CENTS = {"TIER_1": 5000, "TIER_2": 15000, "TIER_3": 30000}
FEDERAL_OFFSET_SHARE_BPS = 500
FEDERAL_OFFSET_CAP_BPS = 3000
DEFAULT_PNA_MONTHLY_CENTS = 9000

# ---------------------------------------------------------------------------
# Survey scoring and certification (PRD 3.8)
# ---------------------------------------------------------------------------
SCOPE_WEIGHT = {"ISOLATED": 1, "PATTERN": 2, "WIDESPREAD": 4}
SEVERITY_WEIGHT = {
    "MINIMAL": 1,
    "MINIMAL_HARM": 3,
    "ACTUAL_HARM": 8,
    "IMMEDIATE_JEOPARDY": 20,
}
CERTIFICATION_CONDITIONAL_THRESHOLD = 1
CERTIFICATION_DECERTIFY_THRESHOLD = 25

# ---------------------------------------------------------------------------
# Per diem claims (PRD 2.9, 3.10)
# ---------------------------------------------------------------------------
PER_DIEM_RATE_CENTS = {
    "NURSING": 11857,
    "DOMICILIARY": 5502,
    "ADULT_DAY_HEALTH": 4230,
}
BED_HOLD_RATE_BPS = 5000
BED_HOLD_PAYABLE_DAYS_PER_MONTH = 10
