"""Domain thresholds — numeric constants from the PRD's business rules."""

# Logical clock
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# NOI opex variants (PRD §3.3)
OPEX_PCT_CONSERVATIVE_NUM = 15   # fifteen percent
OPEX_PCT_MARKET_NUM = 12         # twelve percent

# Cap-rate band in basis points (PRD §3.3)
MIN_CAP_RATE_BPS = 300
MAX_CAP_RATE_BPS = 1200

# Financing thresholds (PRD §3.9)
MAX_LTV_PCT_NUM = 65             # loan <= 65% of PSA price
MIN_DSCR = 1.25                  # commit boundary, inclusive

# PSA field ranges (PRD §3.4)
DD_PERIOD_DAYS_MIN = 15
DD_PERIOD_DAYS_MAX = 120
FINANCING_CONTINGENCY_SLACK_DAYS = 30   # fc_days <= dd_period_days + 30
EARNEST_MONEY_MIN_PCT_NUM = 1           # earnest >= 1% of PSA price

# Title cure committee sign-off threshold in cents (PRD §3.6)
TITLE_CURE_THRESHOLD_CENTS = 100000

# Estoppel rent tolerance in basis points (PRD §3.8)
ESTOPPEL_TOLERANCE_BPS = 50

# Proration day-count convention (PRD §3.11)
DAYS_IN_YEAR = 365

# Deal creation floor (PRD §3.1)
TARGET_CLOSE_MIN_DAYS_AFTER_CREATION = 30

TEST_DEFAULTS = {
    "TARGET_CLOSE_DATE": "2026-10-01T00:00:00Z",
    "PURCHASE_PRICE_CENTS": 15000000,
    "EARNEST_MONEY_CENTS": 250000,
    "LEASE_RENT_CENTS": 1000000,
    "LEASE_COMMENCEMENT": "2020-01-01T00:00:00Z",
    "LEASE_EXPIRATION": "2036-01-01T00:00:00Z",
    "TITLE_RECEIVED_AT": "2026-08-02T00:00:00Z",
    "CLOSING_DATE": "2026-09-15T00:00:00Z",
}
