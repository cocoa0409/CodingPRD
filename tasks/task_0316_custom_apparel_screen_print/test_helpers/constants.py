"""Domain thresholds — numeric constants from the PRD's pricing and scheduling rules."""

# Quantity-tier run-rate cutoffs and rates (PRD §3.5).
# line_qty <= 23 -> 800; <= 71 -> 550; <= 143 -> 400; >= 144 -> 300.
TIER_RATES = {
    "TIER1_MAX": 23,
    "TIER2_MAX": 71,
    "TIER3_MAX": 143,
    "TIER1_RATE_CENTS": 800,
    "TIER2_RATE_CENTS": 550,
    "TIER3_RATE_CENTS": 400,
    "TIER4_RATE_CENTS": 300,
}

# Shop-configurable defaults (PRD §3.1, §3.2).
SHOP_DEFAULTS = {
    "SPOILAGE_PCT": 0.05,
    "RUSH_THRESHOLD_DAYS": 7,
    "RUSH_SURCHARGE_PCT": 0.25,
    "EPOCH_UTC": "1970-01-01T00:00:00.000Z",
}

# DecorationMethod cost-knob defaults (PRD §3.1).
METHOD_DEFAULTS = {
    "SCREEN_FEE_CENTS": 2500,
    "DIGITIZING_FEE_CENTS": 5000,
    "EXTRA_COLOR_RUN_CENTS": 75,
    "STITCH_RUN_PER_1K_CENTS": 90,
}

# Machine defaults (PRD §3.2).
MACHINE_DEFAULTS = {
    "TEARDOWN_BUFFER_MIN": 30,
    "HEAD_COUNT": 1,
}

# Deposit fraction (PRD §3.4): deposit = ceil(grand_total * 0.5).
DEPOSIT_PCT = 0.5

# Test fixture defaults used across composite setups.
TEST_DEFAULTS = {
    "BLANK_COST_CENTS": 350,
    "STOCK_QTY": 200,
    "NON_RUSH_SHIP_DATE": "2026-06-20T00:00:00.000Z",
    "CLOCK_UTC": "2026-06-01T00:00:00.000Z",
}
