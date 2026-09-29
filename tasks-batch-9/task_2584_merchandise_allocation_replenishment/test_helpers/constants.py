"""Domain thresholds and defaults taken from the PRD's calculation rules."""

# Numeric constants the PRD pins by name.
THRESHOLDS = {
    "COVER_WEEKS": 4,
    "PUSH_FILL_RATE_BP": 8000,
    "DEFAULT_LIFT_BP": 10000,
    "FREIGHT_MIN_USD": 45.00,
    "PER_UNIT_HANDLING_USD": 0.85,
    "NET_MARGIN_BP": 5500,
    "HANDLING_TIER_LOW_BP": 1200,
    "HANDLING_TIER_MID_BP": 900,
    "HANDLING_TIER_HIGH_BP": 600,
    "HANDLING_TIER_MID_FLOOR_USD": 50.00,
    "HANDLING_TIER_HIGH_FLOOR_USD": 150.00,
    "TRANSFER_TTL_DAYS": 7,
    "PROMO_BUFFER_DAYS": 1,
    "DEFAULT_TRANSFER_MIN_RATIO_BP": 15000,
    "DEFAULT_CORE_SIZE_MIN_SHARE_BP": 1500,
    "BASIS_POINT_ONE": 10000,
}

# Tiered markdown depth: lower bound in basis points -> depth in basis points.
MARKDOWN_TIERS_BP = [
    (0, 0),
    (2500, 1500),
    (5000, 3000),
    (7500, 4500),
]

# Store grade ranking used by the PRD's deterministic tie-breaks.
GRADE_RANK = {"A": 1, "B": 2, "C": 3, "D": 4}

# Promotional-event scope specificity ranking.
SPECIFICITY_RANK = {"PROGRAM": 1, "CLUSTER": 2, "STORE": 3}

# The clock value the PRD says is in force before any explicit set.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Pagination envelope defaults.
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Reusable literals for the standard four-size apparel curve used across tests.
SIZE_CURVE_TOP_4SZ = [
    {"size_code": "S", "share_bp": 2000},
    {"size_code": "M", "share_bp": 3500},
    {"size_code": "L", "share_bp": 3000},
    {"size_code": "XL", "share_bp": 1500},
]

TEST_DEFAULTS = {
    "PROGRAM_NAME": "FA26 Core Tops",
    "SEASON_CODE": "FA26",
    "BANNER_CODE": "NORTH",
    "PROFILE_CODE": "TOP-4SZ",
    "ITEM_CLASS": "APPAREL_TOP",
    "SKU_CODE": "SKU-1001",
    "STYLE_CODE": "ST-100",
    "UNIT_COST_USD": 14.20,
    "RETAIL_PRICE_USD": 36.50,
}
