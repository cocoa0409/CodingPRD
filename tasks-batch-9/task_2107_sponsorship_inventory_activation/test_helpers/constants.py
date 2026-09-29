"""Domain constants and canonical test instants drawn from the PRD."""

# --------------------------------------------------------------------------
# Logical clock instants
# --------------------------------------------------------------------------
# The clock reads exactly this until a PropertyAdmin repositions it.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

SEASON_START = "2026-09-01T00:00:00Z"
SEASON_END = "2026-12-31T23:59:59Z"
TERM_START = "2026-09-01T00:00:00Z"
TERM_END = "2026-12-31T00:00:00Z"
AFTER_TERM_END = "2027-01-02T00:00:00Z"

# Canonical booking window used across the delivery scenarios.
WINDOW_START = "2026-09-10T18:00:00Z"
WINDOW_END = "2026-09-10T21:00:00Z"


# --------------------------------------------------------------------------
# Money and scoring constants
# --------------------------------------------------------------------------
VOLUME_DISCOUNT_TIERS = [
    (5_000_000, 0.12),
    (2_500_000, 0.08),
    (1_000_000, 0.04),
]

IN_KIND_CAP_PCT = 0.25
IN_KIND_HAIRCUT = {
    "MEDIA_TRADE": 0.50,
    "SERVICES": 0.40,
    "PRODUCT": 0.35,
    "TICKETS": 0.20,
}

MAX_MAKEGOOD_PCT = 0.15
OVERSELL_ALLOWANCE = 1.10

INTENT_ADJUSTMENT = {"YES": 10, "MAYBE": 0, "NO": -15}
BAND_HIGH_MIN = 70
BAND_MEDIUM_MIN = 40

SURVEY_WEIGHTS = {
    "satisfaction_score": 0.40,
    "activation_quality_score": 0.35,
    "reporting_quality_score": 0.25,
}

# Minimum rest between two non-touching shifts of the same staffer, in minutes.
MIN_REST_MINUTES = 45

# Pagination envelope defaults.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100


# --------------------------------------------------------------------------
# Canonical rate-card / inventory defaults reused by the composite setups
# --------------------------------------------------------------------------
TEST_DEFAULTS = {
    "PROPERTY_NAME": "Metro FC",
    "SPORT_CODE": "SOCCER",
    "SEASON_YEAR": 2026,
    "SEASONALITY_INDEX": 1.20,
    "INVENTORY_TARGET_VALUE_CENTS": 50_000_000,
    "DIGITAL_BOARD_BASE_UNIT_PRICE_CENTS": 250_000,
    "DIGITAL_BOARD_EXCLUSIVITY_MULTIPLIER": 1.25,
    "SIGNAGE_BASE_UNIT_PRICE_CENTS": 100_000,
    "SIGNAGE_EXCLUSIVITY_MULTIPLIER": 1.10,
    "ASSET_NAME": "North LED Ribbon",
    "ASSET_CAPACITY_UNITS": 6,
    "CHANGEOVER_BUFFER_MINUTES": 30,
    "PROMISED_UNITS": 10,
    "CLAUSE_REF": "4.2(a)",
    "STAFF_NAME": "Dana Reyes",
    "STAFF_HOURLY_RATE_CENTS": 3_500,
    "ROLE_LABEL": "Brand Ambassador",
}

DEFAULT_TIER_BREAKS = [{"min_units": 10, "unit_price_cents": 225_000}]
