"""Domain constants for the AI governance / model approval API.

Every value here is transcribed from the PRD's normative tables so that tests
assert against named constants instead of bare literals.
"""

# ─── Logical clock (PRD §2.5) ──────────────────────────────────────────────
# Before any client sets the clock it reads exactly this instant.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# ─── Pagination (PRD §2.3) ─────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────
ROLE_REQUESTER = "Requester"
ROLE_LEGAL = "LegalReviewer"
ROLE_PRIVACY = "PrivacyReviewer"
ROLE_SECURITY = "SecurityReviewer"
ROLE_BUSINESS = "BusinessReviewer"
ROLE_OFFICER = "GovernanceOfficer"

ALL_ROLES = [
    ROLE_REQUESTER,
    ROLE_LEGAL,
    ROLE_PRIVACY,
    ROLE_SECURITY,
    ROLE_BUSINESS,
    ROLE_OFFICER,
]

# Gate ownership: reviewer role ↔ gate type (PRD §2.1).
GATE_OWNER_ROLE = {
    "LEGAL": ROLE_LEGAL,
    "PRIVACY": ROLE_PRIVACY,
    "SECURITY": ROLE_SECURITY,
    "BUSINESS": ROLE_BUSINESS,
}

# The literal actor recorded on cascade-appended ledger rows and on a design
# superseded by a later filing (PRD §2.1).
SYSTEM_ACTOR = "system"

# ─── Risk classification scoring (PRD §3.2) ────────────────────────────────
INDIVIDUAL_IMPACT_POINTS = {
    "NONE": 0,
    "LOW": 10,
    "MATERIAL": 25,
    "CONSEQUENTIAL": 40,
}

DECISION_AUTONOMY_POINTS = {
    "ADVISORY": 0,
    "HUMAN_IN_LOOP": 8,
    "HUMAN_ON_LOOP": 18,
    "FULLY_AUTOMATED": 30,
}

DATA_SENSITIVITY_POINTS = {
    "PUBLIC": 0,
    "INTERNAL": 6,
    "CONFIDENTIAL": 14,
    "SPECIAL_CATEGORY": 24,
}

# Reach bands, evaluated in descending order (PRD §3.2).
REACH_BANDS = [(100000, 6), (10000, 4), (1000, 2)]
REACH_POINTS_BELOW_LOWEST_BAND = 0

# Only these jurisdictions carry scrutiny points (PRD §3.2).
HIGH_SCRUTINY_JURISDICTIONS = ["EU", "UK", "US_CO"]
POINTS_PER_HIGH_SCRUTINY_JURISDICTION = 3

ALL_JURISDICTIONS = ["EU", "UK", "US_CA", "US_CO", "US_FED"]

# Risk tier bands, evaluated in descending order (PRD §3.2).
TIER_BAND_PROHIBITED = 85
TIER_BAND_HIGH = 70
TIER_BAND_LIMITED = 35

RISK_SCORE_MIN = 0
RISK_SCORE_MAX = 100

FORCED_PROHIBITED_REJECTION_REASON = "PROHIBITED_COMBINATION"

# Gates opened per final band (PRD §3.2).
REQUIRED_GATES = {
    "MINIMAL": ["BUSINESS"],
    "LIMITED": ["PRIVACY", "BUSINESS"],
    "HIGH": ["LEGAL", "PRIVACY", "SECURITY", "BUSINESS"],
    "PROHIBITED": [],
}

# Canonical gate creation order (PRD §2.3).
CANONICAL_GATE_ORDER = ["LEGAL", "PRIVACY", "SECURITY", "BUSINESS"]

# ─── Control debt (PRD §3.3) ───────────────────────────────────────────────
GATE_WEIGHTS = {
    "LEGAL": 1.35,
    "PRIVACY": 1.25,
    "SECURITY": 1.15,
    "BUSINESS": 0.75,
}

TIER_DEBT_MULTIPLIERS = {
    "MINIMAL": 0.5,
    "LIMITED": 1.0,
    "HIGH": 1.5,
    "PROHIBITED": 2.0,
}

CONDITION_DEBT_DIVISOR = 3
MIN_CONDITIONS = 1
MAX_CONDITIONS = 20

# Gate statuses whose debt contributes to control_debt_index_total (PRD §2.11).
DEBT_BEARING_GATE_STATUSES = [
    "PENDING",
    "IN_REVIEW",
    "CONDITIONS_ISSUED",
    "CLEARED",
]

# ─── Vendor terms grading (PRD §3.1) ───────────────────────────────────────
PROVENANCE_POINTS = {
    "DOCUMENTED_LICENSED": 0,
    "DOCUMENTED_MIXED": 8,
    "UNDISCLOSED": 20,
}
UNDISCLOSED_PROVENANCE_SURCHARGE = 10

OUTPUT_RIGHTS_POINTS = {
    "FULL_ASSIGNMENT": 0,
    "LICENSE_WITH_RESTRICTIONS": 6,
    "VENDOR_RETAINS": 16,
}

# Retention bands, evaluated in ascending order of the upper bound (PRD §3.1).
RETENTION_BANDS = [(30, 0), (90, 5), (365, 10)]
RETENTION_POINTS_ABOVE_HIGHEST_BAND = 18

NO_OPT_OUT_POINTS = 6
UNDISCLOSED_SUBPROCESSORS_POINTS = 5

# Grade bands, evaluated in ascending order (PRD §3.1).
GRADE_BAND_A = 8
GRADE_BAND_B = 20
GRADE_BAND_C = 34

# Grading variants (PRD §3.1).
VARIANT_CONSERVATIVE = "CONSERVATIVE_LEGAL"
VARIANT_DOCUMENTED = "DOCUMENTED_TERMS"

# The retention figure the conservative variant substitutes (PRD §3.1).
CONSERVATIVE_RETENTION_DAYS = 3650

# Grades that permit an asset to be approved for use (PRD §3.1 / §4).
ASSET_APPROVABLE_GRADES = ["A", "B", "C"]

# ─── Oversight adequacy (PRD §3.5) ─────────────────────────────────────────
REVIEW_MODE_BASE = {
    "NONE": 0,
    "SAMPLED": 30,
    "PRE_DECISION_REVIEW": 70,
    "DUAL_REVIEW": 90,
}

SAMPLE_COMPONENT_CAP = 30
SAMPLE_COMPONENT_FACTOR = 0.3

SLA_COMPONENT_BASE = 20
SLA_COMPONENT_HOURS_PER_POINT = 6

OVERRIDE_CAPABILITY_POINTS = 10
ADEQUACY_SCORE_CAP = 100

MIN_SAMPLE_PCT = 0
MAX_SAMPLE_PCT = 100
MIN_ESCALATION_SLA_HOURS = 0
MAX_ESCALATION_SLA_HOURS = 240

# Required adequacy keyed (tier, decision_autonomy) (PRD §3.5).
REQUIRED_ADEQUACY = {
    ("HIGH", "ADVISORY"): 60,
    ("HIGH", "HUMAN_IN_LOOP"): 75,
    ("HIGH", "HUMAN_ON_LOOP"): 85,
    ("HIGH", "FULLY_AUTOMATED"): 95,
    ("LIMITED", "ADVISORY"): 45,
    ("LIMITED", "HUMAN_IN_LOOP"): 60,
    ("LIMITED", "HUMAN_ON_LOOP"): 70,
    ("LIMITED", "FULLY_AUTOMATED"): 80,
    ("MINIMAL", "ADVISORY"): 30,
    ("MINIMAL", "HUMAN_IN_LOOP"): 30,
    ("MINIMAL", "HUMAN_ON_LOOP"): 30,
    ("MINIMAL", "FULLY_AUTOMATED"): 30,
    ("PROHIBITED", "ADVISORY"): 100,
    ("PROHIBITED", "HUMAN_IN_LOOP"): 100,
    ("PROHIBITED", "HUMAN_ON_LOOP"): 100,
    ("PROHIBITED", "FULLY_AUTOMATED"): 100,
}

# ─── Test evaluations (PRD §3.4) ───────────────────────────────────────────
EVAL_TYPES = ["BIAS", "ROBUSTNESS", "HALLUCINATION", "SECURITY_REDTEAM"]

# Frozen threshold profile by provisional tier (PRD §3.4).
EVAL_THRESHOLDS = {
    "HIGH": {
        "BIAS": 0.80,
        "ROBUSTNESS": 0.90,
        "HALLUCINATION": 0.95,
        "SECURITY_REDTEAM": 0.95,
    },
    "LIMITED": {
        "BIAS": 0.70,
        "ROBUSTNESS": 0.80,
        "HALLUCINATION": 0.85,
        "SECURITY_REDTEAM": 0.85,
    },
    "MINIMAL": {
        "BIAS": 0.60,
        "ROBUSTNESS": 0.70,
        "HALLUCINATION": 0.75,
        "SECURITY_REDTEAM": 0.75,
    },
    "PROHIBITED": {
        "BIAS": 1.00,
        "ROBUSTNESS": 1.00,
        "HALLUCINATION": 1.00,
        "SECURITY_REDTEAM": 1.00,
    },
}

REQUIRED_SAMPLE_SIZE = {
    "MINIMAL": 100,
    "LIMITED": 300,
    "HIGH": 1000,
    "PROHIBITED": 1000,
}

REQUIRED_METRIC_NAME = {
    "BIAS": "worst_group_parity_ratio",
    "ROBUSTNESS": "adversarial_pass_rate",
    "HALLUCINATION": "grounded_accuracy",
    "SECURITY_REDTEAM": "adversarial_pass_rate",
}

# Metric comparisons are exact to four decimal places (PRD §2.7).
METRIC_DECIMAL_PLACES = 4

# Evaluations the approval consults per final tier (PRD §3.7).
REQUIRED_EVALS = {
    "MINIMAL": [],
    "LIMITED": ["BIAS"],
    "HIGH": ["BIAS", "ROBUSTNESS", "HALLUCINATION"],
    "PROHIBITED": [],
}

# The gate-side evaluation requirement is narrower (PRD §2.9 step 23).
SECURITY_GATE_REQUIRED_EVALS = ["SECURITY_REDTEAM"]

# ─── Approval arithmetic (PRD §3.7) ────────────────────────────────────────
CREDIT_PER_CLEARED_GATE = 3
CREDIT_PER_PASSED_EVAL = 2
CONTROL_CREDIT_CAP = 15

VENDOR_PENALTY_BY_GRADE = {"A": 0, "B": 5, "C": 12, "D": 25}
VENDOR_PENALTY_FIRST_PARTY = 0

REASSESSMENT_INTERVAL_DAYS = {"MINIMAL": 730, "LIMITED": 365, "HIGH": 180}

# Portfolio reach cap, consulted only when the final tier is HIGH (PRD §3.7).
PORTFOLIO_HIGH_TIER_REACH_CAP = 250000

REVOCATION_REASON_SUPERSEDED = "SUPERSEDED"

# ─── Monitoring incidents (PRD §3.8) ───────────────────────────────────────
INCIDENT_BASE_HOURS = {"SEV1": 4, "SEV2": 24, "SEV3": 72}

TIER_SPEED_FACTOR = {
    "MINIMAL": 1.5,
    "LIMITED": 1.0,
    "HIGH": 0.5,
    "PROHIBITED": 0.5,
}

# Incident statuses that still count against the monitoring posture (PRD §3.8).
UNRESOLVED_INCIDENT_STATUSES = ["OPEN", "ESCALATED"]

POSTURE_HEALTHY = "HEALTHY"
POSTURE_WATCH = "WATCH"
POSTURE_IMPAIRED = "IMPAIRED"

MAX_INCIDENT_SUMMARY_LENGTH = 1000

# ─── Shadow deployments (PRD §3.9) ─────────────────────────────────────────
SHADOW_BASE_GRACE_DAYS = {"SANDBOX": 30, "INTERNAL_PILOT": 14, "PRODUCTION": 7}

MIN_GRACE_DAYS = 1
MAX_GRACE_DAYS = 30

# ─── Reassessment (PRD §3.9) ───────────────────────────────────────────────
REASSESSMENT_OVERDUE_DAYS = 30

# ─── Use case statuses that count as inventory (PRD §2.11) ─────────────────
INVENTORY_STATUSES = ["APPROVED", "UNDER_REASSESSMENT", "SUSPENDED"]

# Terminal use case statuses (PRD §3.2).
TERMINAL_USE_CASE_STATUSES = ["REJECTED", "REVOKED"]

# ─── Disclosure notices (PRD §3.6) ─────────────────────────────────────────
DISCLOSURE_QUIET_BUFFER_DAYS = 7

NOTICE_TYPES = [
    "USER_FACING_AI_DISCLOSURE",
    "AUTOMATED_DECISION_NOTICE",
    "TRAINING_DATA_NOTICE",
    "EMPLOYMENT_SCREENING_NOTICE",
]

MIN_LOCALE_COUNT = 1

# ─── Intake field bounds (PRD §3.2) ────────────────────────────────────────
MAX_TITLE_LENGTH = 160
MAX_BUSINESS_UNIT_LENGTH = 40
MAX_DESCRIPTION_LENGTH = 2000

# ─── Ledger entry types (PRD §2.11) ────────────────────────────────────────
LEDGER_ENTRY_TYPES = [
    "APPROVAL_GRANTED",
    "APPROVAL_REVOKED",
    "APPROVAL_SUSPENDED",
    "APPROVAL_REINSTATED",
    "GATE_CLEARED",
    "GATE_REOPENED",
    "REASSESSMENT_COMPLETED",
    "BINDING_RETIRED",
    "VENDOR_ASSESSMENT_EXPIRED",
    "SHADOW_ENFORCED",
    "CLASSIFICATION_REJECTED",
    "DISCLOSURE_WITHDRAWN",
]

# ─── Binding supersession reasons (PRD §3.4) ───────────────────────────────
SUPERSEDED_BY_NEW_BINDING = "SUPERSEDED_BY_NEW_BINDING"
SUPERSEDED_USE_CASE_REVOKED = "USE_CASE_REVOKED"
SUPERSEDED_APPROVAL_SUSPENDED = "APPROVAL_SUSPENDED"
SUPERSEDED_ASSET_REAPPROVED = "ASSET_REAPPROVED"

# Binding statuses that count toward an asset's active_binding_count (PRD §2.10).
ACTIVE_BINDING_STATUSES = ["PINNED", "STALE"]

# ─── Asset attributes (PRD §3.1) ───────────────────────────────────────────
HOSTING_KINDS = ["INTERNAL", "VENDOR_API", "ON_PREM"]
MODALITIES = ["TEXT", "VISION", "MULTIMODAL", "TABULAR"]

# ─── Rounding (PRD §2.7) ───────────────────────────────────────────────────
# Currency-free 2dp quantities (control debt) tolerate no drift beyond a cent.
DEBT_TOLERANCE = 0.005
METRIC_TOLERANCE = 0.00005
