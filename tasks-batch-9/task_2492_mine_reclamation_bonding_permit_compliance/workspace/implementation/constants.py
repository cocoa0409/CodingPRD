"""Domain constants, enum value sets and numeric parameters.

Every value here is transcribed from PRD.md (the literal contract) and
cross-checked against SCAFFOLD.yaml.
"""

from decimal import Decimal

# --------------------------------------------------------------------------
# Roles (PRD 2.1) — spelled exactly as the PRD spells them.
# --------------------------------------------------------------------------
ROLE_OPERATOR = "Operator"
ROLE_PERMIT_REVIEWER = "PermitReviewer"
ROLE_BOND_SPECIALIST = "BondSpecialist"
ROLE_INSPECTOR = "Inspector"
ROLE_PROGRAM_DIRECTOR = "ProgramDirector"
ROLE_PUBLIC_PARTICIPANT = "PublicParticipant"

ALL_ROLES = [
    ROLE_OPERATOR,
    ROLE_PERMIT_REVIEWER,
    ROLE_BOND_SPECIALIST,
    ROLE_INSPECTOR,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_PUBLIC_PARTICIPANT,
]

# Read-role sets, transcribed one by one from the §4 endpoint table. Role
# authority in this domain is exclusive rather than hierarchical, so no set may
# be inferred from another.
ROLES_STAFF_AND_PUBLIC = [
    ROLE_PERMIT_REVIEWER,
    ROLE_BOND_SPECIALIST,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_PUBLIC_PARTICIPANT,
]
ROLES_OP_STAFF_PUBLIC = [
    ROLE_OPERATOR,
    ROLE_PERMIT_REVIEWER,
    ROLE_BOND_SPECIALIST,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_PUBLIC_PARTICIPANT,
]
ROLES_OP_STAFF = [
    ROLE_OPERATOR,
    ROLE_PERMIT_REVIEWER,
    ROLE_BOND_SPECIALIST,
    ROLE_PROGRAM_DIRECTOR,
]
ROLES_OP_STAFF_INSPECTOR = [
    ROLE_OPERATOR,
    ROLE_PERMIT_REVIEWER,
    ROLE_BOND_SPECIALIST,
    ROLE_INSPECTOR,
    ROLE_PROGRAM_DIRECTOR,
]
ROLES_REVISION_READ = [ROLE_OPERATOR, ROLE_PERMIT_REVIEWER, ROLE_PROGRAM_DIRECTOR]
ROLES_INSPECTOR_PROFILE_READ = [
    ROLE_INSPECTOR,
    ROLE_PERMIT_REVIEWER,
    ROLE_BOND_SPECIALIST,
    ROLE_PROGRAM_DIRECTOR,
]
ROLES_QUEUE_READ = [ROLE_PROGRAM_DIRECTOR, ROLE_PUBLIC_PARTICIPANT]

# Auth headers (PRD 2.1: "X-User-ID identifies the acting user and
# X-User-Role declares the capacity in which they act").
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# --------------------------------------------------------------------------
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0

# --------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# --------------------------------------------------------------------------
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Enum value sets
# --------------------------------------------------------------------------
ELECTED_FINANCIAL_TESTS = ["NET_WORTH_TEST", "FIXED_ASSET_TEST"]
REGISTRY_STATUSES = ["ACTIVE", "DISQUALIFIED"]
SELF_BOND_STATUSES = ["UNTESTED", "QUALIFIED", "FAILED", "DISQUALIFIED"]

SITE_CLASSES = ["ACTIVE_PERMITTED", "ABANDONED_LEGACY"]
HAZARD_CLASSES = ["H1_EXTREME", "H2_HIGH", "H3_MODERATE"]
FUNDING_STATUSES = ["NOT_APPLICABLE", "NOMINATED", "FUNDED"]

CERTIFICATION_LEVELS = ["CERT_I", "CERT_II", "CERT_III"]

POST_MINING_LAND_USES = [
    "CROPLAND",
    "FORESTLAND",
    "RANGELAND",
    "INDUSTRIAL",
    "WATER_IMPOUNDMENT",
    "WILDLIFE_HABITAT",
]
PERMIT_STATUSES = [
    "APPLICATION_SUBMITTED",
    "ISSUED",
    "DENIED",
    "RECLAMATION_PHASE",
    "TERMINATED",
    "FORFEITED",
]
COMPLIANCE_POSTURES = [
    "COMPLIANT",
    "NOTICE_ACTIVE",
    "BOND_DEFICIENT",
    "CESSATION",
    "FORFEITURE_PENDING",
]
BOND_BASES = ["FULL_PLAN", "INCREMENTAL"]

ESTIMATE_STATUSES = ["SUBMITTED", "ACCEPTED", "SUPERSEDED"]

INSTRUMENT_TYPES = ["SURETY", "CASH", "COLLATERAL", "SELF_BOND"]
SURETY_RATINGS = ["A_PLUS_PLUS", "A_PLUS", "A", "B_PLUS_PLUS", "B"]
ELIGIBLE_SURETY_RATINGS = ["A_PLUS_PLUS", "A_PLUS", "A", "B_PLUS_PLUS"]
COLLATERAL_TYPES = ["US_TREASURY", "MUNICIPAL_BOND", "IRREVOCABLE_LOC", "REAL_PROPERTY"]
INSTRUMENT_STATUSES = [
    "PROPOSED",
    "ACCEPTED",
    "REPLACED",
    "RELEASED",
    "FORFEITED",
    "SUBSTITUTION_REQUIRED",
]

RELEASE_PHASES = ["PHASE_I", "PHASE_II", "PHASE_III"]
RELEASE_STATUSES = [
    "SUBMITTED",
    "PUBLIC_NOTICE",
    "SUSPENDED",
    "APPROVED",
    "DENIED",
    "RESCINDED",
]

INSPECTION_TYPES = ["ROUTINE", "RELEASE", "COMPLAINT", "ABATEMENT_FOLLOWUP"]
INSPECTION_STATUSES = ["SCHEDULED", "COMPLETED", "CANCELLED"]
INSPECTION_RESULTS = ["PASS", "VIOLATIONS_FOUND"]

VIOLATION_CLASSES = ["NON_COMPLIANCE", "IMMINENT_HARM", "PERMIT_DEFECT"]
NOTICE_STATUSES = ["ISSUED", "CESSATION_ORDERED", "ABATED", "VACATED"]
PENALTY_STATUSES = ["NONE", "ASSESSED", "PAID", "VACATED"]
GOOD_FAITH_LEVELS = ["RAPID", "PARTIAL", "NONE"]

REVISION_TYPES = ["EXPANSION", "SEQUENCE_CHANGE", "PMLU_CHANGE"]
REVISION_STATUSES = ["SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED"]

INITIATION_REASONS = [
    "UNABATED_CESSATION",
    "BOND_DEFICIENCY_UNCURED",
    "OPERATOR_DISQUALIFIED",
]
PROCEEDING_STATUSES = ["INITIATED", "CONTESTED", "FINAL", "COMPLETED"]

DECISIONS_ISSUE = ["ISSUE", "DENY"]
DECISIONS_APPROVE = ["APPROVE", "DENY"]

# Permit status sets that admit child operations (PRD 3.2 / 3.3 / 3.5 / 3.6)
PERMIT_STATUSES_ESTIMATE = ["APPLICATION_SUBMITTED", "ISSUED", "RECLAMATION_PHASE"]
PERMIT_STATUSES_INSTRUMENT = ["APPLICATION_SUBMITTED", "ISSUED", "RECLAMATION_PHASE"]
PERMIT_STATUSES_INSPECTION = ["APPLICATION_SUBMITTED", "ISSUED", "RECLAMATION_PHASE"]
PERMIT_STATUSES_RELEASE = ["ISSUED", "RECLAMATION_PHASE"]
PERMIT_STATUSES_REVISION = ["ISSUED", "RECLAMATION_PHASE"]
PERMIT_STATUSES_RECALC = ["ISSUED", "RECLAMATION_PHASE"]
PERMIT_STATUSES_DISTURBANCE = ["ISSUED", "RECLAMATION_PHASE"]
PERMIT_STATUSES_FORFEITURE = ["ISSUED", "RECLAMATION_PHASE"]

# --------------------------------------------------------------------------
# Bond determination (PRD 3.2)
# --------------------------------------------------------------------------
INDIRECT_COST_RATE = Decimal("0.185")
ANNUAL_INFLATION_RATE = Decimal("0.03")
ADMIN_FEE_RATE = Decimal("0.015")
ADMIN_FEE_MIN = Decimal("2500.00")
ADMIN_FEE_MAX = Decimal("25000.00")
STATUTORY_MINIMUM_BOND = Decimal("10000.00")
DAYS_PER_ESCALATION_YEAR = 365

# --------------------------------------------------------------------------
# Instrument credit (PRD 3.3)
# --------------------------------------------------------------------------
SURETY_RATING_MULTIPLIER = {
    "A_PLUS_PLUS": Decimal("1.00"),
    "A_PLUS": Decimal("1.00"),
    "A": Decimal("0.90"),
    "B_PLUS_PLUS": Decimal("0.75"),
}
COLLATERAL_HAIRCUT = {
    "US_TREASURY": Decimal("0.00"),
    "MUNICIPAL_BOND": Decimal("0.05"),
    "IRREVOCABLE_LOC": Decimal("0.00"),
    "REAL_PROPERTY": Decimal("0.30"),
}

# --------------------------------------------------------------------------
# Self-bonding financial tests (PRD 3.1)
# --------------------------------------------------------------------------
SELF_BOND_MIN_TNW = Decimal("10000000.00")
SELF_BOND_MIN_TNW_RATIO = Decimal("2.5")
NET_WORTH_CAPACITY_RATE = Decimal("0.25")
SELF_BOND_MIN_FIXED_ASSETS = Decimal("20000000.00")
FIXED_ASSET_CAPACITY_RATE = Decimal("0.10")

# --------------------------------------------------------------------------
# Bond release waterfall (PRD 3.5)
# --------------------------------------------------------------------------
PHASE_RELEASE_PCT = {
    "PHASE_I": Decimal("0.60"),
    "PHASE_II": Decimal("0.25"),
    "PHASE_III": Decimal("0.15"),
}
PHASE_RETENTION_RATE = {
    "PHASE_I": Decimal("0.40"),
    "PHASE_II": Decimal("0.15"),
    "PHASE_III": Decimal("0.00"),
}
PUBLIC_NOTICE_DAYS = 30
NOTICE_GAP_DAYS = 15
RESCISSION_WINDOW_DAYS = 60
DEFAULT_BOND_SUMMARY_PHASE = "PHASE_I"

# --------------------------------------------------------------------------
# Violation notices and civil penalties (PRD 3.6)
# --------------------------------------------------------------------------
SEVERITY_POINTS_MAX = 40
NEGLIGENCE_POINTS_MAX = 30
DURATION_POINTS_MAX = 25
HISTORY_LOOKBACK_DAYS = 365
HISTORY_POINTS_PER_PRIOR = 2
HISTORY_POINTS_CAP = 10
TOTAL_POINTS_CAP = 100
CESSATION_POINTS_THRESHOLD = 70

DOLLARS_PER_POINT = Decimal("60.00")
GOOD_FAITH_RATE = {
    "RAPID": Decimal("0.30"),
    "PARTIAL": Decimal("0.10"),
    "NONE": Decimal("0.00"),
}
CREDIT_CAP_HIGH = Decimal("1500.00")
CREDIT_CAP_HIGH_BASE_THRESHOLD = Decimal("3000.00")
CREDIT_CAP_LOW = Decimal("750.00")
CREDIT_CAP_LOW_BASE_THRESHOLD = Decimal("1500.00")
IMMINENT_HARM_SURCHARGE_HIGH = Decimal("0.25")
IMMINENT_HARM_SURCHARGE_HIGH_THRESHOLD = Decimal("5000.00")
IMMINENT_HARM_SURCHARGE_LOW = Decimal("0.10")
IMMINENT_HARM_SURCHARGE_LOW_THRESHOLD = Decimal("2000.00")
MINIMUM_PENALTY = Decimal("750.00")

# --------------------------------------------------------------------------
# Revisions (PRD 3.4)
# --------------------------------------------------------------------------
REVISION_ROUND_CAP = 2

# --------------------------------------------------------------------------
# Estimates (PRD 3.2)
# --------------------------------------------------------------------------
ESTIMATE_MAX_AGE_DAYS = 1095

# --------------------------------------------------------------------------
# Forfeiture (PRD 3.7)
# --------------------------------------------------------------------------
CONTEST_WINDOW_DAYS = 30

# --------------------------------------------------------------------------
# Legacy inventory (PRD 3.8)
# --------------------------------------------------------------------------
HAZARD_WEIGHT = {
    "H1_EXTREME": Decimal("50"),
    "H2_HIGH": Decimal("30"),
    "H3_MODERATE": Decimal("15"),
}
PUBLIC_SAFETY_WEIGHT = Decimal("0.30")
WATER_QUALITY_WEIGHT = Decimal("0.20")
ACRE_POINT_RATE = Decimal("0.05")
ACRE_POINTS_CAP = Decimal("15")
SCORE_CAP = Decimal("100.00")
LEGACY_FUND_ANNUAL_CAP = Decimal("5000000.00")
