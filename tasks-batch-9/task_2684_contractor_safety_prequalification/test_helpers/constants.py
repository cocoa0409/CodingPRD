"""Business constants for the contractor safety prequalification API.

Every value here is quoted from the PRD so that tests never hard-code a
magic number without a traceable origin.
"""

# --- Logical clock -----------------------------------------------------------

# "At startup the logical clock is 2026-08-01T00:00:00Z."
INITIAL_CLOCK = "2026-08-01T00:00:00Z"

# --- Roles -------------------------------------------------------------------

ROLE_NETWORK_ADMIN = "NetworkAdmin"
ROLE_CONTRACTOR_ADMIN = "ContractorAdmin"
ROLE_CLIENT_SAFETY_MANAGER = "ClientSafetyManager"
ROLE_VERIFICATION_ANALYST = "VerificationAnalyst"

ALL_ROLES = [
    ROLE_NETWORK_ADMIN,
    ROLE_CONTRACTOR_ADMIN,
    ROLE_CLIENT_SAFETY_MANAGER,
    ROLE_VERIFICATION_ANALYST,
]

# --- Enumerations ------------------------------------------------------------

GRADING_POLICIES = ["STRICT", "BALANCED"]
COVERAGE_TYPES = ["GL", "WC", "AUTO", "UMBRELLA"]
HAZARD_CLASSES = [
    "GENERAL",
    "HEIGHTS",
    "CONFINED_SPACE",
    "ELECTRICAL",
    "HOT_WORK",
    "EXCAVATION",
]
HIGH_HAZARD_CLASSES = [
    "HEIGHTS",
    "CONFINED_SPACE",
    "ELECTRICAL",
    "HOT_WORK",
    "EXCAVATION",
]
TRADE_CODES = [
    "GENERAL_BUILDING",
    "ELECTRICAL_TRADE",
    "MECHANICAL_TRADE",
    "SCAFFOLDING",
    "ROOFING",
    "EARTHWORK",
]
QUALIFICATION_CODES = [
    "OSHA10",
    "OSHA30",
    "FALL_PROTECTION_COMPETENT",
    "CONFINED_SPACE_ENTRANT",
    "LOTO_AUTHORIZED",
    "HOT_WORK_PERMIT",
    "EXCAVATION_COMPETENT",
]
PROGRAM_TYPES = [
    "HAZCOM",
    "DISCIPLINE_POLICY",
    "FALL_PROTECTION",
    "CONFINED_SPACE",
    "LOTO",
    "HOT_WORK",
    "EXCAVATION",
]
GRADES = ["A", "B", "C", "F"]
PREQUALIFICATION_STATUSES = [
    "DRAFT",
    "SUBMITTED",
    "UNDER_REVIEW",
    "APPROVED",
    "CONDITIONAL",
    "REJECTED",
    "SUSPENDED",
    "EXPIRED",
]
STATISTICS_DIMENSION_STATES = ["NOT_SUBMITTED", "PENDING", "VERIFIED", "REJECTED"]
DOCUMENT_DIMENSION_STATES = ["NOT_STARTED", "IN_PROGRESS", "COMPLETE", "DEFICIENT"]
AUDIT_STATES = ["NOT_SELECTED", "SELECTED", "PASSED", "FAILED"]
PROGRAM_REVIEW_STATUSES = ["SUBMITTED", "ACCEPTED", "DEFICIENT", "WAIVED"]
CERTIFICATE_VERIFICATION_STATUSES = ["PENDING", "VERIFIED", "REJECTED"]
CERTIFICATE_LIFECYCLE_STATUSES = [
    "NOT_YET_EFFECTIVE",
    "CURRENT",
    "EXPIRING_SOON",
    "LAPSED",
    "SUPERSEDED",
]
IMPROVEMENT_PLAN_STATUSES = ["OPEN", "SUBMITTED", "ACCEPTED", "REJECTED", "OVERDUE"]
VARIANCE_STATUSES = ["REQUESTED", "APPROVED", "DENIED"]
VARIANCE_REQUIREMENT_CODES = ["TRIR", "DART", "EMR", "CITATION_POINTS", "HAZARD_CLASS"]
GRANT_STATUSES = ["GRANTED", "REVOKED", "EXPIRED"]
REVOCATION_REASONS = [
    "CLIENT_REVOKED",
    "PREQUAL_SUSPENDED",
    "PREQUAL_REJECTED",
    "PREQUAL_EXPIRED",
]
SEVERITIES = ["FIRST_AID", "RECORDABLE", "LOST_TIME", "FATALITY"]
INCIDENT_REVIEW_STATUSES = ["OPEN", "CLOSED"]
SUBCONTRACTOR_LINK_STATUSES = ["ACTIVE", "TERMINATED"]
FLOW_DOWN_STATUSES = ["PENDING", "SATISFIED", "DEFICIENT"]
SITE_GATE_STATUSES = ["OPEN", "RESTRICTED", "LOCKED"]

# --- Client published defaults ----------------------------------------------

CLIENT_DEFAULTS = {
    "grading_policy": "BALANCED",
    "max_trir": 3.00,
    "max_dart_rate": 1.50,
    "max_emr": 1.00,
    "max_citation_points": 6,
    "weight_trir": 0.40,
    "weight_dart": 0.25,
    "weight_emr": 0.25,
    "weight_citation": 0.10,
    "conditional_band_pct": 20,
    "requalification_interval_months": 12,
    "audit_sample_rate_pct": 25,
    "cascade_depth_limit": 2,
    "required_coverage_types": ["GL", "WC"],
}

DEFAULT_SITE_MIN_GRADE = "C"

# --- Pagination --------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Scoring and normalization ----------------------------------------------

TRIR_BASIS_HOURS = 200000
CITATION_POINT_WEIGHTS = {"willful": 5, "serious": 2, "other": 1}

RATE_PRECISION = 4
SCORE_PRECISION = 2

BALANCED_BANDS = {"A": 85.00, "B": 70.00, "C": 55.00}
STRICT_BANDS = {"A": 90.00, "B": 78.00, "C": 66.00}
GRADE_RANK = {"F": 0, "C": 1, "B": 2, "A": 3}
MAX_GRADE_RANK = 3

TIGHTENING_BY_TIER = {1: 1.00, 2: 0.85, 3: 0.70}
PROVISIONAL_TIGHTENING = 1.00
MAX_HAZARD_TIER = 3

SEVERITY_RANK = {"FIRST_AID": 1, "RECORDABLE": 2, "LOST_TIME": 3, "FATALITY": 4}
TIER_ESCALATION_SEVERITY_RANK = 3
INCIDENT_LOOKBACK_DAYS = 365

METRIC_ORDER = ["TRIR", "DART", "EMR", "CITATION_POINTS"]
COMPOSITE_CONDITIONAL_CODE = "COMPOSITE_C"
COMPOSITE_REJECTED_CODE = "COMPOSITE_F"
AUDIT_SAMPLING_CODE = "AUDIT_SAMPLING"

CONDITIONAL_CURE_DAYS = 90

# --- Insurance ---------------------------------------------------------------

PER_OCCURRENCE_FLOORS = {
    "GL": 1000000,
    "WC": 500000,
    "AUTO": 1000000,
    "UMBRELLA": 2000000,
}
AGGREGATE_FLOORS = {
    "GL": 2000000,
    "WC": 1000000,
    "AUTO": 1000000,
    "UMBRELLA": 4000000,
}
TIER_COVERAGE_MULTIPLIER = {1: 1.0, 2: 1.5}
DEPLETION_PER_OPEN_SEVERE_INCIDENT = 250000
FLOW_DOWN_GL_PER_OCCURRENCE_FLOOR = 500000

EXPIRING_SOON_DAYS = 30
SECONDS_PER_DAY = 86400

# --- Gate --------------------------------------------------------------------

ACCESS_COOLDOWN_HOURS = 24

HAZARD_REQUIRED_PROGRAMS = {
    "GENERAL": ["HAZCOM", "DISCIPLINE_POLICY"],
    "HEIGHTS": ["FALL_PROTECTION"],
    "CONFINED_SPACE": ["CONFINED_SPACE"],
    "ELECTRICAL": ["LOTO"],
    "HOT_WORK": ["HOT_WORK"],
    "EXCAVATION": ["EXCAVATION"],
}

HAZARD_REQUIRED_QUALIFICATIONS = {
    "GENERAL": ["OSHA10"],
    "HEIGHTS": ["OSHA30", "FALL_PROTECTION_COMPETENT"],
    "CONFINED_SPACE": ["OSHA30", "CONFINED_SPACE_ENTRANT"],
    "ELECTRICAL": ["OSHA30", "LOTO_AUTHORIZED"],
    "HOT_WORK": ["OSHA10", "HOT_WORK_PERMIT"],
    "EXCAVATION": ["OSHA30", "EXCAVATION_COMPETENT"],
}

# --- Canonical scenario literals --------------------------------------------

CANONICAL_CLIENT_NAME = "Northwind Facilities"
# "an `industry_code` that must be exactly six digits"
CANONICAL_INDUSTRY_CODE = "236220"
ALTERNATE_INDUSTRY_CODE = "236210"
CANONICAL_SITE_CODE = "PLANT-7"
CANONICAL_CONTRACTOR_NAME = "Acme Mechanical"
CANONICAL_CARRIER = "Ironclad Mutual"
ALTERNATE_CARRIER = "Harbor Casualty"

ANALYST_INSURANCE = "analyst-ins-1"
ANALYST_STATISTICS = "analyst-stat-1"
NETWORK_ADMIN_USER = "network-admin-1"

CANONICAL_CERT_EFFECTIVE = "2026-07-01T00:00:00Z"
CANONICAL_CERT_EXPIRATION = "2027-07-01T00:00:00Z"

CANONICAL_STATISTIC = {
    "reporting_year": 2025,
    "hours_worked": 500000,
    "recordable_incidents": 2,
    "dart_cases": 1,
    "fatalities": 0,
    "emr": 0.80,
    "citation_count_willful": 0,
    "citation_count_serious": 0,
    "citation_count_other": 1,
    "source_document_ref": "OSHA300A-2025",
}
