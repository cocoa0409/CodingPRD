"""Named constants drawn from the PRD's rating, discount, grant, settlement and
assessment rules, plus the scheduling and threshold numbers the PRD pins.

Tests import these instead of repeating magic numbers so that a single reading of
the PRD governs every expectation.
"""

API_PREFIX = "/eqp"

# A syntactically valid identifier that no record in the system will ever carry.
NON_EXISTENT_ID = "00000000-0000-4000-8000-000000000000"

# The instant the logical clock starts at before any test advances it.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ─── Pagination ───────────────────────────────────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ─── Hazard base premium ──────────────────────────────────────────────────────
BASE_RATE_PER_1000 = {
    "TIER_1": 180,
    "TIER_2": 320,
    "TIER_3": 520,
}
SOIL_FACTOR = {
    "ROCK": 0.85,
    "STIFF": 1.00,
    "SOFT": 1.25,
    "LIQUEFACTION": 1.55,
}
STRUCTURE_FACTOR = {
    "WOOD_FRAME_SLAB": 1.00,
    "WOOD_FRAME_CRIPPLE_WALL": 1.30,
    "MASONRY_URM": 1.85,
    "MOBILE_HOME": 1.45,
}
DEDUCTIBLE_FACTOR = {
    5: 1.35,
    10: 1.00,
    15: 0.86,
    20: 0.75,
    25: 0.66,
}
# The retrofit factor keys off the dwelling's retrofit posture, not off the scope.
# A verified cripple-wall bracing on a cripple-wall structure earns the deepest
# factor; any other verified pairing earns the shallower one.
RETROFIT_FACTOR_VERIFIED_CRIPPLE_WALL = 0.75
RETROFIT_FACTOR_VERIFIED_OTHER = 0.90
RETROFIT_FACTOR_SELF_DECLARED = 0.95
RETROFIT_FACTOR_NONE = 1.00
AGE_FACTOR_PRE_CODE = 1.20
PRE_CODE_YEAR = 1979
HIGH_LIMIT_LOAD = 1.15
HIGH_LIMIT_THRESHOLD_CENTS = 75000000
MIN_PREMIUM_CENTS = 18000
MAX_PREMIUM_CENTS = 4000000
EXPOSURE_UNIT_CENTS = 100000

# ─── Mitigation discount application ──────────────────────────────────────────
DISCOUNT_SCOPE_PCT = {
    "CRIPPLE_WALL_BRACING": 0.25,
    "EARTHQUAKE_BRACING_SYSTEM": 0.20,
    "ANCHOR_BOLT_ONLY": 0.10,
}
GRANT_OFFSET_PCT = 0.05
MIN_EFFECTIVE_DISCOUNT_PCT = 0.05

# ─── Claim settlement ─────────────────────────────────────────────────────────
COSMETIC_ALLOWANCE_PCT = 0.10

# ─── Grant award amount ───────────────────────────────────────────────────────
SCOPE_COST_CAP = {
    "WOOD_FRAME_CRIPPLE_WALL": 1000000,
    "MOBILE_HOME": 600000,
    "WOOD_FRAME_SLAB": 0,
    "MASONRY_URM": 0,
}
MATCH_PCT = {
    "TIER_LOW": 1.00,
    "TIER_MID": 0.75,
    "TIER_ANY": 0.50,
}
MAX_GRANT_CENTS = 300000

# ─── Grant pool waterfall ─────────────────────────────────────────────────────
# The three bucket percentages deliberately sum to more than one; the hard pool
# ceiling is what actually bounds total commitments.
TIER_POOL_PCT = {
    "TIER_LOW": 0.60,
    "TIER_MID": 0.40,
    "TIER_ANY": 0.25,
}

# ─── Post-event assessment ────────────────────────────────────────────────────
LOADING_RATE_SMALL = 0.02
LOADING_RATE_MID = 0.035
LOADING_RATE_LARGE = 0.05
BAND_1_CENTS = 10000000000
BAND_2_CENTS = 50000000000

# ─── Take-up rate evaluation ──────────────────────────────────────────────────
MIN_OFFER_SAMPLE = 4
TAKE_UP_FLOOR_BP = 2500
UNDOCUMENTED_DECLINE_LIMIT = 3

# ─── Calendar and threshold constants ─────────────────────────────────────────
OFFER_VALID_DAYS = 60
QUOTE_VALID_DAYS = 30
TERM_DAYS = 365
RENEWAL_WINDOW_DAYS = 45
MORATORIUM_DAYS = 60
MAX_REVIEW_ROUNDS = 3
MAX_REOPENS = 2
PROBATION_FAIL_THRESHOLD = 3
MAX_OPEN_PROJECTS_PER_CONTRACTOR = 3
INSPECTION_MIN_MINUTES = 30
INSPECTION_MAX_MINUTES = 240
INSPECTION_BUFFER_MINUTES = 60
DECLARATION_MIN_MAGNITUDE = 5.0
