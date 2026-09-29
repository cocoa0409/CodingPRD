"""Named constants declared by the Cloud Cost Allocation & Chargeback PRD.

Every value here is copied from the PRD prose so that tests never restate a
formula inline.  Nothing in this module is derived or guessed.
"""

# ─── Routing ──────────────────────────────────────────────────────────────
API_PREFIX = "/finops"
CLOCK_PATH = "/_clock/set_current_utc"

# ─── Logical clock (PRD §2.5) ─────────────────────────────────────────────
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ─── Pagination (PRD §2.3) ────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Roles (PRD §2.1) ─────────────────────────────────────────────────────
ROLE_ANALYST = "FinOpsAnalyst"
ROLE_CONTROLLER = "FinOpsController"
ROLE_BU_OWNER = "BusinessUnitOwner"
ROLE_RESOURCE_OWNER = "ResourceOwner"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = [
    ROLE_ANALYST,
    ROLE_CONTROLLER,
    ROLE_BU_OWNER,
    ROLE_RESOURCE_OWNER,
    ROLE_PLATFORM_ADMIN,
]

# ─── Tag compliance (PRD §3.3) ────────────────────────────────────────────
DIMENSION_WEIGHTS = {"team": 40, "environment": 35, "application": 25}
ALL_DIMENSIONS = ["team", "environment", "application"]
UNTAGGED_ENVIRONMENT = "untagged"

# ─── Commitments (PRD §3.4) ───────────────────────────────────────────────
HOURS_PER_PERIOD = 720
DISCOUNT_RATE_RESERVED_INSTANCE = 0.40
DISCOUNT_RATE_SAVINGS_PLAN = 0.275
REGION_MAX_HOURLY_COMMIT_CENTS = 500
COMMITMENT_BUFFER_HOURS = 24
DEFAULT_COVERAGE_TARGET_PCT = 80.00
DEFAULT_UTILIZATION_TARGET_PCT = 85.00
COMMITMENT_KIND_RANK = ["COMPUTE", "DATABASE", "STORAGE"]

# ─── Invoices and disputes (PRD §3.6, §3.7) ───────────────────────────────
DISPUTE_WINDOW_HOURS = 168
MAX_DISPUTE_ROUNDS = 3
MAX_RUN_REOPENS = 2
DISPUTE_REASON_CODES = [
    "WRONG_OWNER",
    "SHARED_METHODOLOGY",
    "UNTAGGED_ABSORPTION",
    "DOUBLE_CHARGE",
]

# ─── Remediation (PRD §3.8) ───────────────────────────────────────────────
REMEDIATION_WINDOW_HOURS = 72
MAX_SNOOZES = 2
IDLE_UTILIZATION_MAX_PCT = 5.00
RIGHTSIZE_UTILIZATION_MAX_PCT = 30.00
MIN_RUN_RATE_CENTS = 20000
IDLE_SAVINGS_FRACTION = 1.0
RIGHTSIZE_SAVINGS_FRACTION = 0.5
UTILIZATION_WEIGHT = 0.6
RUN_RATE_DIVISOR = 25000
RUN_RATE_SCORE_CAP = 40
WASTE_SCORE_CAP = 100
AUTO_REMEDIATION_SCORE_MIN = 60.00
NON_AUTO_ENVIRONMENT = "prod"

# ─── Anomaly detection (PRD §3.9) ─────────────────────────────────────────
SPIKE_RATIO_MIN = 1.20
SPIKE_DELTA_MIN_CENTS = 50000
SEVERITY_CRITICAL_MIN = 70
SEVERITY_HIGH_MIN = 45
SEVERITY_MEDIUM_MIN = 25
ROOT_CAUSE_KINDS = [
    "NEW_RESOURCE",
    "UTILIZATION_SPIKE",
    "COMMITMENT_EXPIRY",
    "UNTAGGED_ABSORPTION",
]

# ─── Budgets (PRD §3.9) ───────────────────────────────────────────────────
BUDGET_WARN_THRESHOLD_PCT = 5.00
BUDGET_BREACH_THRESHOLD_PCT = 10.00
DEFAULT_ACCURACY_BASIS = "MAPE_BASIS"
ACCURACY_BASES = ["MAPE_BASIS", "PERIOD_END_BASIS"]

# ─── Unit economics (PRD §3.9) ────────────────────────────────────────────
DRIVER_NAMES = ["ORDERS", "ACTIVE_USERS", "API_CALLS", "SHIPMENTS"]
TIER_EFFICIENT_MAX_CENTS_PER_UNIT = 50.00
TIER_STANDARD_MAX_CENTS_PER_UNIT = 250.00
OVERHEAD_RATE_EFFICIENT = 0.03
OVERHEAD_RATE_STANDARD = 0.07
OVERHEAD_RATE_INEFFICIENT = 0.12

# ─── Enum vocabularies used by payloads ───────────────────────────────────
RESOURCE_KINDS = ["COMPUTE", "DATABASE", "STORAGE"]
ALLOCATION_MODES = ["SHOWBACK", "CHARGEBACK"]
ALLOCATION_VARIANTS = ["PROVISIONAL", "FINAL"]
POOL_METHODOLOGIES = ["EVEN_SPLIT", "PROPORTIONAL"]
PROPORTIONAL_BASES = ["SPEND", "HEADCOUNT", "REVENUE"]
ENFORCEMENT_MODES = ["ADVISORY", "BLOCKING"]
COMMITMENT_TYPES = ["RESERVED_INSTANCE", "SAVINGS_PLAN"]
REMEDIATION_KINDS = ["IDLE_TERMINATE", "RIGHTSIZE"]

# ─── Frequently used period boundaries ────────────────────────────────────
JULY_START = "2026-07-01T00:00:00Z"
JULY_END = "2026-08-01T00:00:00Z"
JUNE_START = "2026-06-01T00:00:00Z"
JUNE_END = "2026-07-01T00:00:00Z"
MAY_START = "2026-05-01T00:00:00Z"
MAY_END = "2026-06-01T00:00:00Z"
APRIL_START = "2026-04-01T00:00:00Z"
APRIL_END = "2026-05-01T00:00:00Z"
AUGUST_START = "2026-08-01T00:00:00Z"
AUGUST_END = "2026-09-01T00:00:00Z"
SEPTEMBER_START = "2026-09-01T00:00:00Z"
SEPTEMBER_END = "2026-10-01T00:00:00Z"

# A clock instant a few days into August: past every July period, inside August.
AUGUST_FIFTH_UTC = "2026-08-05T00:00:00Z"

# A syntactically valid identifier that is never issued by the API.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000999"
