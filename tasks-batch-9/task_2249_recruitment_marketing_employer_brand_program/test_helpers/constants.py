"""Literal values the PRD pins: the logical clock origin, pricing tables, thresholds."""

# ------------------------------------------------------------------ logical clock
#: Every freshly started server reports this instant as "now".
CLOCK_START = "2026-08-01T00:00:00Z"
CLOCK_START_RESPONSE = "2026-08-01T00:00:00.000Z"

# -------------------------------------------------------------------- pagination
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0
DEFAULT_OFFSET = 0

# ------------------------------------------------------------------ budget buckets
#: Draw order when a media flight reserves budget.
FLIGHT_BUCKET_ORDER = [
    "FAMILY_DEDICATED",
    "POOL_JOB_BOARD",
    "POOL_SOCIAL",
    "POOL_PROGRAMMATIC",
    "FLEX_RESERVE",
]
#: Draw order when an event presence reserves budget.
EVENT_BUCKET_ORDER = ["FAMILY_DEDICATED", "FLEX_RESERVE"]
#: The pool bucket that matches each payable channel type.
POOL_BUCKET_BY_CHANNEL_TYPE = {
    "JOB_BOARD": "POOL_JOB_BOARD",
    "SOCIAL": "POOL_SOCIAL",
    "PROGRAMMATIC": "POOL_PROGRAMMATIC",
}

# --------------------------------------------------------------- flight pricing
TIER_2_FLOOR_CENTS = 500000
TIER_3_FLOOR_CENTS = 2000000
#: Volume discount percentage per cost tier.
VOLUME_DISCOUNT_PCT = {"TIER_1": 0, "TIER_2": 5, "TIER_3": 8}
#: Platform fee percentage, indexed by channel type then cost tier.
PLATFORM_FEE_PCT = {
    "JOB_BOARD": {"TIER_1": 3, "TIER_2": 3, "TIER_3": 2},
    "SOCIAL": {"TIER_1": 6, "TIER_2": 5, "TIER_3": 4},
    "PROGRAMMATIC": {"TIER_1": 10, "TIER_2": 9, "TIER_3": 7},
}

# ------------------------------------------------------------------- pacing
#: A channel throttles once its cpqa exceeds its blended target by more than 20%.
PACING_THRESHOLD_NUMERATOR = 12
PACING_THRESHOLD_DENOMINATOR = 10

# ------------------------------------------------------------- attribution
TOTAL_CREDIT_BP = 10000
ATTRIBUTION_WINDOW_DAYS = 30
POSITION_BASED_FIRST_BP = 4000
POSITION_BASED_LAST_BP = 4000
POSITION_BASED_MIDDLE_BP = 2000

# ------------------------------------------------------------ persona research
DEFAULT_RESEARCH_WINDOW_DAYS = 180
MIN_MIX_CONFIDENCE_PCT = 40
ENGAGEMENT_DECAY_START_PCT = 100
ENGAGEMENT_DECAY_STEP_PCT = 10
ENGAGEMENT_DECAY_STEP_DAYS = 30
ENGAGEMENT_DECAY_FLOOR_PCT = 10

# -------------------------------------------------------- posting optimization
TITLE_SCORE_IDEAL = 25
TITLE_SCORE_ACCEPTABLE = 10
TITLE_IDEAL_MIN_WORDS = 3
TITLE_IDEAL_MAX_WORDS = 12
TITLE_ACCEPTABLE_MAX_WORDS = 20
RESPONSIBILITY_SCORE_MAX = 20
RESPONSIBILITY_SCORE_PER_ITEM = 4
RESPONSIBILITY_TARGET_COUNT = 5
PAY_TRANSPARENCY_SCORE = 15
EEO_SCORE = 15
BENEFIT_SCORE_PER_ITEM = 5
BENEFIT_SCORE_CAP_COUNT = 5
MIN_PUBLISHABLE_SCORE = 70

# --------------------------------------------------------------- brand health
BRAND_HEALTH_BASE = 100.00
BRAND_HEALTH_MIN = 0.00
BRAND_HEALTH_MAX = 100.00
BRAND_HEALTH_WINDOW_DAYS = 90
RATING_PENALTY_PER_STAR = 2.5
TARGET_RATING = 5
BREACH_PENALTY = 5
#: Recency weight by review age in days.
RECENCY_WEIGHT_RECENT = 1.00
RECENCY_WEIGHT_MID = 0.50
RECENCY_WEIGHT_OLD = 0.25
RECENCY_RECENT_MAX_DAYS = 30
RECENCY_MID_MAX_DAYS = 60
#: A flight may only be activated while brand health is at or above this floor.
BRAND_HEALTH_ACTIVATION_FLOOR = 55.00

# ------------------------------------------------------------------ review SLA
#: Response deadline in hours, by star rating.
SLA_HOURS_BY_RATING = {1: 24, 2: 24, 3: 72, 4: 168, 5: 168}

# ------------------------------------------------------------- talent community
DEFAULT_FREQUENCY_CAP_PER_30D = 4
FREQUENCY_WINDOW_DAYS = 30

# ------------------------------------------------------------- event presences
#: Recruiters need this much clear time between two events of one job family.
EVENT_BUFFER_HOURS = 48

# ------------------------------------------------------- ids that never resolve
UNKNOWN_PROGRAM_ID = "44444444-4444-4444-8444-444444444444"
UNKNOWN_JOB_FAMILY_ID = "66666666-6666-4666-8666-666666666666"
UNKNOWN_JOB_FAMILY_ID_ALT = "11111111-1111-4111-8111-111111111111"
UNKNOWN_PERSONA_ID = "22222222-2222-4222-8222-222222222222"
UNKNOWN_CHANNEL_ID = "33333333-3333-4333-8333-333333333333"
UNKNOWN_POSTING_ID = "55555555-5555-4555-8555-555555555555"
UNKNOWN_POSTING_ID_ALT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
UNKNOWN_FLIGHT_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"
UNKNOWN_TOUCHPOINT_ID = "77777777-7777-4777-8777-777777777777"
UNKNOWN_NURTURE_SEND_ID = "88888888-8888-4888-8888-888888888888"
UNKNOWN_LEDGER_ENTRY_ID = "99999999-9999-4999-8999-999999999999"
#: A client-chosen identifier that the server must never adopt.
CLIENT_SUPPLIED_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
