"""Domain constants for the glass container manufacturing API.

Every value here is fixed by the PRD; nothing is inferred.
"""

API_PREFIX = "/glass-plant"
CLOCK_PATH = "/_clock/set_current_utc"

# The logical clock reads exactly this instant before any clock call is made.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# Timestamps are rendered with exactly three fractional-second digits.
TIMESTAMP_SUFFIX = ".000Z"

# --- Colour and refractory wear -------------------------------------------
COLOR_WEAR_FACTOR = {"FLINT": 1.00, "AMBER": 1.15, "GREEN": 1.30}
OVER_PULL_STRESS_WEIGHT = 2.0
CULLET_STRESS_WEIGHT = 0.8

# --- Furnace posture thresholds (percent of refractory life remaining) ----
REBUILD_DUE_REMAINING_PCT = 5.00
RESTRICTED_REMAINING_PCT = 15.00

POSTURE_OPERATING = "OPERATING"
POSTURE_RESTRICTED = "RESTRICTED"
POSTURE_REBUILD_DUE = "REBUILD_DUE"
POSTURE_COLD = "COLD"

# --- Pull limits -----------------------------------------------------------
OVER_PULL_LIMIT_FACTOR = 1.15

# --- Batch house -----------------------------------------------------------
FLINT_CULLET_CEILING_PCT = 90.00
CULLET_STRESS_FLOOR_PCT = 45.00
CULLET_RATIO_FIELD_CEILING_PCT = 95.00
COLOR_CHANGE_RATE_LIMIT = 4
COLOR_CHANGE_RATE_WINDOW_DAYS = 30

# --- Bottle design risk and lead time --------------------------------------
THINNESS_COEFFICIENT = 8
SPEED_COEFFICIENT = 12
SPEED_REFERENCE_BPM = 250
HISTORY_COEFFICIENT = 6
THIN_WALL_MM = 1.60
THIN_WALL_PENALTY = 8
THINNESS_REFERENCE_RATIO = 0.36
BREAKAGE_RISK_INDEX_CAP = 100.00

RISK_SIGNOFF_CAP = 55.00
RISK_DELTA_CAP = 30.00

LEAD_TIME_FLOOR_DAYS = 30
LEAD_TIME_BASE_DAYS = 45
LEAD_TIME_PER_CAVITY_GROUP_DAYS = 5
LEAD_TIME_CAVITY_GROUP_SIZE = 4
LEAD_TIME_PER_REVISION_DAYS = 7
LEAD_TIME_RISK_SURCHARGE_LOW = 0
LEAD_TIME_RISK_SURCHARGE_MID = 10
LEAD_TIME_RISK_SURCHARGE_HIGH = 25
LEAD_TIME_RISK_BAND_LOW = 30.00
LEAD_TIME_RISK_BAND_MID = 45.00
SUPERSEDE_CREDIT_DAYS = 10

# --- Mold sets and changeover ---------------------------------------------
MOLD_SCRAP_CONDITION_THRESHOLD = 40
CHANGEOVER_BASE_MINUTES = 60
FOREIGN_FAMILY_FACTOR = 1.5
CHANGEOVER_CAP_MINUTES = 240
CAVITY_DELTA_TIERS = ((0, 0), (2, 15), (5, 35), (None, 60))
CONDITION_PENALTY_GOOD = 0
CONDITION_PENALTY_FAIR = 10
CONDITION_PENALTY_POOR = 25
CONDITION_GOOD_MIN = 85
CONDITION_POOR_MAX = 70
DEFAULT_CHANGEOVER_BUFFER_MINUTES = 45

# --- Pack lot disposition --------------------------------------------------
MAJOR_PPM_LIMIT = 2500.0
COMBINED_PPM_LIMIT = 9000.0
TRANSITION_ATTRIBUTION_GAP_DAYS = 7

# --- Warehouse aging and palletization ------------------------------------
BASE_AGING_DAYS = 3
THIN_WALL_AGING_DAYS = 2
ADOPTED_PROGRAM_AGING_DAYS = 3
PALLET_UNITS = {"EURO_1200x800": 1800, "GMA_1200x1000": 2100}

# --- Lightweighting economics ---------------------------------------------
TIER_B_FLOOR_USD = 100000.00
TIER_C_FLOOR_USD = 500000.00
RESERVE_BASE_RATE = {"TIER_A": 0.05, "TIER_B": 0.09, "TIER_C": 0.14}
RESERVE_RATE_PER_RISK_DELTA = 0.0009
REBATE_RATE = {"TIER_A": 0.20, "TIER_B": 0.30, "TIER_C": 0.40}
GRAMS_PER_KILOGRAM = 1000

# --- Complaints and customer standing -------------------------------------
PPM_SCALE = 1000000
CREDIT_SHARE_OF_VALUE = 0.5
SEVERITY_SHARE_CAP = 1.0000
WATCH_THRESHOLD_FRACTION = 0.5

STANDING_GOOD = "GOOD"
STANDING_WATCH = "WATCH"
STANDING_CRITICAL = "CRITICAL"

# --- Pagination ------------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# --- Field length limits ---------------------------------------------------
CODE_MAX_LENGTH = 32
LOT_CODE_MAX_LENGTH = 40
CUSTOMER_NAME_MAX_LENGTH = 120
