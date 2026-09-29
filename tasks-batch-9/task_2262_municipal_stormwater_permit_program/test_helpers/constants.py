"""Numeric constants the PRD's calculation narratives fix."""

# Logical clock (PRD §2.4) — the instant the clock reads before any request.
INITIAL_CLOCK = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Tiered stormwater utility fee (PRD §3.8)
# --------------------------------------------------------------------------

DEFAULT_ERU_SQFT = 3000
MIN_ERU_SQFT = 100

TIER1_UPPER_ERU = 1.00
TIER2_UPPER_ERU = 4.00
RATE_TIER1_CENTS_PER_ERU = 9633
RATE_TIER2_CENTS_PER_ERU = 8207
RATE_TIER3_CENTS_PER_ERU = 6541

CLASS_SURCHARGE_PCT = {
    "RESIDENTIAL_SINGLE": 0.00,
    "RESIDENTIAL_MULTI": 0.05,
    "COMMERCIAL": 0.12,
    "INSTITUTIONAL": 0.08,
}

# --------------------------------------------------------------------------
# Fee credit programme (PRD §3.8)
# --------------------------------------------------------------------------

MAX_CREDIT_PCT = 0.5000
MAX_RESUBMISSIONS = 2

# --------------------------------------------------------------------------
# Dry-weather screening indicator panel (PRD §3.2)
# --------------------------------------------------------------------------

BACTERIA_LIMIT_MPN = 1000
SURFACTANT_LIMIT_MG_PER_L = 0.25
AMMONIA_LIMIT_MG_PER_L = 0.50
SUSPECT_INDICATOR_COUNT = 2
SURFACTANT_HARD_TRIGGER_MG_PER_L = 1.00

# --------------------------------------------------------------------------
# Illicit discharge caseload (PRD §3.3)
# --------------------------------------------------------------------------

MAX_REOPEN_COUNT = 3

# --------------------------------------------------------------------------
# Construction sites (PRD §3.4)
# --------------------------------------------------------------------------

MIN_DISTURBED_ACRES = 1.00
POST_CONSTRUCTION_CONTROL_ACRES = 2.00

# --------------------------------------------------------------------------
# Inspection deficiency score (PRD §3.5)
# --------------------------------------------------------------------------

MINOR_FINDING_POINTS = 8
MAJOR_FINDING_POINTS = 22
CRITICAL_FINDING_POINTS = 34
RAINFALL_MULTIPLIER = 1.20
LARGE_SITE_ACRES = 5.00
LARGE_SITE_ADDER = 12
OVERDUE_ADDER = 15
NO_AGREEMENT_ADDER = 25
ESCALATION_THRESHOLD = 70
DEFICIENCY_SCORE_CAP = 100

# --------------------------------------------------------------------------
# Enforcement ladder and penalty ledger (PRD §3.6)
# --------------------------------------------------------------------------

PENALTY_BASE_CENTS = {
    "NOTICE_OF_VIOLATION": 25000,
    "ADMINISTRATIVE_ORDER": 50000,
    "CIVIL_PENALTY": 100000,
}
PER_DAY_CENTS = 2000
MAX_BILLABLE_DAYS = 30
REPEAT_TIER_CENTS = 100000
MULTIPLIER_NONE = 1.00
MULTIPLIER_REPEAT = 1.50
MULTIPLIER_CHRONIC = 2.25
COOLING_OFF_DAYS = 14

# --------------------------------------------------------------------------
# Annual pollutant load and sweeping credit (PRD §3.7)
# --------------------------------------------------------------------------

MG_PER_L_KL_TO_LB = 0.00220462
REQUIRED_SAMPLES_PER_YEAR = 4
LB_PER_LANE_MILE = 0.85
CREDIT_CAP_PCT = 0.25

# --------------------------------------------------------------------------
# Measurable-goal attainment and posture (PRD §3.1)
# --------------------------------------------------------------------------

MAX_OPEN_CASES = 3
MAX_SITE_ENFORCEMENTS = 2
MET_PCT = 100.00
ON_TRACK_PCT = 75.00
NON_COMPLIANT_BEHIND_COUNT = 2

# --------------------------------------------------------------------------
# Annual reporting (PRD §3.9)
# --------------------------------------------------------------------------

INDEX_CEILING_PCT = 100.00
SUBMISSION_WINDOW_DAYS = 90

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --------------------------------------------------------------------------
# Values reused across composite setups
# --------------------------------------------------------------------------

SIX_MEASURE_CODES = [
    "PUBLIC_EDUCATION",
    "ILLICIT_DISCHARGE",
    "CONSTRUCTION_RUNOFF",
    "POST_CONSTRUCTION",
    "MUNICIPAL_OPERATIONS",
    "MONITORING",
]

# The standard measure set the composite fixtures register: target and weight
# per measure_code, plus the two municipal-operations flags set true so that
# gate three does not hold that measure at BEHIND unless a test wants it to.
STANDARD_MEASURE_SET = {
    "PUBLIC_EDUCATION": {"measurable_goal_target": 12.0, "weight": 1},
    "ILLICIT_DISCHARGE": {"measurable_goal_target": 20.0, "weight": 3},
    "CONSTRUCTION_RUNOFF": {"measurable_goal_target": 30.0, "weight": 2},
    "POST_CONSTRUCTION": {"measurable_goal_target": 8.0, "weight": 2},
    "MUNICIPAL_OPERATIONS": {
        "measurable_goal_target": 20.0,
        "weight": 1,
        "salt_storage_covered": True,
        "fleet_wash_recycle": True,
    },
    "MONITORING": {"measurable_goal_target": 4.0, "weight": 1},
}

# A UUID that is well formed but never minted by the server.
UNRESOLVABLE_UUID = "00000000-0000-0000-0000-000000000000"
