"""Domain thresholds and canonical values (PRD §2.5, §2.6, §3.4, §3.7, §3.8)."""

# Logical clock startup default (PRD §2.5).
CLOCK_START = "2026-05-01T00:00:00Z"

# Canonical summer delivery window used across setups (PRD §3.2).
WINDOW_START = "2026-06-15"
WINDOW_END = "2026-08-15"
BID_DUE_DATE = "2026-04-01"
ORDER_BY_DATE = "2026-06-01"

# Install closeout constants (PRD §3.4).
EARLY_COMPLETION_CREDIT_PCT = 0.03

# Replacement deadline constants (PRD §3.7).
REPLACEMENT_BUFFER_DAYS = 14
MAX_REPLACEMENT_DAYS = 21

# Backorder posture threshold (PRD §3.8).
BACKORDER_RISK_THRESHOLD = 2

# Canonical cooperative tier schedules (PRD §3.1, §3.4).
STANDARD_TIER_TABLE = [
    {"min_qty": 1, "unit_price_cents": 12000},
    {"min_qty": 100, "unit_price_cents": 10500},
    {"min_qty": 250, "unit_price_cents": 9000},
]
TWO_TIER_TABLE = [
    {"min_qty": 1, "unit_price_cents": 12000},
    {"min_qty": 100, "unit_price_cents": 10500},
]

TEST_DEFAULTS = {
    "ANNUAL_CAP_CENTS": 100_000_000,
    "FLAT_UNIT_PRICE_CENTS": 11000,
    "INSTALL_RATE_CENTS": 25125,
    "MAX_UNIT_PRICE_CENTS": 13000,
    "SPEC_LINE_QTY": 500,
    "WARRANTY_YEARS": 5,
    "FISCAL_YEAR": 2026,
    "SITE_CAPACITY": 5,
    "MANUFACTURER": "Acme",
    "MODEL": "Desk-100",
}
