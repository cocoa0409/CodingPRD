"""Domain constants for the Pentest Assurance API test suite.

Every literal here is transcribed from the product requirements document so the
tests can assert exact server-computed values without re-deriving them inline.
"""

API_PREFIX = "/pentest"
CLOCK_PATH = "/_clock/set_current_utc"

# ---------------------------------------------------------------------------
# Role names, spelled exactly as the service expects them.
# ---------------------------------------------------------------------------
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_PROGRAM_MANAGER = "ProgramManager"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_TESTER = "Tester"
ROLE_REMEDIATION_OWNER = "RemediationOwner"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_PROGRAM_MANAGER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_TESTER,
    ROLE_REMEDIATION_OWNER,
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
ASSET_CLASSES = ("APPLICATION", "NETWORK", "CLOUD")
COMPLIANCE_REGIMES = ("PCI_DSS", "HIPAA", "SOX", "SOC2", "FEDRAMP")
EXPOSURE_STATES = ("MONITORED", "ELEVATED", "CLEARED")

PRIORITIZATION_MODES = ("RISK_DRIVEN", "COMPLIANCE_DRIVEN")
PLAN_STATUSES = ("DRAFT", "ACTIVE", "CLOSED")

SCOPE_ITEM_STATUSES = ("PROPOSED", "APPROVED", "DEFERRED", "WITHDRAWN", "CONSUMED")
SCOPE_DECISIONS = ("APPROVE", "DEFER", "WITHDRAW")

ENGAGEMENT_TYPES = ("APPLICATION_TEST", "NETWORK_TEST", "CLOUD_REVIEW")
EXECUTION_STATES = ("PLANNED", "EXECUTING", "FIELDWORK_COMPLETE", "REPORTED", "CLOSED")
AUTHORIZATION_STATES = ("ROE_PENDING", "AUTHORIZED", "SUSPENDED", "TERMINATED")
EXECUTION_ACTIONS = ("START", "COMPLETE_FIELDWORK", "REPORT", "CLOSE")
STOP_CODES = ("PAUSE", "TERMINATE")

ROE_STATUSES = ("DRAFT", "SIGNED", "SUSPENDED", "REVOKED")
TECHNIQUES = (
    "SQLI",
    "XSS",
    "AUTHZ_BYPASS",
    "PHISHING",
    "LATERAL_MOVEMENT",
    "IAM_ESCALATION",
    "DOS",
)

TARGET_STATES = ("ACTIVE", "EXCLUDED", "SUSPENDED")

CERTIFICATIONS = ("OSCP", "GPEN", "CREST", "CISSP")
BACKGROUND_CHECK_STATUSES = ("PENDING", "CLEARED", "FLAGGED", "EXPIRED")
BACKGROUND_CHECK_RESULTS = ("CLEARED", "FLAGGED", "EXPIRED")
AVAILABILITY_STATES = ("PENDING_CLEARANCE", "AVAILABLE", "ASSIGNED", "SUSPENDED")

ASSIGNMENT_ROLES = ("LEAD", "MEMBER")
ACCESS_STATES = ("REQUESTED", "PROVISIONED", "REVOKED")
ACCESS_ACTIONS = ("PROVISION", "REVOKE")

EXPOSURE_CLASSES = ("INTERNAL", "PARTNER", "INTERNET")
ROOT_CAUSE_THEMES = (
    "INPUT_VALIDATION",
    "ACCESS_CONTROL",
    "CRYPTO_MISCONFIG",
    "PATCH_MANAGEMENT",
    "SECRETS_HANDLING",
    "CLOUD_IAM",
)
SEVERITY_BANDS = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
FINDING_STATUSES = (
    "REPORTED",
    "TRIAGED",
    "RISK_ACCEPTED",
    "REMEDIATION_ASSIGNED",
    "REMEDIATION_SUBMITTED",
    "RETEST_PASSED",
    "RETEST_FAILED",
    "CLOSED",
    "DUPLICATE",
)
TRIAGE_ACTIONS = ("ACCEPT", "MARK_DUPLICATE", "RISK_ACCEPT", "REVOKE_RISK_ACCEPTANCE")

ALERT_STATES = ("RAISED", "ACKNOWLEDGED", "ESCALATED")
DUPLICATE_CONTAINMENT_TEXT = "DUPLICATE_OF_PRIOR_FINDING"

VALIDATION_REQUIREMENTS = ("RETEST_REQUIRED", "EVIDENCE_ONLY")
REMEDIATION_STATUSES = (
    "ASSIGNED",
    "SUBMITTED",
    "VALIDATED",
    "PARTIALLY_VALIDATED",
    "REJECTED",
    "CLOSED",
)

RETEST_OUTCOMES = ("PASS", "FAIL", "PARTIAL")
RETEST_STATES = ("VERIFIED", "SIGNED_OFF", "SUPERSEDED")

URGENCY_BANDS = ("MANDATORY", "RECOMMENDED")

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Instants used repeatedly across the programme timeline under test.
T_PROGRAMME_OPEN = "2026-09-01T00:00:00Z"
T_BEFORE_ASSIGNMENT = "2026-09-07T08:00:00Z"
T_INTERVAL_START = "2026-09-07T09:00:00Z"
T_FIELDWORK_DAY = "2026-09-08T10:00:00Z"

WINDOW_START = "2026-09-05T00:00:00Z"
WINDOW_END = "2026-09-30T23:59:59Z"
INTERVAL_START = "2026-09-07T09:00:00Z"
INTERVAL_END = "2026-09-14T09:00:00Z"
CLEARANCE_EXPIRY = "2027-01-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Scope candidate scoring (§3.2)
# ---------------------------------------------------------------------------
TIER_POINTS = {1: 100, 2: 75, 3: 50, 4: 25}
REGIME_POINTS_PER_REGIME = 40
REGIME_POINTS_CAP = 100
STALENESS_POINTS_WHEN_NEVER_TESTED = 100
STALENESS_DAYS_DIVISOR = 365
STALENESS_POINTS_CAP = 100

RISK_DRIVEN_WEIGHTS = {
    "exposure": 0.45,
    "tier": 0.30,
    "staleness": 0.20,
    "regime": 0.05,
}
COMPLIANCE_DRIVEN_WEIGHTS = {
    "exposure": 0.20,
    "tier": 0.25,
    "staleness": 0.15,
    "regime": 0.40,
}

# ---------------------------------------------------------------------------
# Coverage gate (§3.3)
# ---------------------------------------------------------------------------
COVERAGE_TIERS = (1, 2)
COVERAGE_MIN_PCT = 60.0
COVERAGE_WHEN_NO_ELIGIBLE_ASSET = 100.00

# ---------------------------------------------------------------------------
# Authorized target cooldown (§3.4)
# ---------------------------------------------------------------------------
COOLDOWN_HOURS = {"APPLICATION": 0, "NETWORK": 24, "CLOUD": 12}

# ---------------------------------------------------------------------------
# Tester qualification (§3.1) and the lead gate (§3.5)
# ---------------------------------------------------------------------------
CERT_POINTS = {"OSCP": 45, "GPEN": 35, "CREST": 25, "CISSP": 15}
QUALIFICATION_SCORE_CAP = 100
LEAD_MIN_QUALIFICATION_SCORE = 60
DEFAULT_MAX_CONCURRENT_ENGAGEMENTS = 2

# ---------------------------------------------------------------------------
# Finding severity rating (§3.6)
# ---------------------------------------------------------------------------
EXPOSURE_MULTIPLIER = {"INTERNAL": 0.95, "PARTNER": 1.00, "INTERNET": 1.15}
TIER_BONUS = {1: 0.50, 2: 0.30, 3: 0.10, 4: 0.00}
REGIME_BONUS_PER_REGIME = 0.20
REGIME_BONUS_CAP = 0.60
SEVERITY_SCORE_CAP = 10.00
SEVERITY_BAND_FLOORS = (("CRITICAL", 9.00), ("HIGH", 7.00), ("MEDIUM", 4.00))
SEVERITY_POINTS = {"CRITICAL": 40, "HIGH": 20, "MEDIUM": 8, "LOW": 2}

# ---------------------------------------------------------------------------
# Critical alert acknowledgement deadlines (§3.6)
# ---------------------------------------------------------------------------
ACK_DEADLINE_MINUTES = {"INTERNET": 60, "PARTNER": 240, "INTERNAL": 240}
ESCALATION_LEVEL_ON_TIME = 1
ESCALATION_LEVEL_LATE = 2

# ---------------------------------------------------------------------------
# Remediation due dates (§3.8)
# ---------------------------------------------------------------------------
SEVERITY_SLA_DAYS = {"CRITICAL": 7, "HIGH": 30, "MEDIUM": 60, "LOW": 120}
REGIME_SLA_CAP_DAYS = {
    "FEDRAMP": 21,
    "PCI_DSS": 30,
    "HIPAA": 45,
    "SOX": 60,
    "SOC2": 90,
}
PARTIAL_GRACE_DAYS = 14
MAX_EXTENSIONS = 2

# ---------------------------------------------------------------------------
# Engagement assurance scoring (§3.9)
# ---------------------------------------------------------------------------
ASSURANCE_BASE_SCORE = 100.00
ASSURANCE_DEDUCTION = {"CRITICAL": 25, "HIGH": 12, "MEDIUM": 5, "LOW": 1}
RETEST_CREDIT_PER_CLOSURE = 5
RETEST_CREDIT_CAP = 20

# ---------------------------------------------------------------------------
# Training priority scoring (§3.9)
# ---------------------------------------------------------------------------
TRAINING_SEVERITY_WEIGHT = {"CRITICAL": 5.00, "HIGH": 3.00, "MEDIUM": 1.20, "LOW": 0.40}
RECENCY_WINDOW_DAYS = 90
RECENCY_DECAY_SLOPE = 0.60
RECENCY_MULTIPLIER_FLOOR = 0.40
TRAINING_SCORE_CAP = 20.00
MANDATORY_MIN_RECURRENCE = 3
MANDATORY_MIN_SCORE = 8.00

# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------
SCORE_TOLERANCE = 0.01
