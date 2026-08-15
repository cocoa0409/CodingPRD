"""Domain thresholds — numeric constants from PRD sections 2.5 and 3.1."""

# PRD section 2.5: before any set call, the logical clock reads exactly this.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# PRD section 3.1: program policy knobs and their documented defaults.
PROGRAM_DEFAULTS = {
    "OVER_SHORT_TOLERANCE_CENTS": 500,
    "EXCHANGE_WINDOW_DAYS": 14,
    "PICKUP_WINDOW_DAYS": 7,
    "REGISTER_BUFFER_MINUTES": 30,
    "DEPOSIT_FLOOR_CENTS": 500,
}

TEST_DEFAULTS = {
    "OPENING_FLOAT_CENTS": 10000,
    "UNIT_PRICE_CENTS": 2500,
    "UNIT_COST_CENTS": 500,
    "STOCK_QTY": 25,
    "CAMPAIGN_OPENS": "2026-08-01T00:00:00Z",
    "CAMPAIGN_CLOSES": "2026-09-01T00:00:00Z",
    "EVENT_STARTS": "2026-09-05T14:00:00Z",
    "EVENT_ENDS": "2026-09-05T16:00:00Z",
}
