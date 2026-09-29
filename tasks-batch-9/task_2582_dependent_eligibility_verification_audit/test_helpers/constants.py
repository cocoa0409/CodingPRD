"""Domain constants: roles, enum member sets, the cost schedule and the
thresholds every calculation in the specification is driven from.
"""
from __future__ import annotations

from typing import Dict, Tuple

# ------------------------------------------------------------------------- roles
PROGRAM_ADMIN = "ProgramAdmin"
VERIFICATION_ANALYST = "VerificationAnalyst"
APPEAL_REVIEWER = "AppealReviewer"
RECOVERY_AGENT = "RecoveryAgent"
EMPLOYEE = "Employee"

ALL_ROLES: Tuple[str, ...] = (
    PROGRAM_ADMIN,
    VERIFICATION_ANALYST,
    APPEAL_REVIEWER,
    RECOVERY_AGENT,
    EMPLOYEE,
)
OPERATOR_ROLES: Tuple[str, ...] = (
    PROGRAM_ADMIN,
    VERIFICATION_ANALYST,
    APPEAL_REVIEWER,
    RECOVERY_AGENT,
)

# ------------------------------------------------------------------ the logical clock
CLOCK_ORIGIN = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------- enum members
COVERAGE_TIERS: Tuple[str, ...] = (
    "EMPLOYEE_ONLY",
    "EMPLOYEE_SPOUSE",
    "EMPLOYEE_CHILDREN",
    "FAMILY",
)

RELATIONSHIP_TYPES: Tuple[str, ...] = (
    "SPOUSE",
    "DOMESTIC_PARTNER",
    "CHILD_BIOLOGICAL",
    "STEPCHILD",
    "ADOPTED_CHILD",
    "DISABLED_ADULT_CHILD",
    "LEGAL_GUARDIANSHIP",
)

PROOF_TYPES: Tuple[str, ...] = (
    "MARRIAGE_CERTIFICATE",
    "JOINT_TAX_RETURN",
    "JOINT_ACCOUNT_STATEMENT",
    "DOMESTIC_PARTNER_AFFIDAVIT",
    "SHARED_RESIDENCE_PROOF",
    "BIRTH_CERTIFICATE",
    "ADOPTION_DECREE",
    "COURT_ORDER",
    "DISABILITY_CERTIFICATION",
    "TAX_DEPENDENCY_PROOF",
)

# The four document classes designated sensitive; every other class is standard.
SENSITIVE_PROOF_TYPES: Tuple[str, ...] = (
    "JOINT_TAX_RETURN",
    "JOINT_ACCOUNT_STATEMENT",
    "DISABILITY_CERTIFICATION",
    "TAX_DEPENDENCY_PROOF",
)

# Exactly two document classes are recency-scoped.
RECENCY_SCOPED_PROOF_TYPES: Tuple[str, ...] = (
    "JOINT_TAX_RETURN",
    "JOINT_ACCOUNT_STATEMENT",
)

DECISION_REASON_CODES: Tuple[str, ...] = (
    "VERIFIED_MATCH",
    "ILLEGIBLE",
    "EXPIRED_DOCUMENT",
    "WRONG_DEPENDENT",
    "INSUFFICIENT_PROOF",
)

AMNESTY_REASON_CODES: Tuple[str, ...] = (
    "NO_LONGER_ELIGIBLE",
    "DIVORCE_FINALIZED",
    "AGE_LIMIT_EXCEEDED",
    "DOCUMENTATION_UNAVAILABLE",
    "OTHER",
)

APPEAL_GROUNDS: Tuple[str, ...] = (
    "DOMESTIC_PARTNERSHIP_AFFIDAVIT",
    "CUSTODY_ARRANGEMENT",
    "DOCUMENT_UNAVAILABLE",
    "ADMINISTRATIVE_ERROR",
)

CUSTODY_ELIGIBLE_RELATIONSHIPS: Tuple[str, ...] = (
    "CHILD_BIOLOGICAL",
    "STEPCHILD",
    "ADOPTED_CHILD",
    "LEGAL_GUARDIANSHIP",
)

SENSITIVE_RELATIONSHIPS: Tuple[str, ...] = (
    "DOMESTIC_PARTNER",
    "STEPCHILD",
    "LEGAL_GUARDIANSHIP",
)

CHANNELS: Tuple[str, ...] = ("EMAIL", "MAIL", "PORTAL")
COMMUNICATION_KINDS: Tuple[str, ...] = (
    "ANNOUNCEMENT",
    "REMINDER",
    "AMNESTY_CONFIRMATION",
    "TERMINATION_NOTICE",
    "RESCISSION_NOTICE",
)
SCOPE_TYPES: Tuple[str, ...] = ("FULL_CENSUS", "TARGETED", "NEW_DEPENDENT_ONLY")
PHASES: Tuple[str, ...] = ("AUDIT", "POINT_OF_ENROLLMENT")
PROVIDER_TYPES: Tuple[str, ...] = ("MEDICAL", "DENTAL", "VISION", "PHARMACY")
RECOVERY_VARIANTS: Tuple[str, ...] = ("STRICT", "EQUITABLE")
SAVINGS_VARIANTS: Tuple[str, ...] = ("PROVISIONAL", "AUDITED")
NOTICE_ORIGINS: Tuple[str, ...] = ("AUDIT_ESCALATION", "POE_LAPSE")

# ------------------------------------------------------------- program defaults
DEFAULT_AMNESTY_DAYS = 21
DEFAULT_RESPONSE_DAYS = 45
DEFAULT_REMINDER_MIN_GAP_DAYS = 7
DEFAULT_MAX_REMINDERS = 3
DEFAULT_POE_VERIFICATION_ENABLED = True
DEFAULT_REQUIRES_RECENCY_DAYS = 365
DEFAULT_AFFIDAVIT_ALLOWED = False
DEFAULT_AUTO_TERMINATE_ON_LAPSE = False

# ------------------------------------------------ the published monthly cost schedule
MONTHLY_COST_CENTS: Dict[str, int] = {
    "SPOUSE": 49713,
    "DOMESTIC_PARTNER": 49713,
    "CHILD_BIOLOGICAL": 30500,
    "STEPCHILD": 30500,
    "ADOPTED_CHILD": 30500,
    "DISABLED_ADULT_CHILD": 36238,
    "LEGAL_GUARDIANSHIP": 30500,
}

# --------------------------------------- the three-component continuation cost table
CONTINUATION_COMPONENTS: Dict[str, Dict[str, int]] = {
    "SPOUSE": {"medical": 45125, "dental": 3313, "vision": 1275},
    "DOMESTIC_PARTNER": {"medical": 45125, "dental": 3313, "vision": 1275},
    "CHILD_BIOLOGICAL": {"medical": 27450, "dental": 2137, "vision": 913},
    "STEPCHILD": {"medical": 27450, "dental": 2137, "vision": 913},
    "ADOPTED_CHILD": {"medical": 27450, "dental": 2137, "vision": 913},
    "LEGAL_GUARDIANSHIP": {"medical": 27450, "dental": 2137, "vision": 913},
    "DISABLED_ADULT_CHILD": {"medical": 33188, "dental": 2137, "vision": 913},
}
CONTINUATION_LOAD_FACTOR = 1.02
CONTINUATION_ELECTION_DAYS = 60
CONTINUATION_MONTHS = 18

# ------------------------------------------------------------------ fiscal thresholds
TERMINATION_GRACE_DAYS = 14
APPEAL_WINDOW_DAYS = 30
MAX_APPEAL_ROUNDS = 2
DE_MINIMIS_RECOVERY_CENTS = 25000

ADMIN_FEE_TIER_MID_FLOOR = 100000
ADMIN_FEE_TIER_HIGH_FLOOR = 500000
ADMIN_FEE_PCT_LOW = 0.00
ADMIN_FEE_PCT_MID = 0.05
ADMIN_FEE_PCT_HIGH = 0.08

# --------------------------------------------------- priority score weights and cap
PRIORITY_WEIGHT_UNVERIFIED = 40
PRIORITY_WEIGHT_SENSITIVE = 25
PRIORITY_WEIGHT_REMINDER = 20
PRIORITY_WEIGHT_SILENCE = 15
PRIORITY_SCORE_CEILING = 100

# ------------------------------------------------------------- documentation classes
# Proof types that satisfy each relationship class in the fixtures below.
DEFAULT_PROOF_TYPE: Dict[str, str] = {
    "SPOUSE": "MARRIAGE_CERTIFICATE",
    "DOMESTIC_PARTNER": "DOMESTIC_PARTNER_AFFIDAVIT",
    "CHILD_BIOLOGICAL": "BIRTH_CERTIFICATE",
    "STEPCHILD": "BIRTH_CERTIFICATE",
    "ADOPTED_CHILD": "ADOPTION_DECREE",
    "DISABLED_ADULT_CHILD": "DISABILITY_CERTIFICATION",
    "LEGAL_GUARDIANSHIP": "COURT_ORDER",
}
