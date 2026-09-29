"""Domain thresholds and numeric constants taken from the PRD's calculations."""

# --- Completeness (PRD §3.4) -------------------------------------------------
IMAGE_WEIGHT = 20

# --- Readiness blend (PRD §3.4 / §3.7 / §3.8) -------------------------------
CERTIFIED_WEIGHT = 0.60
ACCURACY_WEIGHT = 0.40
ACCURACY_CAP_WHEN_NOT_OK = 60.00
LIVE_ENHANCED_BONUS = 5

# Blocking-error penalty bands keyed on open_blocking_error_count.
PENALTY_NONE = 0
PENALTY_ONE_TO_TWO = 5
PENALTY_THREE_TO_FIVE = 12
PENALTY_SIX_OR_MORE = 25

# --- Feed service fee (PRD §3.6) --------------------------------------------
PER_SKU_RATE_CENTS = 2500
VOLUME_DISCOUNT_TIER_1_CENTS = 5000     # >= 5000 and < 15000 -> 5%
VOLUME_DISCOUNT_TIER_2_CENTS = 15000    # >= 15000 and < 25000 -> 10%
VOLUME_DISCOUNT_TIER_3_CENTS = 25000    # >= 25000 -> 15%
VOLUME_DISCOUNT_PCTS = (0.00, 0.05, 0.10, 0.15)
RUSH_WINDOW_HOURS = 24
RUSH_TIER_BOUNDARY_CENTS = 20000
RUSH_SURCHARGE_LOW_PCT = 0.20           # discounted amount below 20000 cents
RUSH_SURCHARGE_HIGH_PCT = 0.12          # discounted amount at or above 20000

# --- Shelf health index (PRD §3.9) ------------------------------------------
HEALTH_ACCURACY_WEIGHT = 0.45
HEALTH_RANK_WEIGHT = 0.25
HEALTH_AVAILABILITY_WEIGHT = 0.20
HEALTH_RATING_WEIGHT = 0.10
RANK_DECAY_PER_POSITION = 5
RATING_MULTIPLIER = 20
HEALTH_ALERT_THRESHOLD = 60.00

# --- Conversion lift (PRD §3.9) ---------------------------------------------
QUALITY_SPLIT_ACCURACY_THRESHOLD = 90.00
DEFAULT_LIFT_VARIANT = "post_pin_window"

# --- Content drift alert (PRD §3.9) -----------------------------------------
CONTENT_DRIFT_THRESHOLD = 85.00

# --- Queue gate (PRD §3.6) --------------------------------------------------
CERTIFIED_QUEUE_THRESHOLD = 85.00

# --- Pagination (PRD §2.3) --------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# --- Logical clock (PRD §2.4) ----------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"
CLOCK_BASE = "2026-08-10T00:00:00Z"

# --- Literal resolution notes the platform writes itself -------------------
CANCELLED_WITH_JOB = "CANCELLED_WITH_JOB"
AUTO_CLEARED_BY_OBSERVATION = "AUTO_CLEARED_BY_OBSERVATION"
AUTO_CLEARED_BY_ACCOUNT_TEAM = "AUTO_CLEARED_BY_ACCOUNT_TEAM"

# --- Prohibited claim tokens (PRD §3.2) ------------------------------------
PROHIBITED_CLAIM_TOKENS = ("cures", "fda approved", "100% guaranteed")

TEST_DEFAULTS = {
    "TITLE_WEIGHT": 40.00,
    "DESCRIPTION_WEIGHT": 30.00,
    "BRAND_WEIGHT": 10.00,
    "TITLE_MAX_CHARS": 200,
    "DESCRIPTION_MAX_CHARS": 2000,
    "BRAND_MAX_CHARS": 60,
}
