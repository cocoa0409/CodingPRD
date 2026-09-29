"""Numeric constants the PRD fixes for the TDR program's computations."""

API_PREFIX = "/tdr"

# The logical clock's fixed startup default.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Soil multipliers used by the baseline development-right allocation.
SOIL_MULTIPLIERS = {
    "PRIME": 1.25,
    "STATEWIDE": 1.10,
    "LOCAL": 1.00,
    "NONE": 0.75,
}

# Program fee tiers, keyed on gross_price_cents (inclusive upper bounds).
FEE_TIER_TOP_CENTS = 5_000_000            # <= 5,000,000 cents -> 350 bps
FEE_TIER_MID_CENTS = 25_000_000           # <= 25,000,000 cents -> 275 bps
FEE_BPS_LOW_TIER = 350
FEE_BPS_MID_TIER = 275
FEE_BPS_HIGH_TIER = 200

# Equity surcharge basis points by the origin sending area's equity_tier.
EQUITY_SURCHARGE_BPS = {
    "HIGH_VALUE": 150,
    "MODERATE": 75,
    "UNDERSERVED": 0,
}

# Bank channel pricing spreads applied to the equity-adjusted per-unit value.
BANK_RESALE_MARKUP_BPS = 500
BANK_PURCHASE_DISCOUNT_BPS = 300

# Deviation band on a proposed price (absolute basis points, strictly greater fails).
PRICE_DEVIATION_BAND_BPS = 3000

# Receiving-site bonus sizing.
SITE_TIER_LARGE_ACRES = 10.00
SITE_TIER_MID_ACRES = 3.00
SITE_TIER_FACTOR_LARGE = 1.00
SITE_TIER_FACTOR_MID = 0.90
SITE_TIER_FACTOR_SMALL = 0.75
PROVISIONAL_RELEASE_FRACTION = 0.5

# Revision limits.
MAX_REVISION_ROUNDS = 2
MAX_DESIGN_ROUNDS = 2

# Stewardship.
INSPECTION_MIN_INTERVAL_DAYS = 90
SEVERITY_FINDING_POINTS = {
    "COMPLIANT": 0,
    "MINOR_VIOLATION": 40,
    "MAJOR_VIOLATION": 90,
}
SEVERITY_WEIGHT_FINDING = 0.5
SEVERITY_WEIGHT_EXTENT = 0.3
SEVERITY_WEIGHT_HISTORY = 0.2
HISTORY_POINTS_PER_PRIOR_VIOLATION = 25
HISTORY_POINTS_CAP = 100
CURE_BAND_HIGH_SCORE = 70.00      # score >= 70.00 -> 30 days
CURE_BAND_MID_SCORE = 45.00       # 45.00 <= score < 70.00 -> 60 days
CURE_DAYS_HIGH = 30
CURE_DAYS_MID = 60
CURE_DAYS_LOW = 90

# Reversal window measured from settled_at.
REVERSAL_WINDOW_DAYS = 30

# Pagination bounds.
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

TEST_DEFAULTS = {
    "BASE_RATE_UNITS_PER_ACRE": 0.25,
    "GROSS_DISCOUNT_FACTOR": 0.80,
    "SENDING_CAP_UNITS": 200,
    "GROSS_ACRES": 100.00,
    "CONSTRAINED_ACRES": 0.00,
    "SOIL_CLASS": "LOCAL",
    "EXISTING_DWELLING_UNITS": 0,
    "PER_UNIT_VALUE_CENTS": 1_000_000,
    "BASE_DENSITY_UNITS_PER_ACRE": 4.00,
    "MAX_BONUS_PCT": 0.35,
    "ABSORPTION_CAP_UNITS": 500,
}
