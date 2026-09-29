"""
Domain constants for the warehouse receipt & commodity collateral API.

Every literal here is transcribed from the PRD: enum member sets, the
calculation constant tables (licensing, grading, storage accrual,
reconciliation, collateral valuation, indemnity allocation, bin condition)
and the shared logical-clock instants used by the tests.
"""

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"
CLOCK_BASE_UTC = "2026-08-05T08:00:00Z"

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLE_STATE_REGULATOR = "StateRegulator"
ROLE_WAREHOUSE_OPERATOR = "WarehouseOperator"
ROLE_DEPOSITOR = "Depositor"
ROLE_LENDER = "Lender"
ROLE_REGISTRY_ADMINISTRATOR = "RegistryAdministrator"

ALL_ROLES = [
    ROLE_STATE_REGULATOR,
    ROLE_WAREHOUSE_OPERATOR,
    ROLE_DEPOSITOR,
    ROLE_LENDER,
    ROLE_REGISTRY_ADMINISTRATOR,
]

# ---------------------------------------------------------------------------
# Enum member sets
# ---------------------------------------------------------------------------
LICENSE_PROGRAMS = ["STATE", "FEDERAL"]
LICENSE_STATES = ["APPLIED", "LICENSED", "SUSPENDED", "REVOKED", "DENIED"]
INSOLVENCY_STATES = ["SOLVENT", "DECLARED", "CLAIMS_OPEN", "ALLOCATED", "CLOSED"]
OPERATIONAL_POSTURES = ["OPEN", "RESTRICTED", "CLOSED"]

LICENSE_DECISIONS = ["ISSUE", "DENY", "SUSPEND", "REINSTATE", "REVOKE"]
INSOLVENCY_ACTIONS = ["DECLARE", "OPEN_CLAIMS", "ALLOCATE", "CLOSE"]

PARTY_KINDS = ["PRODUCER_DEPOSITOR", "COMMERCIAL_DEPOSITOR", "LENDER"]

COMMODITIES = ["CORN", "SOYBEANS", "WHEAT"]
STORAGE_KINDS = ["COMMINGLED", "IDENTITY_PRESERVED"]
AGREEMENT_STATES = ["ACTIVE", "TERMINATED"]

GRADES = ["US_NO_1", "US_NO_2", "US_NO_3", "SAMPLE_GRADE"]
GRADE_RANK = {"US_NO_1": 1, "US_NO_2": 2, "US_NO_3": 3, "SAMPLE_GRADE": 4}

BIN_CONDITION_STATES = ["SOUND", "WATCH", "OUT_OF_CONDITION"]
TREATMENT_ACTIONS = ["NONE", "AERATE", "TURN", "BLEND_OUT"]

TICKET_STATES = ["WEIGHED", "ACCEPTED", "RECEIPTED", "REJECTED"]
REJECTION_REASONS = ["OPERATOR_REJECTED", "LICENSE_SUSPENDED", "INSOLVENCY_DECLARED"]

RECEIPT_FORMS = ["NEGOTIABLE", "NON_NEGOTIABLE"]
RECEIPT_MEDIA = ["PAPER", "ELECTRONIC"]
RECEIPT_STATES = ["ISSUED", "CANCELLED", "VOIDED"]
ENCUMBRANCE_STATES = ["UNENCUMBERED", "PLEDGED", "RELEASED"]
QUALITY_FLAGS = ["SOUND", "IMPAIRED"]
TRANSFER_CHANNELS = ["ENDORSEMENT", "REGISTRY"]

VALUATION_BASES = ["MARK_TO_MARKET", "FACE_ADVANCE"]
PERFECTION_METHODS = ["POSSESSION", "ELECTRONIC_CONTROL"]
LIEN_STATES = ["REQUESTED", "PERFECTED", "RELEASED"]
MARGIN_STATUSES = ["SUFFICIENT", "DEFICIENT"]

REPORT_STATES = ["DRAFT", "UNDER_EXAMINATION", "ACCEPTED", "REJECTED"]
EXAMINATION_RESULTS = ["PASS", "DEFICIENT", "CRITICAL"]

DELIVERY_STATES = [
    "REQUESTED",
    "LOADED",
    "SETTLED_FULL",
    "SETTLED_PARTIAL",
    "CANCELLED",
]

CLAIM_STATES = ["FILED", "ALLOWED", "DISALLOWED", "SETTLED"]
CLAIM_DECISIONS = ["ALLOW", "DISALLOW"]

# ---------------------------------------------------------------------------
# Licensing: net worth and bond requirement constants
# ---------------------------------------------------------------------------
MIN_NET_WORTH_CENTS = {"STATE": 5_000_000, "FEDERAL": 10_000_000}
NET_WORTH_CENTS_PER_BUSHEL = {"STATE": 4, "FEDERAL": 8}
BOND_MIN_CENTS = {"STATE": 2_500_000, "FEDERAL": 6_000_000}
BOND_CENTS_PER_BUSHEL = {"STATE": 5, "FEDERAL": 3}
NET_WORTH_SHORTFALL_TOLERANCE_BPS = 2500
BOND_SHORTFALL_MULTIPLIER_BPS = 15000

# ---------------------------------------------------------------------------
# Grading and deposit quantity constants
# ---------------------------------------------------------------------------
MOISTURE_SHRINK_BPS_PER_POINT = 118

GRADE_LIMITS = {
    "US_NO_1": {"min_test_weight": 56.0, "max_damage": 3.0, "max_foreign": 2.0},
    "US_NO_2": {"min_test_weight": 54.0, "max_damage": 5.0, "max_foreign": 3.0},
    "US_NO_3": {"min_test_weight": 52.0, "max_damage": 7.0, "max_foreign": 4.0},
}

# ---------------------------------------------------------------------------
# Storage accrual constants
# ---------------------------------------------------------------------------
BASE_TIER_DAYS = 90
SURCHARGE_MULTIPLIER_BPS = 12500
MIN_STORAGE_CHARGE_CENTS = 500

# ---------------------------------------------------------------------------
# Reconciliation constants
# ---------------------------------------------------------------------------
EXAM_TOLERANCE_BPS = 50
EXAM_MIN_TOLERANCE_BUSHELS = 500

# ---------------------------------------------------------------------------
# Collateral valuation constants
# ---------------------------------------------------------------------------
GRADE_DISCOUNT_BPS = {
    "US_NO_1": 0,
    "US_NO_2": 150,
    "US_NO_3": 400,
    "SAMPLE_GRADE": 1200,
}
IMPAIRED_DISCOUNT_BPS = 2500
LIEN_ADMIN_FEE_BPS = 25
ADVANCE_RATE_TIER_THRESHOLD_CENTS = 10_000_000
ADVANCE_RATE_HIGH_BPS = 8000
ADVANCE_RATE_LOW_BPS = 7000

# ---------------------------------------------------------------------------
# Indemnity waterfall constants
# ---------------------------------------------------------------------------
FUND_AGGREGATE_CAP_CENTS = 100_000_000
FUND_PER_CLAIMANT_CAP_CENTS = 30_000_000

# ---------------------------------------------------------------------------
# Bin condition thresholds
# ---------------------------------------------------------------------------
WATCH_MOISTURE_PCT = 14.0
OOC_MOISTURE_PCT = 15.5
WATCH_TEMPERATURE_F = 85
OOC_TEMPERATURE_F = 95
BLEND_SHRINK_BPS = 150

# ---------------------------------------------------------------------------
# Temporal windows
# ---------------------------------------------------------------------------
RECEIPT_VOID_WINDOW_HOURS = 72
BIN_REST_BUFFER_MINUTES = 240

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Common fields carried by every resource type in this system
# ---------------------------------------------------------------------------
COMMON_FIELDS = ["id", "created_at", "updated_at", "version"]

# ---------------------------------------------------------------------------
# Base scenario literals shared by the fixtures
# ---------------------------------------------------------------------------
BASE_WAREHOUSE_NAME = "Prairie Elevator"
BASE_OPERATOR_NAME = "Prairie Grain Co"
BASE_STATE_CODE = "KS"
BASE_LICENSED_CAPACITY_BUSHELS = 500_000
BASE_BOND_AMOUNT_CENTS = 2_500_000
BASE_NET_WORTH_CENTS = 5_000_000
BASE_LOADOUT_LANE_COUNT = 2

BASE_LICENSE_EFFECTIVE_DATE = "2026-08-01"
BASE_LICENSE_EXPIRY_DATE = "2027-07-31"

BASE_STORAGE_RATE_MILLICENTS = 350
BASE_RECEIVING_CHARGE_CENTS_PER_BUSHEL = 6
BASE_LOADOUT_CHARGE_CENTS_PER_BUSHEL = 8
BASE_FREE_STORAGE_DAYS = 15
BASE_DECLARED_VALUE_CENTS_PER_BUSHEL = 420
BASE_MAX_MOISTURE_PCT = 14.0

BASE_BIN_CODE = "B1"
BASE_BIN_CAPACITY_BUSHELS = 40_000

BASE_LENDER_CREDIT_LINE_CENTS = 50_000_000

# The base deposit ticket: gross 1005, dockage 4.5% -> 45, clean 960,
# one excess moisture point -> shrink 11, net 949 bushels of US_NO_1 corn.
BASE_TICKET_GROSS_BUSHELS = 1005
BASE_TICKET_NET_BUSHELS = 949
BASE_TICKET_DOCKAGE_BUSHELS = 45
BASE_TICKET_CLEAN_BUSHELS = 960
BASE_TICKET_SHRINK_BUSHELS = 11
BASE_FILL_START_AT = "2026-08-05T09:00:00Z"
BASE_FILL_END_AT = "2026-08-05T11:00:00Z"

BASE_RECEIPT_NUMBER = "WR-0001"
