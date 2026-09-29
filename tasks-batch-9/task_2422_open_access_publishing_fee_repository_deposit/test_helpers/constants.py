"""Domain thresholds and literals taken from the PRD's calculations."""

# --- Logical clock ---------------------------------------------------------- #
# The clock is initialised to exactly this instant before any request is made.
INITIAL_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- Predatory-venue screening --------------------------------------------- #
SCREENING_WEIGHTS = {
    "NO_DOAJ": 25,
    "NO_COPE": 15,
    "BOARD_UNVERIFIED": 20,
    "RETRACTION_MULTIPLIER": 5,
    "RETRACTION_CAP": 25,
    "FAST_REVIEW": 15,
    "PEER_REVIEW_MIN_DAYS": 14,
    "TRANSPARENCY_CREDIT": 0.1,
}

SCREENING_BANDS = {
    "BLOCKED_MIN": 85,
    "PREDATORY_FLAGGED_MIN": 60,
    "WATCHLIST_MIN": 35,
}

SCORE_MIN = 0
SCORE_MAX = 100

AUTHOR_GUIDANCE = {
    "CLEARED": "Venue cleared: institutional APC funds and agreement coverage may be used.",
    "WATCHLIST": "Venue on watchlist: confirm indexing and peer-review claims before submitting.",
    "PREDATORY_FLAGGED": (
        "Venue flagged as predatory: no institutional funds; deposit the accepted "
        "manuscript instead."
    ),
    "BLOCKED": (
        "Venue blocked: eligibility checks are refused; contact the scholarly "
        "communications office."
    ),
}

# --- Money, invoices and volume tiers -------------------------------------- #
VARIANCE_TOLERANCE_CENTS = 100
DISCOUNT_EPSILON = 0.0001

VOLUME_TIERS = {
    "TIER_20_MIN_CENTS": 5000000,
    "TIER_15_MIN_CENTS": 2000000,
    "TIER_10_MIN_CENTS": 500000,
}
VOLUME_TIER_RATES = {
    "TIER_20": 0.20,
    "TIER_15": 0.15,
    "TIER_10": 0.10,
    "NO_TIER": 0.00,
}

# --- APC funds -------------------------------------------------------------- #
FUND_FREEZE_THRESHOLD_PCT = 0.98
AUTO_FREEZE_REASON = "AUTO_THRESHOLD"

# --- Fund requests ---------------------------------------------------------- #
WITHDRAWAL_RELEASED_REASON = "REQUEST_WITHDRAWN"

# --- Authors, journals and coverage ---------------------------------------- #
DEFAULT_ANNUAL_CAP_CENTS = 500000
DEFAULT_REQUIRED_EMBARGO_MONTHS = 12
COVERAGE_GAP_DAYS = 1

# --- Analytics -------------------------------------------------------------- #
EMPTY_SET_AVERAGE = 0
LEVERAGE_DENOMINATOR_FLOOR = 1
FISCAL_YEAR_START_MONTH_DAY = "07-01"

# --- Minted identifiers ----------------------------------------------------- #
DOI_PREFIX = "10.5555/"
PERSISTENT_IDENTIFIER_PREFIX = "hdl:2027/ir."
FIRST_PERSISTENT_IDENTIFIER = "hdl:2027/ir.000001"

# --- Pagination ------------------------------------------------------------- #
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# --- Convenient payload defaults for tests --------------------------------- #
TEST_DEFAULTS = {
    "COUNTRY_CODE": "GB",
    "CURRENCY": "USD",
    "LIST_APC_CENTS": 300000,
    "ARTICLE_QUOTA": 1,
    "DISCOUNT_PCT": 0.05,
    "JUSTIFICATION": "Grant funds are exhausted for this quarter.",
}
