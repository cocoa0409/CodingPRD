"""Domain thresholds and fixed values taken from the PRD's calculations."""

# --- carrying capacity -----------------------------------------------------
AUM_DEMAND_LBS_PER_MONTH = 790
DAILY_DEMAND_LBS = 26
HISTORY_SAFETY_FACTOR = 0.85
DAYS_PER_MONTH = 30.4

# --- infrastructure cost allocation ---------------------------------------
INFRA_SHARED_OWNER_PCT = 50

# --- death loss ------------------------------------------------------------
DEATH_CREDIT_PCT = 60

# --- drought ---------------------------------------------------------------
DROUGHT_SEVERE_INDEX = 3
DROUGHT_CONSECUTIVE_REQUIRED = 2
DROUGHT_FORAGE_FLOOR_PCT = 20
DROUGHT_RECOVERY_INDEX = 1
DROUGHT_NOTICE_DAYS = 15

# --- settlement base charge ------------------------------------------------
ADG_TIER_2_FLOOR = 1.50
ADG_TIER_3_FLOOR = 2.25
ADG_TIER_1_MULT = 1.00
ADG_TIER_2_MULT = 1.10
ADG_TIER_3_MULT = 1.20
GAIN_CAP_LBS_PER_HEAD = 250

# --- settlement waterfall --------------------------------------------------
DROUGHT_WAIVER_PCT = 5
OWNER_EARLY_PENALTY_PCT = 8
GRAZIER_EARLY_CREDIT_PCT = 10
REBATE_TIER_1_FLOOR = 500000
REBATE_TIER_2_FLOOR = 1500000

# --- windows and rounds ----------------------------------------------------
REST_DAYS_BUFFER = 14
DISPUTE_WINDOW_DAYS = 10
MAX_DISPUTE_ROUNDS = 2

# --- defaults --------------------------------------------------------------
DEFAULT_CREDIT_LIMIT_CENTS = 500000
DEFAULT_MIN_DAYS = 60
DEFAULT_INFRA_OWNER_CAP_CENTS = 100000
DEFAULT_DEATH_LOSS_THRESHOLD_PCT = 2.0

# --- logical clock ---------------------------------------------------------
LOGICAL_CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_LIMIT = 10

# A syntactically valid UUID that never resolves to a stored row.
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
