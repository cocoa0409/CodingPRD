"""Domain constants and thresholds drawn from the PRD narrative.

Everything here is a literal quantity the PRD pins: the logical clock origin,
the risk-score weights and tier boundaries, the rollout ladder geometry, the
staleness bands, the canary abort arithmetic, the evidence weights and cap
tiers, and the release readiness floor.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §1)
# ---------------------------------------------------------------------------

#: The server's logical clock starts here and never advances on its own.
CLOCK_ORIGIN = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Risk scoring (PRD §3.3)
# ---------------------------------------------------------------------------

SIZE_POINTS_PER_HUNDRED_LINES = 5
SIZE_POINTS_CAP = 30
SPREAD_POINTS_PER_SUBSYSTEM = 4
SPREAD_POINTS_CAP = 20
MIGRATION_POINTS = 25
BLAST_RADIUS_POINTS = {"INTERNAL": 0, "SINGLE_TENANT": 10, "GLOBAL": 20}
DEPENDENCY_POINTS_PER_DEPTH = 5
DEPENDENCY_POINTS_CAP = 15

ROLLBACK_CREDIT_PLAN_AND_TESTED = -10
ROLLBACK_CREDIT_PLAN_ONLY = -5
FLAG_CREDIT_GATES_ENTIRE_CHANGE = -15
FLAG_CREDIT_PARTIAL = -5

RISK_SCORE_MIN = 0
RISK_SCORE_MAX = 100

#: Tier boundaries: LOW below 25, MEDIUM 25..<50, HIGH 50..<70, CRITICAL >= 70.
RISK_TIER_MEDIUM_FLOOR = 25
RISK_TIER_HIGH_FLOOR = 50
RISK_TIER_CRITICAL_FLOOR = 70

#: Approval lanes required per risk class (PRD §3.4).
REQUIRED_LANES = {
    "LOW": [],
    "MEDIUM": ["TECHNICAL"],
    "HIGH": ["TECHNICAL", "COMPLIANCE"],
    "CRITICAL": ["TECHNICAL", "COMPLIANCE", "CAB"],
}

# ---------------------------------------------------------------------------
# Readiness scoring (PRD §3.2)
# ---------------------------------------------------------------------------

READINESS_MAX = 100
READINESS_MIN = 0
READINESS_FLOOR_TO_SHIP = 80

PENALTY_PER_UNTESTED_HIGH_OR_CRITICAL = 4
PENALTY_PER_BLOCKED_CHANGE = 5
PENALTY_PER_STALE_FLAG = 3
PENALTY_PER_LATE_MERGE = 6
PENALTY_PER_UNLANDED_CHANGE = 6

# ---------------------------------------------------------------------------
# Rollout ladder geometry (PRD §3.5)
# ---------------------------------------------------------------------------

LADDER_MIN_CEILING_PCT = 5.0
LADDER_MULTIPLIER = 3
LADDER_MAX_PCT = 100.0

#: Soak bands: target <= 10 needs 30 min, > 10 and <= 50 needs 60, > 50 needs 120.
SOAK_BAND_LOW_TARGET_PCT = 10.0
SOAK_BAND_MID_TARGET_PCT = 50.0
SOAK_MINUTES_LOW = 30
SOAK_MINUTES_MID = 60
SOAK_MINUTES_HIGH = 120

# ---------------------------------------------------------------------------
# Staleness debt (PRD §3.6)
# ---------------------------------------------------------------------------

STALE_POINTS_PER_DAY_OVERDUE = 3
STALE_POINTS_PAUSED_WITH_EXPOSURE = 20
STALE_POINTS_ORPHAN = 15
STALE_DEBT_CAP = 100

CLEANUP_ENFORCED_FLOOR = 60
CLEANUP_OVERDUE_FLOOR = 30
SECONDS_PER_DAY = 86400
WARNING_HORIZON_SECONDS = 604800

# ---------------------------------------------------------------------------
# Deployments and canary analysis (PRD §3.7)
# ---------------------------------------------------------------------------

DEFAULT_COOLDOWN_MINUTES = 30
DEFAULT_CANARY_PCT = 5.0
DEFAULT_MIN_SAMPLE_COUNT = 20

ERROR_COMPONENT_MULTIPLIER = 60
LATENCY_COMPONENT_MULTIPLIER = 40
ERROR_COMPONENT_WEIGHT = 0.6
LATENCY_COMPONENT_WEIGHT = 0.4

# ---------------------------------------------------------------------------
# Incidents (PRD §3.8)
# ---------------------------------------------------------------------------

INCIDENT_LINK_WINDOW_HOURS = 72

# ---------------------------------------------------------------------------
# Evidence packets (PRD §3.9)
# ---------------------------------------------------------------------------

EVIDENCE_ITEM_WEIGHTS = {
    "approvals_complete": 25,
    "rollback_plans": 20,
    "canary_pass": 15,
    "freeze_discipline": 15,
    "flag_hygiene": 15,
    "release_notes": 10,
}

#: Waiver credit cap keyed on ``base_index`` only, never on the running total.
WAIVER_CAP_TIERS = [(85, 15), (70, 10), (50, 5)]
WAIVER_CAP_DEFAULT = 0
WAIVER_MIN_BASE_INDEX = 50

COMPLETENESS_INDEX_MAX = 100
SEAL_MIN_COMPLETENESS_INDEX = 90

# ---------------------------------------------------------------------------
# Recurring fixture data (the scenario vocabulary used by the fixtures module)
# ---------------------------------------------------------------------------

TRAIN_NAME = "core-train"
TRAIN_CADENCE_DAYS = 14
TRAIN_CODE_FREEZE_LEAD_HOURS = 48
TRAIN_STABILIZATION_HOURS = 72
TRAIN_RISK_BUDGET_POINTS = 120

RELEASE_VERSION_LABEL = "2026.08.1"
RELEASE_CUT_AT = "2026-08-10T00:00:00Z"
RELEASE_FREEZE_AT = "2026-08-08T00:00:00Z"
RELEASE_STABILIZATION_END_AT = "2026-08-13T00:00:00Z"

FLAG_EXPIRES_AT = "2026-12-01T00:00:00Z"

CANARY_ABORT_ERROR_RATE_PCT = 25.0
CANARY_ABORT_LATENCY_P95_MS = 800
CANARY_PCT = 10
CANARY_MIN_SAMPLE_COUNT = 5
