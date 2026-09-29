"""Domain thresholds and shared fixture literals from the PRD's stated rules."""

# --------------------------------------------------------------------------- #
# Pro tier ladder                                                              #
# --------------------------------------------------------------------------- #

TRAILING_WINDOW_DAYS = 365

TIER_TABLE = [
    {
        "tier_code": "MEMBER",
        "min_trailing_volume_cents": 0,
        "discount_pct": 0.00,
        "rebate_rate_pct": 0.000,
        "max_quote_term_days": 15,
    },
    {
        "tier_code": "GOLD",
        "min_trailing_volume_cents": 5_000_000,
        "discount_pct": 0.05,
        "rebate_rate_pct": 0.010,
        "max_quote_term_days": 30,
    },
    {
        "tier_code": "PLATINUM",
        "min_trailing_volume_cents": 20_000_000,
        "discount_pct": 0.08,
        "rebate_rate_pct": 0.020,
        "max_quote_term_days": 60,
    },
    {
        "tier_code": "DIAMOND",
        "min_trailing_volume_cents": 50_000_000,
        "discount_pct": 0.12,
        "rebate_rate_pct": 0.030,
        "max_quote_term_days": 90,
    },
]

TIER_BY_CODE = {row["tier_code"]: row for row in TIER_TABLE}

# Baseline volumes that place an account squarely inside each tier band.
BASELINE_VOLUME_FOR_TIER = {
    "MEMBER": 0,
    "GOLD": 6_000_000,
    "PLATINUM": 20_000_000,
    "DIAMOND": 50_000_000,
}

# --------------------------------------------------------------------------- #
# Quote negotiation                                                            #
# --------------------------------------------------------------------------- #

MAX_QUOTE_ROUNDS = 3
MAX_APPROVABLE_DISCOUNT_DEPTH_PCT = 0.30

# --------------------------------------------------------------------------- #
# Order totals                                                                 #
# --------------------------------------------------------------------------- #

FREIGHT_BASE_SURCHARGE_CENTS = 8_900
FREIGHT_WAIVER_SUBTOTAL_CENTS = 250_000
LIFT_GATE_FEE_CENTS = 4_500

# --------------------------------------------------------------------------- #
# Credit exposure                                                              #
# --------------------------------------------------------------------------- #

FREEZE_UTILIZATION_PCT = 0.90

# --------------------------------------------------------------------------- #
# Returns                                                                      #
# --------------------------------------------------------------------------- #

RETURN_WINDOW_DAYS = 90
RESTOCK_FREE_WINDOW_DAYS = 30
QUOTED_MATERIAL_RESTOCK_FLOOR_PCT = 0.15

# --------------------------------------------------------------------------- #
# Rebates                                                                      #
# --------------------------------------------------------------------------- #

REBATE_PERIOD_DAYS = 90

# --------------------------------------------------------------------------- #
# Pagination                                                                   #
# --------------------------------------------------------------------------- #

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# --------------------------------------------------------------------------- #
# Logical clock                                                                #
# --------------------------------------------------------------------------- #

CLOCK_START = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------- #
# Shared fixture literals                                                      #
# --------------------------------------------------------------------------- #

SKU_SHINGLE_BUNDLE = "SHINGLE-BUNDLE"
SKU_MORTAR_BAG = "MORTAR-BAG"
SKU_TRIM_PACK = "TRIM-PACK"

LIST_PRICE_CENTS = {
    SKU_SHINGLE_BUNDLE: 1_999,
    SKU_MORTAR_BAG: 2_000,
    SKU_TRIM_PACK: 1_000,
}

TEST_DEFAULTS = {
    "STORE_CODE": "HD-101",
    "REGION_CODE": "MIDWEST",
    "STATE_CODE": "IL",
    "DISTANCE_RANK": 1,
    "WILL_CALL_BAY_SLOTS": 2,
    "LIFT_GATE_AVAILABLE": True,
    "TAX_RATE_PCT": 0.0825,
    "MAX_STAGE_HOURS": 48,
    "BUSINESS_NAME": "Corner Handyman",
    "ON_HAND_UNITS": 600,
    "TRUCK_CODE": "T-1",
    "TURNAROUND_BUFFER_MINUTES": 30,
}

# A syntactically valid identifier that never resolves to a stored row.
FABRICATED_ID = "00000000-0000-4000-8000-000000000000"
