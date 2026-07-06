"""Domain thresholds — numeric constants from PRD."""

# Platform fee basis-points by product category (PRD §3.6)
PLATFORM_FEE_BPS_BY_CATEGORY = {
    "APPAREL": 1500,
    "DRINKWARE": 1200,
    "ACCESSORY": 1000,
    "PRINT": 800,
}

# Shipping surcharges (PRD §2.6, §3.7)
DOMESTIC_SHIPPING_CENTS = 599
CROSS_BORDER_SHIPPING_CENTS = 1599

# Reprint / payout thresholds (PRD §3.5, §3.8, §3.9)
STRIKE_THRESHOLD = 5
DEFAULT_PAYOUT_FEE_BPS = 250
PAYOUT_RETURN_WINDOW_HOURS = 72

# Sample-order item_count bounds (PRD §3.7)
SAMPLE_ITEM_COUNT_MIN = 1
SAMPLE_ITEM_COUNT_MAX = 3

# markup_bps bounds (PRD §3.2)
MARKUP_BPS_MIN = 0
MARKUP_BPS_MAX = 10000

# Reprint reason weights (PRD §3.8)
REPRINT_REASON_WEIGHTS = {
    "DAMAGED": 1,
    "WRONG_SIZE": 2,
    "MISPRINT": 0,
    "OTHER": 1,
}

# Consumer-fault reprint surcharge percentage (PRD §3.8)
REPRINT_CONSUMER_FAULT_SURCHARGE_PCT = 25

# Logical clock default startup time (PRD §2.10)
CLOCK_DEFAULT_START = "2026-03-01T00:00:00Z"

# Test defaults
TEST_DEFAULTS = {
    "PRODUCT_BASE_COST_CENTS": 2000,
    "MARKUP_BPS": 5000,
    "PARTNER_COST_MULTIPLIER_BPS": 10000,
    "PARTNER_MAX_BACKLOG_HOURS": 168,
    "DIMENSIONS_JSON": {"width_px": 3000, "height_px": 3600, "dpi": 300},
}
