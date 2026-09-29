"""Named constants pinned by the PRD.

Every literal here is stated in the PRD narrative; tests import these instead of
re-typing magic numbers so that a threshold test reads at its boundary.
"""

# ─── Logical clock (PRD §2.4) ─────────────────────────
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"


# ─── Pagination (PRD §2.3) ────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


# ─── Operational posture gate (PRD §2.5) ──────────────
JAM_FREEZE_THRESHOLD = 3
LANE_PRESSURE_RESTRICT_RATIO = 1.50
AUTOMATION_RESTRICT_PCT = 45

POSTURE_MULTIPLIER = {
    "OPEN": 1.00,
    "RESTRICTED": 1.10,
    "FROZEN": 1.25,
}


# ─── Facility surface defaults (PRD §3.1) ─────────────
DEFAULT_TURNAROUND_BUFFER_MIN = 15
DEFAULT_MAX_CONCURRENT_DESTINATIONS = 2
CENTER_CODE_MIN_LEN = 3
CENTER_CODE_MAX_LEN = 10


# ─── Lane pressure (PRD §3.2) ─────────────────────────
LANE_CAPACITY_DIVISOR_FLOOR = 1
LANE_PRESSURE_DECIMALS = 4


# ─── Inbound / jam recovery (PRD §3.3) ────────────────
JAM_RETRY_LIMIT = 3

PRIORITY_CLASS_RANK = {
    "CRITICAL": 0,
    "EXPRESS": 1,
    "STANDARD": 2,
    "DEFERRED": 3,
}


# ─── Headcount sizing (PRD §3.4) ──────────────────────
AUTOMATION_TIER_HIGH_PCT = 85
AUTOMATION_TIER_MID_PCT = 60
PPH_TIER_HIGH = 1200
PPH_TIER_MID = 950
PPH_TIER_LOW = 700
MIN_HEADCOUNT_PER_LINE = 4


# ─── Pricing (PRD §3.5, §3.9) ─────────────────────────
RATE_CENTS_PER_HOUR = {
    "CORE": 2150,
    "SEASONAL": 1875,
    "FLEX": 2480,
}

FLEX_PREMIUM_TIER_1_MAX_RATIO = 0.20
FLEX_PREMIUM_TIER_2_MAX_RATIO = 0.35
FLEX_PREMIUM_PCT = {
    "TIER_1": 0.00,
    "TIER_2": 0.05,
    "TIER_3": 0.12,
}

FIXED_OVERHEAD_CENTS_PER_SHIFT = 12000
REWORK_CENTS_PER_MISSORT_PACKAGE = 35

MAX_LINE_HEADCOUNT = 22


# ─── Hiring / attrition (PRD §3.6) ────────────────────
REQUIRED_TRAINING_SESSIONS = 2
MAX_CONSECUTIVE_SHIFTS = 5

TENURE_BUCKET_RISK = {
    "D0_14": 0.42,
    "D15_45": 0.31,
    "D46_120": 0.18,
    "D121_PLUS": 0.09,
}

HIRE_CLASS_ATTRITION_ADJ = {
    "CORE": 0.00,
    "SEASONAL": 0.12,
    "FLEX": 0.07,
}

NO_SHOW_WEIGHT = 0.06
MISSED_TRAINING_WEIGHT = 0.05
CERTIFIED_CREDIT = 0.04
MIN_OBSERVATION_ASSIGNMENTS = 3
ATTRITION_FLAG_THRESHOLD = 0.55
SCORE_CEILING = 0.95
SCORE_FLOOR = 0.02


# ─── Staffing (PRD §3.7) ──────────────────────────────
AT_RISK_GAP_THRESHOLD = 0


# ─── Outbound cube (PRD §3.8) ─────────────────────────
CUFT_PER_PACKAGE = {
    "SMALL": 0.335,
    "MEDIUM": 1.205,
    "LARGE": 3.755,
    "OVERSIZED": 11.505,
}


# ─── Rounding decimal places (PRD §2.9) ───────────────
MONEY_DECIMALS = 0
COST_PER_PACKAGE_DECIMALS = 2
HOURS_DECIMALS = 2
CUBE_DECIMALS = 2
PCT_DECIMALS = 2
RATIO_DECIMALS = 4
