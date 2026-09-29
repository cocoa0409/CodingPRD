"""Shared literal values for the Healthcare Group Purchasing & Contract Compliance API.

Every value here is transcribed from the PRD under test: the `/gpo` prefix, the
role names, the enum domains, the pagination defaults, the evidence weights, and
the logical-clock default instant.
"""

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

API_PREFIX = "/gpo"

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

# PRD: "Before that capability is called for the first time, the logical clock
# reads exactly 2026-08-01T00:00:00Z, and it never falls back to real
# wall-clock time."
DEFAULT_CLOCK_INSTANT = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_INSTANT_STAMPED = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_CONTRACT_MANAGER = "ContractManager"
ROLE_CLINICAL_REVIEWER = "ClinicalReviewer"
ROLE_COMPLIANCE_ANALYST = "ComplianceAnalyst"
ROLE_MEMBER_MATERIALS_MANAGER = "MemberMaterialsManager"
ROLE_DISTRIBUTOR_AGENT = "DistributorAgent"
ROLE_FINANCE_ADMINISTRATOR = "FinanceAdministrator"

ALL_ROLES = [
    ROLE_CONTRACT_MANAGER,
    ROLE_CLINICAL_REVIEWER,
    ROLE_COMPLIANCE_ANALYST,
    ROLE_MEMBER_MATERIALS_MANAGER,
    ROLE_DISTRIBUTOR_AGENT,
    ROLE_FINANCE_ADMINISTRATOR,
]

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Money / rate arithmetic
# ---------------------------------------------------------------------------

BPS_DENOMINATOR = 10000
PCT_DENOMINATOR = 100

MAX_ADMIN_FEE_BPS = 500
MAX_MEMBER_SHARE_BPS = 10000
MAX_HOLDBACK_BPS = 1000

# ---------------------------------------------------------------------------
# Clinical evidence scoring
# ---------------------------------------------------------------------------

EVIDENCE_WEIGHT_CLINICAL_EFFICACY = 0.40
EVIDENCE_WEIGHT_SAFETY = 0.35
EVIDENCE_WEIGHT_SUPPLY_RESILIENCE = 0.25
CONVERT_THRESHOLD_SCORE = 7.00
MAX_REVISION_ROUNDS = 2

RECOMMENDATION_CONVERT = "CONVERT"
RECOMMENDATION_DO_NOT_CONVERT = "DO_NOT_CONVERT"

# ---------------------------------------------------------------------------
# Leakage reporting
# ---------------------------------------------------------------------------

DEFAULT_LEAKAGE_ALERT_THRESHOLD_PCT = 15.00
LEAKAGE_TOP_N_ITEMS = 3

# ---------------------------------------------------------------------------
# Tier ladders used across the suite
# ---------------------------------------------------------------------------

TIER_0 = "TIER_0"
TIER_1 = "TIER_1"
TIER_2 = "TIER_2"

TIER_ROW_0 = {
    "tier_code": TIER_0,
    "min_committed_volume_units": 0,
    "min_compliance_pct": 0.00,
    "discount_bps": 0,
}
TIER_ROW_1 = {
    "tier_code": TIER_1,
    "min_committed_volume_units": 2000,
    "min_compliance_pct": 80.00,
    "discount_bps": 800,
}
TIER_ROW_2 = {
    "tier_code": TIER_2,
    "min_committed_volume_units": 5000,
    "min_compliance_pct": 90.00,
    "discount_bps": 1500,
}

# The three-rung ladder used by most scenarios: 0 bps / 800 bps / 1500 bps.
FULL_TIER_LADDER = [TIER_ROW_0, TIER_ROW_1, TIER_ROW_2]

# A single-rung ladder: only the zero-discount default tier exists.
FLAT_TIER_LADDER = [TIER_ROW_0]

# Two-rung ladder.
TWO_RUNG_TIER_LADDER = [TIER_ROW_0, TIER_ROW_1]

# Holdback ladders.
HOLDBACK_FLAT = [{"min_gross_pool_cents": 0, "holdback_bps": 0}]
HOLDBACK_LADDER = [
    {"min_gross_pool_cents": 0, "holdback_bps": 0},
    {"min_gross_pool_cents": 100000, "holdback_bps": 250},
]

# ---------------------------------------------------------------------------
# Contract item defaults
# ---------------------------------------------------------------------------

DEFAULT_BASE_PRICE_CENTS = 10000
DEFAULT_FLOOR_PRICE_CENTS = 8200

# ---------------------------------------------------------------------------
# Enum domains
# ---------------------------------------------------------------------------

CONTRACT_STATUSES = ["DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED"]
CONTRACT_ITEM_STATUSES = ["ACTIVE", "DELISTED"]
MEMBER_STATUSES = ["ACTIVE", "SUSPENDED"]
WATCHLIST_STATUSES = ["NONE", "WATCHLIST"]

REVIEW_STATUSES = ["UNDER_REVIEW", "REVISION_REQUESTED", "ENDORSED", "REJECTED"]

ELECTION_STATUSES = ["ELECTED", "ACTIVE", "REQUAL_REVIEW", "TERMINATED"]
LOP_STATUSES = ["NOT_ISSUED", "ISSUED", "SIGNED", "COUNTERSIGNED", "VOID"]

XREF_STATUSES = ["PROPOSED", "APPROVED", "REJECTED"]
XREF_MATCH_TYPES = ["EXACT", "EQUIVALENT", "MANUAL"]

ACTIVATION_STATUSES = [
    "DRAFT",
    "ENDORSED",
    "APPROVED",
    "ACTIVE",
    "SUPERSEDED",
    "DENIED",
]
ACTIVATION_TYPES = ["TIER_PRICE", "LOCAL_EXCEPTION"]
ACTIVATION_ORIGINS = ["REQUEST", "REQUALIFICATION_CASCADE"]

FILE_STATUSES = [
    "RECEIVED",
    "VALIDATING",
    "LOADED",
    "PARTIALLY_LOADED",
    "REJECTED",
    "REVERSED",
]

PURCHASE_LINE_CLASSIFICATIONS = [
    "UNCLASSIFIED",
    "ON_CONTRACT",
    "OFF_CONTRACT_LEAKAGE",
    "UNMATCHED",
]
PURCHASE_LINE_REJECT_REASONS = [
    "NONE",
    "ZERO_QUANTITY",
    "DATE_OUT_OF_PERIOD",
    "NEGATIVE_AMOUNT",
    "UNKNOWN_UOM",
]

MEASUREMENT_STATUSES = ["DRAFT", "PRELIMINARY", "FINAL", "SUPERSEDED"]
MEASUREMENT_VARIANTS = ["PRELIMINARY", "FINAL"]

DISTRIBUTION_STATUSES = ["ACCRUED", "COLLECTED", "DISTRIBUTED", "REVERSED"]
SHARE_BASES = ["ACCRUAL", "COLLECTED"]

UOMS = ["EA", "BX", "CS"]
