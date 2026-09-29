"""Named constants drawn from the Tower Colocation Master Lease API PRD.

Every literal here is stated explicitly in the PRD so that tests never hard-code
an unexplained magic number.
"""

# ─── Mounting ────────────────────────────────────────────────────────────────

API_PREFIX = "/tower-colo"

# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────

ROLE_PORTFOLIO_ADMIN = "PortfolioAdmin"
ROLE_STRUCTURAL_ENGINEER = "StructuralEngineer"
ROLE_COMPLIANCE_AUDITOR = "ComplianceAuditor"
ROLE_TENANT = "Tenant"
ROLE_LANDLORD = "Landlord"

ALL_ROLES = (
    ROLE_PORTFOLIO_ADMIN,
    ROLE_STRUCTURAL_ENGINEER,
    ROLE_COMPLIANCE_AUDITOR,
    ROLE_TENANT,
    ROLE_LANDLORD,
)

# ─── Pagination (PRD §2.3) ───────────────────────────────────────────────────

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Logical clock (PRD §2.4) ────────────────────────────────────────────────

CLOCK_COLD_START_UTC = "2026-08-01T00:00:00Z"

# ─── Structural load formula (PRD §3.4) ──────────────────────────────────────

WIND_COEFF_LBS_PER_SQFT = 30
ELEV_TIER_1_LIMIT_FT = 100
ELEV_TIER_2_LIMIT_FT = 200
ELEV_MULT_TIER_1 = 1.00
ELEV_MULT_TIER_2 = 1.25
ELEV_MULT_TIER_3 = 1.50

LOAD_DECIMAL_PLACES = 3
PCT_DECIMAL_PLACES = 3

# ─── Structural analysis thresholds (PRD §3.5) ───────────────────────────────

STRUCTURAL_PASS_LIMIT_PCT = 95.000
STRUCTURAL_CAPACITY_LIMIT_PCT = 100.000
STANDARD_REVIEW_DAYS = 45
MAX_EXPEDITED_REVIEW_DAYS = 45
SLA_CREDIT_PCT = 0.25

# ─── Site rent escalation (PRD §3.7) ─────────────────────────────────────────

ESCALATION_CAP_MULTIPLE = 1.50
ELEVATION_SEPARATION_BUFFER_FT = 10

# ─── Modification cost pipeline (PRD §3.6) ───────────────────────────────────

ENG_FEE_PCT = 0.12
DISCOUNT_TIER_1_CENTS = 10_000_000
DISCOUNT_TIER_1_PCT = 0.015
DISCOUNT_TIER_2_CENTS = 25_000_000
DISCOUNT_TIER_2_PCT = 0.03

# ─── Retroactive unauthorized-install billing (PRD §3.9) ─────────────────────

UNAUTHORIZED_RATE_CENTS_PER_LOAD_UNIT = 25
UNAUTHORIZED_PENALTY_MULTIPLIER = 1.5
RETRO_CAP_MONTHS = 24

# ─── Receivables interlock (PRD §2.12) ───────────────────────────────────────

DELINQUENCY_THRESHOLD_CENTS = 5_000_000

# ─── Capacity posture ladder (PRD §2.8) ──────────────────────────────────────

RESTRICTED_LOAD_PCT = 90.000

# ─── Ground lease renewal (PRD §3.2) ─────────────────────────────────────────

RENEWAL_WINDOW_DAYS = 365
MAX_ESCALATOR_PCT = 25

# ─── Enumerations ────────────────────────────────────────────────────────────

STRUCTURE_TYPES = ("MONOPOLE", "SELF_SUPPORT", "GUYED")
CAPACITY_POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
EQUIPMENT_TYPES = ("ANTENNA", "RRU", "TMA", "DISH")

GROUND_LEASE_STATUSES = ("ACTIVE", "RENEWAL_NEGOTIATION", "EXPIRED", "BOUGHT_OUT")
MLA_STATUSES = ("DRAFT", "ACTIVE", "EXPIRED")
APPLICATION_PRIVILEGES = ("ENABLED", "SUSPENDED")
CREDIT_STATUSES = ("CURRENT", "DELINQUENT")

APPLICATION_STATUSES = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_STRUCTURAL_REVIEW",
    "CAPACITY_HOLD",
    "ON_HOLD",
    "MODIFICATION_REQUIRED",
    "APPROVED",
    "REJECTED",
    "WITHDRAWN",
    "AMENDMENT_ISSUED",
)

ANALYSIS_VARIANTS = ("PRELIMINARY", "DETAILED")
ANALYSIS_STATUSES = ("ISSUED", "QUOTED", "SUPERSEDED")
ANALYSIS_RESULTS = ("PASS", "MODIFICATION_REQUIRED", "CAPACITY_EXCEEDED")

AMENDMENT_EXECUTION_STATUSES = (
    "DRAFT",
    "PENDING_SIGNATURE",
    "EXECUTED",
    "TERMINATION_NOTICED",
    "TERMINATED",
    "VOIDED",
)
AMENDMENT_BILLING_STATUSES = ("NOT_BILLING", "BILLING", "SUSPENDED", "CLOSED")
RESTORATION_STATUSES = ("NOT_REQUIRED", "PENDING", "COMPLETE")

PROJECT_STATUSES = (
    "PROPOSED",
    "COST_ALLOCATED",
    "FUNDED",
    "STALLED",
    "IN_CONSTRUCTION",
    "CERTIFIED",
    "CANCELLED",
)
ALLOCATION_BASES = ("PRO_RATA_LOAD", "EQUAL_SHARE")
COST_SHARE_STATUSES = ("PENDING", "ACCEPTED", "DECLINED", "BILLED", "VOIDED")

AUDIT_STATUSES = ("SCHEDULED", "IN_PROGRESS", "FINALIZED")
AUDIT_BASES = ("INSTALL_DATE_BASIS", "DISCOVERY_LIMITED")
FINDING_STATUSES = ("OPEN", "BILLED")
