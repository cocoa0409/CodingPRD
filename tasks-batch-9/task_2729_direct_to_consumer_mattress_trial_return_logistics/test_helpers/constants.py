"""Domain thresholds and literal constants drawn from the PRD's stated rules."""

# PRD §2.5 — the logical clock reads exactly this instant before any operator sets it.
LOGICAL_CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# PRD §2.3 — pagination window.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# PRD §2.6 — one whole day is exactly this many seconds.
SECONDS_PER_DAY = 86400

THRESHOLDS = {
    # PRD §3.2 — abuse signal weights.
    "SIGNAL_WEIGHT_HOUSEHOLD_MATCH": 30,
    "SIGNAL_WEIGHT_REPEAT_RETURN": 25,
    "SIGNAL_WEIGHT_SHORT_TRIAL": 15,
    "SIGNAL_WEIGHT_MULTI_CHANNEL": 10,
    # PRD §3.2 — rolling decay steps and posture thresholds.
    "DECAY_STEP_DAYS": 180,
    "WINDOW_DAYS": 365,
    "SCORE_CEILING": 100,
    "ABUSE_RESTRICT_THRESHOLD": 60,
    "ABUSE_BLOCK_THRESHOLD": 80,
    "ABUSE_BLOCK_DAYS": 365,
    # PRD §3.7 — a return collected under this many nights is a short trial.
    "SHORT_TRIAL_NIGHTS": 30,
    # PRD §3.1 — catalogue defaults.
    "DEFAULT_BREAK_IN_NIGHTS": 21,
    "DEFAULT_TRIAL_NIGHTS": 100,
    "DEFAULT_INDENTATION_THRESHOLD_MM": 25,
    "DEFAULT_WARRANTY_YEARS": 10,
    "DEFAULT_ATTRIBUTION_WINDOW_DAYS": 30,
    "DEFAULT_BUFFER_MINUTES": 30,
    # PRD §3.5 — comfort-exchange settlement.
    "EXCHANGE_FEE_BASE_CENTS": 9900,
    "EXCHANGE_FEE_STEP_CENTS": 5000,
    "EXCHANGE_FEE_CAP_CENTS": 24900,
    "TIER_A_MAX_CENTS": 20000,
    "TIER_B_MAX_CENTS": 50000,
    "TIER_A_CREDIT_BPS": 0,
    "TIER_B_CREDIT_BPS": 250,
    "TIER_C_CREDIT_BPS": 500,
    "MAX_EXCHANGES_PER_CHAIN": 2,
    # PRD §3.4 — quality-claim evidence minimums and credits.
    "MIN_PHOTOS_DELIVERY": 2,
    "MIN_PHOTOS_STRAIGHTEDGE": 3,
    "MIN_PHOTOS_LASER": 1,
    "DAMAGE_GOODWILL_BPS": 1500,
    "COMPRESSION_GOODWILL_CENTS": 7500,
    "WARRANTY_DECAY_BPS_PER_YEAR": 1000,
    "WARRANTY_FLOOR_BPS": 2000,
    "MAX_EVIDENCE_ROUNDS": 2,
    "COMPRESSION_RECOVERY_WAIT_NIGHTS": 3,
    "DAMAGE_REPORT_WINDOW_NIGHTS": 7,
    # PRD §3.8 — inspection and refund settlement.
    "USAGE_RETENTION_BPS": 2500,
    "TIER1_MAX_NIGHTS": 30,
    "TIER1_BPS": 0,
    "TIER2_MAX_NIGHTS": 60,
    "TIER2_BPS": 500,
    "TIER3_MAX_NIGHTS": 100,
    "TIER3_BPS": 1200,
    "TIER4_BPS": 2000,
    "SOIL_OFFSET_BPS": 1000,
    "DAMAGE_OFFSET_CAP_BPS": 4000,
    # PRD §3.10 — attribution and price match.
    "MIN_CLAIM_EVIDENCE": 2,
    "PRICE_MATCH_CAP_BPS": 1000,
    "MAX_REVISION_ROUNDS": 2,
}

# PRD §3.8 — retention basis points by condition grade.
GRADE_RETENTION_BPS = {"A": 0, "B": 500, "C": 1500, "D": 3000}

# PRD §3.7 — capacity units consumed by a pickup, keyed on the mattress size.
SIZE_UNITS = {"TWIN": 1, "QUEEN": 2, "KING": 3}

# Values reused across fixtures so that the pinned money literals stay reproducible.
TEST_DEFAULTS = {
    "QUEEN_LIST_PRICE_CENTS": 120000,
    "TWIN_LIST_PRICE_CENTS": 70000,
    "KING_LIST_PRICE_CENTS": 180000,
    "DELIVERY_CLOCK": "2026-08-01T00:00:00Z",
    "RETURN_REQUEST_CLOCK": "2026-09-10T00:00:00Z",
    "PICKUP_CLOCK": "2026-09-15T00:00:00Z",
    "ROUTE_DATE": "2026-09-15",
    "ROUTE_WINDOW_START_AT": "2026-09-15T08:00:00Z",
    "ROUTE_WINDOW_END_AT": "2026-09-15T18:00:00Z",
    "SLOT_START_AT": "2026-09-15T09:00:00Z",
    "SLOT_END_AT": "2026-09-15T11:00:00Z",
    "INTAKE_DATE": "2026-09-16",
    "REGION_CODE": "CA",
    "ROUTE_CAPACITY_UNITS": 6,
    "PARTNER_DAILY_CAPACITY_UNITS": 6,
}
