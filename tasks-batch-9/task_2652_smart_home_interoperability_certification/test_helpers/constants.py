"""Domain constants for the Smart Home Interoperability Certification API.

Every value here is taken from the PRD: the fee tables of the certification-fee
computation, the readiness and competency weights, the penalty bands, the
validation ranges and the logical-clock defaults.
"""

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_MEMBER = "Member"
ROLE_TEST_LABORATORY = "TestLaboratory"
ROLE_CONFORMANCE_REVIEWER = "ConformanceReviewer"
ROLE_SECURITY_REVIEWER = "SecurityReviewer"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_PUBLIC_VIEWER = "PublicViewer"

ALL_ROLES = [
    ROLE_PROGRAM_ADMIN,
    ROLE_MEMBER,
    ROLE_TEST_LABORATORY,
    ROLE_CONFORMANCE_REVIEWER,
    ROLE_SECURITY_REVIEWER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PUBLIC_VIEWER,
]

# The literal recorded in place of a user identifier when the server itself
# performs a write as part of a cascade.
SYSTEM_USER_ID = "SYSTEM"

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00.000Z"
# Every design recipe repositions the clock here before doing anything else.
CLOCK_PROGRAMME_START = "2026-09-01T00:00:00Z"
SECONDS_PER_DAY = 86400

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

DEVICE_TYPES = ["LIGHTING", "THERMOSTAT", "LOCK", "SENSOR", "HUB"]
OBLIGATIONS = ["MANDATORY", "OPTIONAL", "CONDITIONAL"]
SECURITY_BASELINE_LEVELS = ["SB1", "SB2", "SB3"]
MEMBER_TIERS = ["ADOPTER", "PARTICIPANT", "PROMOTER"]
REVIEW_TRACKS = ["STANDARD", "EXPEDITED"]
SESSION_TYPES = ["INTEROP", "SECURITY"]
RESULT_OUTCOMES = ["PASS", "FAIL", "BLOCKED", "WAIVED"]
FIRMWARE_CAPABILITIES = ["OTA_SIGNED", "OTA_UNSIGNED", "NONE"]
IP_COMMITMENT_TYPES = ["RAND_ROYALTY_FREE", "RAND_ROYALTY_BEARING"]
CASE_CATEGORIES = [
    "INTEROP_DEFECT",
    "SECURITY_DEFECT",
    "FALSE_FEATURE_DECLARATION",
    "IP_WITHDRAWAL",
]
CASE_DISPOSITIONS = [
    "ESCALATE",
    "ORDER_REMEDIATION",
    "ORDER_WITHDRAWAL",
    "CONFIRM_REMEDIATION",
]
ACCREDITATION_DECISIONS = ["AUTHORIZE", "SUSPEND", "REINSTATE", "REVOKE"]
TOOL_ACCESS_DECISIONS = ["GRANT", "REVOKE"]
REVIEW_DECISIONS = ["APPROVE", "REJECT"]
PLUGFEST_OUTCOMES = ["PASS", "FAIL"]

CREDIT_LEDGER_VARIANTS = ["AVAILABLE", "COMMITTED"]
COMPETENCY_VARIANTS = ["ROLLING_90D", "LIFETIME"]
READINESS_VARIANTS = ["PROVISIONAL", "FINAL"]

# ---------------------------------------------------------------------------
# Specification / feature-set ranges
# ---------------------------------------------------------------------------

VERSION_LABEL_MIN_LEN = 1
VERSION_LABEL_MAX_LEN = 32
FEATURE_CODE_MIN_LEN = 1
FEATURE_CODE_MAX_LEN = 48
TEST_CASE_COUNT_MIN = 1
TEST_CASE_COUNT_MAX = 500
MIN_PLUGFEST_CREDITS_MIN = 0
MIN_PLUGFEST_CREDITS_MAX = 4

# ---------------------------------------------------------------------------
# Member / credit ranges
# ---------------------------------------------------------------------------

LEGAL_NAME_MAX_LEN = 120
CREDIT_PURCHASE_MIN_CENTS = 1000
CREDIT_PURCHASE_MAX_CENTS = 100000000

# ---------------------------------------------------------------------------
# Laboratory ranges and bench arithmetic
# ---------------------------------------------------------------------------

LAB_NAME_MAX_LEN = 120
BENCH_CAPACITY_MIN = 1
BENCH_CAPACITY_MAX = 32
MINUTES_PER_BENCH_PER_CYCLE = 600
BENCH_CHANGEOVER_MINUTES = 60
COMPETENCY_SUSPENSION_THRESHOLD = 70.00
COMPETENCY_PUNCTUALITY_WEIGHT = 60
COMPETENCY_DISPUTE_FREE_WEIGHT = 40
ROLLING_WINDOW_DAYS = 90

# ---------------------------------------------------------------------------
# Certification fee
# ---------------------------------------------------------------------------

BASE_FEE_CENTS = {
    "SENSOR": 100000,
    "LIGHTING": 120000,
    "THERMOSTAT": 180000,
    "LOCK": 240000,
    "HUB": 300000,
}
FEE_PER_DECLARED_FEATURE_CENTS = 15000
SECURITY_BASELINE_SURCHARGE_CENTS = {"SB1": 0, "SB2": 50000, "SB3": 125000}
TIER_DISCOUNT_RATE = {"ADOPTER": 0.00, "PARTICIPANT": 0.10, "PROMOTER": 0.25}
REVIEW_TRACK_MULTIPLIER = {"STANDARD": 1.00, "EXPEDITED": 1.40}

# ---------------------------------------------------------------------------
# Readiness score
# ---------------------------------------------------------------------------

READINESS_WEIGHT_MANDATORY = 50
READINESS_WEIGHT_OPTIONAL = 20
READINESS_WEIGHT_INTEROP = 15
READINESS_WEIGHT_TIMELINESS = 15
READINESS_APPROVAL_THRESHOLD = 65.00
INTEROP_CREDIT_TARGET = 2
PROVISIONAL_PASS_SET = ["PASS", "WAIVED", "BLOCKED"]
FINAL_PASS_SET = ["PASS", "WAIVED"]

# ---------------------------------------------------------------------------
# Review cycle
# ---------------------------------------------------------------------------

MAX_REVISION_ROUNDS = 2

# ---------------------------------------------------------------------------
# Listing / recertification
# ---------------------------------------------------------------------------

LISTING_REFERENCE_PREFIX = "LST-"
RECERT_FULL_DAYS = 30
RECERT_DELTA_DAYS = 90
SPECIFICATION_DEPRECATED_RECERT_DAYS = 180

# ---------------------------------------------------------------------------
# Noncompliance penalty assessment
# ---------------------------------------------------------------------------

PENALTY_BAND_1_UNITS = 100
PENALTY_BAND_1_RATE_CENTS = 500
PENALTY_BAND_2_UNITS = 900
PENALTY_BAND_2_RATE_CENTS = 300
PENALTY_BAND_3_RATE_CENTS = 150
PENALTY_CAP_CENTS = 5000000
CATEGORY_SURCHARGE_RATE = {
    "INTEROP_DEFECT": 0.10,
    "SECURITY_DEFECT": 0.35,
    "FALSE_FEATURE_DECLARATION": 0.25,
    "IP_WITHDRAWAL": 0.00,
}
CLAIMED_IMPACT_UNITS_MAX = 10000000
REMEDIATION_DAYS_MIN = 1
REMEDIATION_DAYS_MAX = 365
AUTO_OPENED_EVIDENCE_SUMMARY = "Auto-opened: IP commitment withdrawn by member"

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# A syntactically valid UUID that never resolves to a stored row.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
