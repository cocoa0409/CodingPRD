"""Domain constants for the Drive-Thru Speed-Of-Service API.

Every value here is taken from the PRD: the URL prefix (§1), the logical clock
epoch (§2.4), the volume-tier band table shape (§2.8), the accuracy constant
maps (§3.6), the staffing model bumps (§3.2) and the coaching award table (§3.8).
"""

API_PREFIX = "/drive-thru"

# --- Logical clock (PRD §2.4) --------------------------------------------------
# "The logical clock starts at 2026-08-01T00:00:00Z" and only ever moves forward.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# A UUID-shaped identifier that no request in the suite ever creates.
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"


# --- Enumerations -------------------------------------------------------------
LANE_CONFIGS = ("SINGLE", "DUAL_TANDEM", "DUAL_PARALLEL")
STAFFING_BASES = ("OBSERVED", "FORECAST_ADJUSTED")
SERVICE_POSTURES = ("OPEN", "SURGE", "ACCURACY_HOLD", "FROZEN")
POSTURE_OVERRIDES = ("NONE", "FROZEN")
VOLUME_TIERS = ("TIER_1", "TIER_2", "TIER_3", "TIER_4")
MERGE_AWARD_BIASES = ("ALTERNATE", "LONGEST_WAIT", "ACCURACY_FIRST")
DAYPARTS = ("BREAKFAST", "LUNCH", "AFTERNOON", "DINNER", "LATE")
PROFILE_STATES = ("DRAFT", "ACTIVE", "RETIRED")
STAFF_STATES = ("AVAILABLE", "DEPLOYED", "INACTIVE")
DEPLOYMENT_POSITIONS = ("OOT_LANE_A", "OOT_LANE_B", "EXPEDITER", "RUNNER")
OOT_POSITIONS = ("OOT_LANE_A", "OOT_LANE_B")
DEPLOYMENT_STATES = ("PLANNED", "ACTIVE", "RELEASED", "ABORTED")
TIMING_STATES = (
    "OPEN",
    "GREETED",
    "ORDERED",
    "MERGED",
    "AT_WINDOW",
    "CLOSED",
    "ABANDONED",
)
ACCURACY_STATES = ("PENDING", "VERIFIED", "REMAKE_OPEN", "REMADE", "WAIVED")
LANES = ("SINGLE", "LANE_A", "LANE_B")
BREACH_SEGMENTS = ("GREET", "ORDER", "PULL_FORWARD", "WINDOW")
SLOT_STATES = ("RESERVED", "COMMITTED", "RELEASED", "FORFEITED")
AWARD_REASONS = ("ALTERNATE", "LONGEST_WAIT", "ACCURACY_FIRST", "CAR_SEQUENCE_TIE_BREAK")
PULL_FORWARD_REASONS = ("ITEM_LAG", "REMAKE_OPEN", "MERGE_CONFLICT")
PULL_FORWARD_STATES = ("ISSUED", "PARKED", "CLEARED", "CANCELLED")
INCIDENT_TYPES = ("WRONG_ITEM", "MISSING_ITEM", "WRONG_SIZE", "ALLERGEN")
SEVERITIES = ("MINOR", "MAJOR", "CRITICAL")
INCIDENT_STATES = ("LOGGED", "REMADE", "CLOSED", "WAIVED")
SETTLEMENT_STATES = ("ACCRUED", "CHARGED", "REVERSED")
REPORT_VARIANTS = ("PROVISIONAL", "FINAL")
METRIC_BASES = ("TOTAL", "ADJUSTED_TOTAL")
REPORT_STATES = ("DRAFT", "PUBLISHED", "SUPERSEDED", "RETRACTED")
ATTAINMENT_BANDS = ("GOLD", "GREEN", "AMBER", "RED")
FOCUS_SEGMENTS = ("GREET", "ORDER", "PULL_FORWARD", "WINDOW", "ACCURACY")
COACHING_TIERS = ("TIER_A_OBSERVE", "TIER_B_COACH", "TIER_C_RETRAIN")
COACHING_STATES = ("DRAFT", "ISSUED", "ACKNOWLEDGED", "CONTESTED", "CLOSED")
OVERRIDE_SOURCES = ("WEATHER", "LOCAL_EVENT", "SYSTEM_OUTAGE")
OVERRIDE_STATES = ("PROPOSED", "APPROVED", "REJECTED", "APPLIED")


# --- Daypart targets (PRD §3.1) -----------------------------------------------
# The LUNCH window used throughout the suite: minute-of-day 660 (11:00) up to but
# not including 840 (14:00), with the four segment targets summing to 235.
LUNCH_START_MINUTE = 660
LUNCH_END_MINUTE = 840
BASE_GREET_TARGET = 25
BASE_ORDER_TARGET = 95
BASE_PULL_FORWARD_TARGET = 40
BASE_WINDOW_TARGET = 75
BASE_TOTAL_TARGET = (
    BASE_GREET_TARGET
    + BASE_ORDER_TARGET
    + BASE_PULL_FORWARD_TARGET
    + BASE_WINDOW_TARGET
)


# --- Volume-tier bands (PRD §2.8) ---------------------------------------------
# A single unbounded band: every rate from 0.0 upward resolves to TIER_1, so the
# store's volume_tier never moves and the pinned relief stays 0.00.
UNBOUNDED_BAND = {
    "tier": "TIER_1",
    "cars_per_hour_floor": 0,
    "target_relief_pct": 0.00,
    "min_oot_count": 0,
    "merge_award_bias": "ALTERNATE",
}

# The four-band ladder used whenever a chain has to cross a tier boundary.
FOUR_TIER_BANDS = (
    {
        "tier": "TIER_1",
        "cars_per_hour_floor": 0,
        "cars_per_hour_ceiling": 6,
        "target_relief_pct": 0.00,
        "min_oot_count": 0,
        "merge_award_bias": "ALTERNATE",
    },
    {
        "tier": "TIER_2",
        "cars_per_hour_floor": 6,
        "cars_per_hour_ceiling": 12,
        "target_relief_pct": 0.03,
        "min_oot_count": 1,
        "merge_award_bias": "LONGEST_WAIT",
    },
    {
        "tier": "TIER_3",
        "cars_per_hour_floor": 12,
        "cars_per_hour_ceiling": 18,
        "target_relief_pct": 0.07,
        "min_oot_count": 2,
        "merge_award_bias": "ACCURACY_FIRST",
    },
    {
        "tier": "TIER_4",
        "cars_per_hour_floor": 18,
        "target_relief_pct": 0.12,
        "min_oot_count": 3,
        "merge_award_bias": "LONGEST_WAIT",
    },
)


# --- Accuracy constants (PRD §3.6) --------------------------------------------
SEVERITY_BY_INCIDENT_TYPE = {
    "ALLERGEN": "CRITICAL",
    "WRONG_ITEM": "MAJOR",
    "MISSING_ITEM": "MAJOR",
    "WRONG_SIZE": "MINOR",
}
PENALTY_SECONDS_BY_SEVERITY = {"MINOR": 20, "MAJOR": 45, "CRITICAL": 90}
REMAKE_COST_CENTS_BY_SEVERITY = {"MINOR": 350, "MAJOR": 750, "CRITICAL": 1200}


# --- Rollup and staffing constants (PRD §2.7, §3.2, §2.6) ---------------------
TRAILING_WINDOW_SECONDS = 600
DUAL_PARALLEL_BUMP_CPH = 12
ACCURACY_HOLD_THRESHOLD = 2
MAX_OOT_COUNT = 4
CHANGEOVER_BUFFER_SECONDS = 600
DEFAULT_MAX_CONSECUTIVE_DEPLOYMENT_MINUTES = 90


# --- Timer-loop constants (PRD §3.3) ------------------------------------------
ESCALATION_PENALTY_SECONDS = 15
MAX_COMBINED_RELIEF = 0.30
MAX_OVERRIDE_RELIEF = 0.20


# --- Report / coaching constants (PRD §3.8, §3.9) -----------------------------
ABANDONED_METRIC_SECONDS = 300
BAND_POINTS = {"GOLD": 10, "GREEN": 6, "AMBER": 3, "RED": 0}
BAND_WEIGHT = {"GOLD": 0.0, "GREEN": 0.2, "AMBER": 0.6, "RED": 1.0}
REMAKE_POINT_PENALTY = 2
VOLUME_POINT_CAP = 6
CARS_PER_VOLUME_POINT = 25
OVERRIDE_AGGREGATE_CAP = 0.50


# --- Pagination (PRD §2.3) ----------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
