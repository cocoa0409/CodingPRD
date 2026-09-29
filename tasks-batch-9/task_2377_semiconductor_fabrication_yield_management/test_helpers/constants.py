"""Numeric constants, defaults and rounding rules for the Fab Yield API.

Every value here is quoted from the PRD so tests never re-derive a magic
number inline.
"""

# --------------------------------------------------------------------------
# Base URL / routing (PRD §2 and §4)
# --------------------------------------------------------------------------

API_PREFIX = "/fab"

#: The logical-clock endpoint sits outside the domain prefix.
CLOCK_PATH = "/_clock/set_current_utc"


# --------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# --------------------------------------------------------------------------

#: "Before the clock is ever set, it reads exactly 2026-08-01T00:00:00Z".
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

T0 = "2026-08-01T00:00:00Z"
T0_MILLIS = "2026-08-01T00:00:00.000Z"


# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


# --------------------------------------------------------------------------
# Rounding (PRD §2.5)
# --------------------------------------------------------------------------

MONEY_DP = 2      # hours / scores / measured values
CYCLE_DP = 3      # cycle-time days
RATIO_DP = 4      # yields, ratios, sigma deviations

TOL_2DP = 0.005
TOL_3DP = 0.0005
TOL_4DP = 0.00005


# --------------------------------------------------------------------------
# Equipment / capacity ledger (PRD §2.12, §3.3)
# --------------------------------------------------------------------------

INITIAL_CAPACITY_HOURS = 720.0
DEFAULT_PM_INTERVAL_HOURS = 168.0
DEFAULT_PURGE_BUFFER_HOURS = 2.0
DEFAULT_HOURS_SINCE_PM = 0.0


# --------------------------------------------------------------------------
# Chambers / recipes (PRD §3.2, §3.3)
# --------------------------------------------------------------------------

DEFAULT_PARTICLE_LIMIT = 50.0
DEFAULT_QUAL_EXPIRY_DAYS = 90


# --------------------------------------------------------------------------
# Recipe change-request risk score (PRD §3.2)
# --------------------------------------------------------------------------

CLASS_WEIGHT = {"MINOR": 10.0, "MAJOR": 35.0, "CRITICAL": 60.0}
DELTA_WEIGHT = 25.0
DELTA_NORM = 0.10
IMPACT_WEIGHT = 15.0
IMPACT_NORM = 20.0
REQUAL_THRESHOLD = 70.0
MAX_REVISION_ROUNDS = 2


# --------------------------------------------------------------------------
# Capacity commitment tiers (PRD §3.4)
# --------------------------------------------------------------------------

TIER_1_MIN = 0.50
TIER_2_MIN = 0.70
TIER_3_MIN = 0.90

SURCHARGE_RATE = {
    "TIER_0": 0.0,
    "TIER_1": 0.05,
    "TIER_2": 0.12,
    "TIER_3": 0.25,
}


# --------------------------------------------------------------------------
# Cycle time (PRD §3.5)
# --------------------------------------------------------------------------

QUEUE_FACTOR = {"STANDARD": 1.60, "HOT": 1.25, "SUPER_HOT": 1.05}
SECONDS_PER_DAY = 86400
HOURS_PER_DAY = 24


# --------------------------------------------------------------------------
# Dispatch score (PRD §3.6)
# --------------------------------------------------------------------------

DISPATCH_BASE = 100.0
QUAL_DECAY_WEIGHT = 40.0
PARTICLE_WEIGHT = 25.0
PM_WEIGHT = 20.0


# --------------------------------------------------------------------------
# SPC (PRD §3.7)
# --------------------------------------------------------------------------

WARN_SIGMA_MULT = 2.0
RUN_SIGMA_MULT = 1.0
WE_RUN_LENGTH = 4


# --------------------------------------------------------------------------
# Excursion severity (PRD §3.7)
# --------------------------------------------------------------------------

DEVIATION_WEIGHT = 60.0
LOT_WEIGHT = 3.0
LOT_CAP = 10
OOS_PENALTY = 10.0
MEDIUM_BAND = 40.0
HIGH_BAND = 70.0
PARTICLE_TOOL_DOWN_MULT = 2.0
MAX_YIELD_LOSS = 0.25


# --------------------------------------------------------------------------
# Die sort (PRD §3.9)
# --------------------------------------------------------------------------

DOMINANCE_THRESHOLD = 0.45
SIGNATURE_PRECEDENCE = [
    "SCRATCH_LINE",
    "EDGE_RING",
    "CENTER_CLUSTER",
    "PARAMETRIC_SHIFT",
]
SORT_EXCURSION_THRESHOLD = 0.10

#: The four per-wafer failure buckets, in the order the PRD lists them.
FAIL_BUCKETS = [
    "edge_ring_fails",
    "center_cluster_fails",
    "scratch_line_fails",
    "parametric_shift_fails",
]


# --------------------------------------------------------------------------
# Rework (PRD §3.8)
# --------------------------------------------------------------------------

MAX_REWORK_COUNT = 2


# --------------------------------------------------------------------------
# Hold precedence (PRD §2.9), strongest last
# --------------------------------------------------------------------------

HOLD_PRECEDENCE = ["NONE", "SPC_HOLD", "QUAL_HOLD", "ENGINEERING_HOLD"]


# --------------------------------------------------------------------------
# Unknown-id probes.  Well-formed UUIDs that are never minted by the server.
# --------------------------------------------------------------------------

UNKNOWN_UUID = "00000000-0000-0000-0000-0000000000ff"
UNKNOWN_FLOW_ID = "00000000-0000-0000-0000-0000000000aa"
UNKNOWN_EQUIPMENT_ID = "00000000-0000-0000-0000-0000000000bb"
UNKNOWN_STEP_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_CHANGE_REQUEST_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_CHAMBER_ID = "33333333-3333-4333-8333-333333333333"
UNKNOWN_OPERATOR_ID = "44444444-4444-4444-8444-444444444444"
UNKNOWN_PLAN_ID = "55555555-5555-4555-8555-555555555555"
UNKNOWN_LOT_ID = "66666666-6666-4666-8666-666666666666"
UNKNOWN_STEP_RUN_ID = "77777777-7777-4777-8777-777777777777"
UNKNOWN_SPC_CHART_ID = "88888888-8888-4888-8888-888888888888"
UNKNOWN_EXCURSION_ID = "99999999-9999-4999-8999-999999999999"
UNKNOWN_DIE_SORT_RUN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UNKNOWN_CR_ID_FOR_RBAC = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UNKNOWN_EXCURSION_ID_FOR_RBAC = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
UNKNOWN_LOT_ID_FOR_RBAC = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
