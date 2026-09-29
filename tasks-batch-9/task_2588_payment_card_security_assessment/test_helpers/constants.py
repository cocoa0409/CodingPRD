"""Domain constants for the payment-card security assessment API.

Every literal here is taken from the PRD: role names, enum vocabularies, the
logical-clock default, the fee ladder, the requirement risk-point table and the
canonical actor identities used across the test suite.
"""

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_LEAD_ASSESSOR = "LeadAssessor"
ROLE_ASSESSOR = "Assessor"
ROLE_QA_REVIEWER = "QaReviewer"
ROLE_ASV_VENDOR = "AsvVendor"
ROLE_CLIENT_REPRESENTATIVE = "ClientRepresentative"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = [
    ROLE_LEAD_ASSESSOR,
    ROLE_ASSESSOR,
    ROLE_QA_REVIEWER,
    ROLE_ASV_VENDOR,
    ROLE_CLIENT_REPRESENTATIVE,
    ROLE_PLATFORM_ADMIN,
]

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
DEFAULT_OFFSET = 0
MAX_LIMIT = 100

# ---------------------------------------------------------------------------
# Enum vocabularies
# ---------------------------------------------------------------------------
MERCHANT_LEVELS = ["L1", "L2", "L3", "L4"]

ASSESSOR_STATUSES = ["ACTIVE", "SUSPENDED"]
CERTIFICATION_STATUSES = ["ACTIVE", "LAPSED"]
VENDOR_APPROVAL_STATUSES = ["APPROVED", "REVOKED"]
VENDOR_EFFECTIVE_APPROVALS = ["APPROVED", "EXPIRED", "REVOKED"]

ENGAGEMENT_STATUSES = [
    "SCOPING",
    "FIELDWORK",
    "REPORTING",
    "ATTESTED",
    "SUBMITTED",
    "REASSESSMENT_PLANNED",
]
POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]

SEGMENT_CLASSES = ["CDE", "CONNECTED", "OUT_OF_SCOPE"]
SEGMENTATION_STATUSES = ["DECLARED", "TEST_PLANNED", "VALIDATED", "FAILED", "WITHDRAWN"]
TEST_METHODS = ["PEN_TEST", "CONFIG_REVIEW", "TRAFFIC_ANALYSIS"]

COMPONENT_TYPES = [
    "SERVER",
    "NETWORK_DEVICE",
    "POS_TERMINAL",
    "APPLICATION",
    "DATABASE",
]
# The pinned stratum order the sampling allocation walks (PRD 3.5).
STRATUM_ORDER = [
    "SERVER",
    "NETWORK_DEVICE",
    "POS_TERMINAL",
    "APPLICATION",
    "DATABASE",
]
FUNCTION_CLASSES = [
    "PAYMENT_APPLICATION",
    "DATA_STORE",
    "SECURITY_SERVICE",
    "CONNECTED_SUPPORT",
    "SEGMENTATION_CONTROL",
]
FACILITY_TYPES = ["DATA_CENTER", "CALL_CENTER", "RETAIL_STORE", "OFFICE"]

PLAN_VARIANTS = ["PRELIMINARY", "FINAL"]
PLAN_STATUSES = ["ACTIVE", "STALE", "SUPERSEDED"]

REQUIREMENT_FAMILIES = [
    "R1",
    "R2",
    "R3",
    "R4",
    "R5",
    "R6",
    "R7",
    "R8",
    "R9",
    "R10",
    "R11",
    "R12",
]
APPLICABILITIES = ["APPLICABLE", "NOT_APPLICABLE"]
TEST_STATUSES = [
    "NOT_STARTED",
    "IN_TESTING",
    "IN_PLACE",
    "IN_PLACE_WITH_CCW",
    "NOT_IN_PLACE",
    "NOT_TESTED",
    "NOT_APPLICABLE",
]
REMEDIATION_STATUSES = ["NONE", "GAP_OPEN", "GAP_REMEDIATED", "GAP_ACCEPTED_CCW"]

EVIDENCE_TYPES = ["DOCUMENT_REVIEW", "INTERVIEW", "OBSERVATION", "SYSTEM_CONFIG"]
# Coverage is reported in this declared order (PRD 3.6).
EVIDENCE_TYPE_ORDER = ["DOCUMENT_REVIEW", "INTERVIEW", "OBSERVATION", "SYSTEM_CONFIG"]
# The three techniques evidence completeness insists on (PRD 3.6).
COMPLETENESS_REQUIRED_TYPES = ["DOCUMENT_REVIEW", "INTERVIEW", "OBSERVATION"]
SUFFICIENCIES = ["SUFFICIENT", "INSUFFICIENT"]

CCW_STATUSES = ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED"]
CCW_DECISIONS = ["ACCEPT", "REJECT"]

REMEDIATION_ITEM_STATUSES = [
    "OPEN",
    "IN_PROGRESS",
    "RETEST_PASSED",
    "RETEST_FAILED",
    "CLOSED_BY_CCW",
]
REMEDIATION_SOURCES = [
    "REQUIREMENT_CONCLUSION",
    "REQUIREMENT_REOPEN",
    "SCAN_FINDING_REJECTED",
]
SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]

ROC_STATUSES = [
    "DRAFTING",
    "IN_QA",
    "QA_APPROVED",
    "QA_REJECTED",
    "ATTESTED",
    "SUBMITTED",
]
ROC_DECISIONS = ["APPROVE", "REJECT"]
COMPLIANCE_RESULTS = ["COMPLIANT", "NON_COMPLIANT"]
SUBMISSION_TARGETS = ["ACQUIRER", "CARD_BRAND"]

SCAN_CYCLE_STATUSES = ["SCHEDULED", "PASSING", "FAILING", "DISPUTE_OPEN"]
SEVERITY_CLASSES = ["HIGH_OR_ABOVE", "LOW"]
DISPUTE_STATUSES = ["NONE", "DISPUTED", "ACCEPTED_FALSE_POSITIVE", "REJECTED"]

CHANGE_TYPES = [
    "COMPONENT_ADDED_TO_CDE",
    "SEGMENT_RECLASSIFIED",
    "THIRD_PARTY_ADDED",
    "APPLICATION_UPDATED",
    "STAFF_CHANGE",
]
# Only these three change types can trigger a reassessment (PRD 3.9).
REASSESSMENT_TRIGGERING_CHANGE_TYPES = [
    "COMPONENT_ADDED_TO_CDE",
    "SEGMENT_RECLASSIFIED",
    "THIRD_PARTY_ADDED",
]

# ---------------------------------------------------------------------------
# Fee derivation (PRD 3.5)
# ---------------------------------------------------------------------------
BASE_HOURS = 160
HOURS_PER_SAMPLED_COMPONENT = 12
HOURS_PER_SAMPLED_FACILITY = 30
HOURS_PER_ACCEPTED_CCW = 20
HOURLY_RATE = 250.00
L1_SURCHARGE_RATE = 0.08
VOLUME_TIERS = [(120000.00, 0.10), (90000.00, 0.06), (60000.00, 0.03)]

# ---------------------------------------------------------------------------
# Sampling (PRD 3.5)
# ---------------------------------------------------------------------------
COMPONENT_SAMPLE_RATE = 0.25
COMPONENT_SAMPLE_FLOOR = 2
FACILITY_SAMPLE_RATE = 0.34
FACILITY_SAMPLE_FLOOR = 1
COVERAGE_RATIO_PRECISION = 4

# ---------------------------------------------------------------------------
# Requirement risk points and severity mapping (PRD 3.6, 3.7)
# ---------------------------------------------------------------------------
RISK_POINTS = {
    "R1": 3,
    "R2": 2,
    "R3": 5,
    "R4": 4,
    "R5": 2,
    "R6": 4,
    "R7": 3,
    "R8": 3,
    "R9": 2,
    "R10": 4,
    "R11": 3,
    "R12": 1,
}


def severity_for_risk_points(risk_points: int) -> str:
    """Map a requirement family's risk points onto a remediation severity."""
    if risk_points >= 5:
        return "CRITICAL"
    if risk_points == 4:
        return "HIGH"
    if risk_points == 3:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Compensating control worksheet rigor (PRD 3.7)
# ---------------------------------------------------------------------------
CONTROL_DEPTH_POINTS_PER_REF = 20
CONTROL_DEPTH_CAP = 100
RIGOR_DEPTH_WEIGHT = 0.40
RIGOR_MONITORING_WEIGHT = 0.35
RIGOR_RISK_OFFSET_WEIGHT = 0.25
THIN_CONTROL_CAP = 40.00
RIGOR_ACCEPT_THRESHOLD = 70.00
CCW_MAX_MONITORING_INTERVAL_DAYS = 30

# ---------------------------------------------------------------------------
# Scanning (PRD 3.9)
# ---------------------------------------------------------------------------
SCAN_WINDOW_DAYS = 90
HIGH_SEVERITY_CVSS_THRESHOLD = 4.0

# ---------------------------------------------------------------------------
# Reassessment (PRD 3.9)
# ---------------------------------------------------------------------------
REASSESSMENT_CHANGE_THRESHOLD = 3
REASSESSMENT_CHANGE_DAYS = 90
SUBMISSION_REASSESSMENT_DAYS = 365

# ---------------------------------------------------------------------------
# Canonical actors used by the fixtures
# ---------------------------------------------------------------------------
LEAD_NAME = "Dana Reyes"
LEAD_EMAIL = "dana.reyes@qsa.example"
LEAD_CERT_EXPIRES = "2027-06-30T00:00:00Z"

QA_NAME = "Kim Vance"
QA_EMAIL = "kim.vance@qsa.example"
QA_CERT_EXPIRES = "2027-06-30T00:00:00Z"

SECOND_LEAD_NAME = "Owen Marsh"
SECOND_LEAD_EMAIL = "owen.marsh@qsa.example"

VENDOR_NAME = "Northstar ASV"
VENDOR_APPROVAL_EXPIRES = "2027-12-31T00:00:00Z"

CLIENT_LEGAL_NAME = "Northwind Retail Inc"
ACQUIRER_NAME = "First Coast Bank"
ASSESSMENT_YEAR = 2026
FIELDWORK_START = "2026-08-10"
FIELDWORK_END = "2026-08-28"
APPROVED_BUDGET = 200000.00

FACILITY_DC_EAST = "DC-EAST"
FACILITY_DC_WEST = "DC-WEST"
FACILITY_DC_SOUTH = "DC-SOUTH"
FACILITY_RETAIL_12 = "RETAIL-12"
FACILITY_RETAIL_40 = "RETAIL-40"
