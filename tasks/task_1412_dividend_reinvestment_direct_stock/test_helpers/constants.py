"""Domain thresholds and default configuration values from the PRD."""

# Logical clock (PRD logical-clock section): value at server startup.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Notice publication lead time in days (PRD plan-communications section).
MIN_NOTICE_DAYS = 10

# Share quantization (PRD rounding-discipline section).
SHARE_DECIMALS = 4

# Standard plan economic configuration shared by most scenarios.
DEFAULT_PLAN_CONFIG = {
    "discount_pct": 0.05,
    "pricing_basis": "MARKET_CLOSE",
    "basis_method": "FIFO",
    "ocp_min_cents": 1000,
    "ocp_max_cents": 25000,
    "ocp_fee_pct": 0.05,
    "ocp_fee_min_cents": 500,
    "sale_fee_cents": 250,
    "transfer_fee_cents": 300,
    "enrollment_fee_cents": 1000,
}

# Standard dividend timeline used by dividend scenarios.
DEFAULT_DIVIDEND_AMOUNT_PER_SHARE = 50
DEFAULT_RECORD_DATE = "2026-09-10T00:00:00Z"
DEFAULT_PAYABLE_DATE = "2026-09-20T00:00:00Z"
DEFAULT_EXECUTION_CLOCK = "2026-09-20T10:00:00Z"
DEFAULT_CLOSING_PRICE = 2000
DEFAULT_AVG5_PRICE = 2100

# Standard purchase-window timeline used by window/order scenarios.
DEFAULT_WINDOW_OPENS = "2026-09-01T00:00:00Z"
DEFAULT_WINDOW_CLOSES = "2026-09-15T00:00:00Z"
DEFAULT_WINDOW_PRICE_CENTS = 2500
DEFAULT_WINDOW_OPEN_CLOCK = "2026-09-02T00:00:00Z"
DEFAULT_WINDOW_CLOSE_CLOCK = "2026-09-16T00:00:00Z"
