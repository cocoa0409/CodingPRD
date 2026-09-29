"""Domain constants, taken verbatim from PRD.md §2/§3 and SCAFFOLD.yaml §1.3."""
from decimal import Decimal

# ---- roles (PRD §2.1) -------------------------------------------------------
ROLE_APPLICANT = "Applicant"
ROLE_ANALYST = "LicensingAnalyst"
ROLE_EVALUATOR = "Evaluator"
ROLE_DEPUTY = "BoardDeputy"
ROLE_ADMIN = "AgencyAdmin"
ALL_ROLES = (ROLE_APPLICANT, ROLE_ANALYST, ROLE_EVALUATOR, ROLE_DEPUTY, ROLE_ADMIN)

# ---- enums ------------------------------------------------------------------
MILITARY_STATUSES = ("NONE", "SERVICE_MEMBER", "MILITARY_SPOUSE", "VETERAN")
MILITARY_ELIGIBLE = ("SERVICE_MEMBER", "MILITARY_SPOUSE", "VETERAN")
CREDENTIAL_STATUSES = ("ACTIVE", "LAPSED", "SUSPENDED", "REVOKED")
PATHWAYS = ("ENDORSEMENT", "UNIVERSAL_RECOGNITION", "MILITARY_SPOUSE_EXPEDITED")
APPLICATION_STATUSES = (
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "DEFICIENT",
    "SUSPENDED_REVIEW", "APPROVED", "DENIED",
)
REVIEWABLE_STATUSES = ("SUBMITTED", "UNDER_REVIEW", "DEFICIENT")
LIVE_APPLICATION_STATUSES = (
    "SUBMITTED", "UNDER_REVIEW", "DEFICIENT", "SUSPENDED_REVIEW", "APPROVED",
)
SCOPE_REVIEW_STATUSES = ("PENDING", "EQUIVALENT", "DEFICIENT_SCOPE")
SCOPE_REVIEW_DECISIONS = ("EQUIVALENT", "DEFICIENT_SCOPE")
DISCIPLINE_REVIEW_STATUSES = ("PENDING", "CLEAR", "ADVERSE")
DISCIPLINE_FINDINGS = ("CLEAR", "ADVERSE")
EVALUATION_OVERALL_STATUSES = ("IN_PROGRESS", "COMPLETE")
EVALUATION_VARIANTS = ("STRICT_SCOPE", "UNIVERSAL_RECOGNITION")
TRAINING_CATEGORIES = ("MOS_TRAINING", "FIELD_EXPERIENCE", "JOINT_SERVICE_TRANSCRIPT")
CREDIT_AWARD_STATUSES = ("AWARDED", "REVOKED")
PERMIT_STATUSES = ("ACTIVE", "CONVERTED", "EXPIRED", "REVOKED")
LICENSE_STATUSES = ("ACTIVE",)
SOURCE_DATABASES = ("NPDB", "NURSYS", "STATE_BOARD_DIRECT")
SEVERITIES = ("ADVISORY", "PROBATION", "SUSPENSION", "REVOCATION")
LEDGER_ENTRY_TYPES = (
    "ASSESSMENT", "WAIVER_CREDIT", "PAYMENT", "EXAM_FEE_REVERSAL",
    "PERMIT_FEE", "PERMIT_FEE_REVERSAL", "CONVERSION_CREDIT",
)
EVALUATOR_STATUSES = ("ACTIVE", "INACTIVE")
ASSIGNMENT_STATUSES = ("ASSIGNED", "COMPLETED", "RELEASED")
EXAM_KINDS = ("NATIONAL", "JURISPRUDENCE")
DECISIONS = ("APPROVE", "DENY")

# ---- ledger memos (PRD §2.10) ----------------------------------------------
MEMOS = {
    "ASSESSMENT": "submit assessment",
    "WAIVER_CREDIT": "statutory waiver credit",
    "PAYMENT": "applicant payment",
    "EXAM_FEE_REVERSAL": "exam fee reversal",
    "PERMIT_FEE": "permit fee",
    "PERMIT_FEE_REVERSAL": "permit fee reversal",
    "CONVERSION_CREDIT": "permit conversion credit",
}

# ---- substantial_equivalency_score -----------------------------------------
W_SCOPE = Decimal("0.60")
W_HOURS = Decimal("0.25")
W_STANDING = Decimal("0.15")
CRITICAL_MISS_PENALTY = Decimal("10.0")

# ---- applicant_disciplinary_risk_index -------------------------------------
SEVERITY_POINTS = {
    "ADVISORY": Decimal("5"),
    "PROBATION": Decimal("15"),
    "SUSPENSION": Decimal("30"),
    "REVOCATION": Decimal("60"),
}
DECAY_PER_FULL_YEAR = Decimal("0.20")
DECAY_FLOOR = Decimal("0.20")
INDEX_CEILING = Decimal("100.00")
GOOD_STANDING_MAX_INDEX = Decimal("25.00")
PATHWAY_BAR_INDEX = Decimal("12.00")
BLOCKING_SEVERITIES = ("SUSPENSION", "REVOCATION")

# ---- net_fee_due_cents ------------------------------------------------------
MILITARY_FULL_WAIVER_CAP_CENTS = 40000

# ---- military_credit_hours --------------------------------------------------
CONVERSION_FACTOR = {
    "MOS_TRAINING": Decimal("0.75"),
    "FIELD_EXPERIENCE": Decimal("0.40"),
    "JOINT_SERVICE_TRANSCRIPT": Decimal("0.90"),
}

# ---- review_deadline / permit_window / license ------------------------------
EXPEDITE_PROCESSING_DAYS = 30
PERMIT_MAX_DAYS = {
    "ENDORSEMENT": 90,
    "UNIVERSAL_RECOGNITION": 120,
    "MILITARY_SPOUSE_EXPEDITED": 180,
}
PERMIT_GRACE_DAYS = 30
LICENSE_TERM_DAYS = 730

# ---- deficiency cycles / reviewer buffer ------------------------------------
MAX_DEFICIENCY_CYCLES = 2
REVIEW_BUFFER_HOURS = 24

# ---- pagination (PRD §2.3) --------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---- logical clock (PRD §2.4) ----------------------------------------------
CLOCK_STARTUP_ISO = "2026-08-01T00:00:00Z"
