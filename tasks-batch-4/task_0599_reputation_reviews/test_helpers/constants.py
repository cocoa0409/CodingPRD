"""Domain thresholds and defaults quoted from the PRD's formulas."""

# --- Logical clock (PRD §2.4) ---------------------------------------------
CLOCK_START = "2026-05-01T00:00:00Z"

# --- Posture derivation (PRD §2.5) ----------------------------------------
POSTURE_MIN_SCORE = 60.00
LISTING_MIN_HEALTH = 40.00
ESCALATION_POSTURE_LIMIT = 3
MIN_REVIEWS_FOR_SCORE_GATE = 3

# --- Sentiment (PRD §3.3) -------------------------------------------------
POSITIVE_MIN_RATING = 4
NEGATIVE_MAX_RATING = 2

# --- Listing health (PRD §3.2) --------------------------------------------
SITE_WEIGHT_GOOGLE = 0.5
SITE_WEIGHT_YELP = 0.3
SITE_WEIGHT_FACEBOOK = 0.2
STATE_FACTOR = {
    "CONNECTED": 1.0,
    "PENDING_SYNC": 0.6,
    "SYNC_FAILED": 0.3,
    "DISCONNECTED": 0.0,
}
STALE_GRACE_DAYS = 7
STALE_MAX_DAYS = 365
MAX_STALENESS_PENALTY = 30
MAX_SYNC_FAILURES = 3

# --- Reputation score (PRD §3.8) ------------------------------------------
RATING_WEIGHT = 60
RESPONSE_WEIGHT = 25
LISTING_WEIGHT = 15
DECAY_PER_30_DAYS = 0.02
DECAY_FLOOR = 0.5

# --- Campaign billing (PRD §3.6) ------------------------------------------
BASE_RATE_SMS = 0.075
BASE_RATE_EMAIL = 0.012
TIER1_MAX_INDEX = 100
TIER1_DISCOUNT = 1.00
TIER2_MAX_INDEX = 500
TIER2_DISCOUNT = 0.90
TIER3_DISCOUNT = 0.80

# --- Attribution / cooldowns / expiry --------------------------------------
ATTRIBUTION_DAYS = 14
SURVEY_TTL_DAYS = 14
DEFAULT_FREQUENCY_CAP_DAYS = 30
CHANNEL_BUFFER_MINUTES = 15

# --- NPS (PRD §3.7) --------------------------------------------------------
NPS_PROMOTER_MIN = 9
NPS_DETRACTOR_MAX = 6

# --- Test data defaults ----------------------------------------------------
TEST_DEFAULTS = {
    "BUSINESS_NAME": "Acme Dental Group",
    "LOCATION_NAME": "Acme Downtown",
    "NAP_NAME": "Acme Dental",
    "NAP_ADDRESS": "1 Main St",
    "NAP_PHONE": "+15551110000",
    "MESSAGE_BODY": "Rate us",
    "SEND_WINDOW_START": "09:00",
    "SEND_WINDOW_END": "11:00",
}
