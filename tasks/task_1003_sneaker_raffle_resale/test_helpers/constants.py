"""Domain thresholds — numeric constants from the PRD's calculation and rule sections."""

# Transaction fee (platform commission) — PRD §3.7
SELLER_BASE_RATE = {"STANDARD": 0.09, "PRO": 0.07, "ELITE": 0.05}
HIGH_VALUE_CENTS = 50000       # >= this, effective rate drops by HIGH_VALUE_BAND_ADJ
HIGH_VALUE_BAND_ADJ = 0.01
MIN_FEE_CENTS = 500
MAX_FEE_CENTS = 10000

# Buyer charge breakdown — PRD §3.7
PROCESSING_PCT = 0.029
PROCESSING_FLAT_CENTS = 30
SHIPPING_FEE_CENTS = 1500

# Seller payout — PRD §3.7
DOWNGRADE_PENALTY_PCT = 0.15
CONDITION_RANK = {"DEADSTOCK": 3, "VNDS": 2, "USED": 1}

# Grade score weights — PRD §3.6
W_CONDITION = 0.60
W_BOX = 0.25
W_ACCESSORIES = 0.15
CONDITION_VALUE = {"DEADSTOCK": 1.0, "VNDS": 0.85, "USED": 0.6}
BOX_VALUE = {"PERFECT": 1.0, "GOOD": 0.8, "DAMAGED": 0.5, "MISSING": 0.0}

# Fairness / bot heuristics — PRD §3.2, §3.3
W_TRUST = 0.5
W_TENURE = 0.3
W_BOTRISK = 0.2
BOT_RISK_THRESHOLD = 0.6
MIN_ACCOUNT_AGE_DAYS = 3

# Seller level thresholds (completed_sales_count) — PRD §3.7
SELLER_LEVEL_PRO_MIN = 5
SELLER_LEVEL_ELITE_MIN = 20

# Marketplace limits & windows — PRD §3.5, §3.7, §3.2, §3.8
BUY_LIMIT_PER_SKU_24H = 2
RELEASE_COOLDOWN_HOURS = 24
DISPUTE_WINDOW_DAYS = 3

# Server startup logical-clock default — PRD §2.4
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"

# Test-default release windows (a valid ordered set the entry/purchase rules accept)
DEFAULT_ENTRY_OPENS = "2026-07-05T00:00:00Z"
DEFAULT_ENTRY_CLOSES = "2026-07-06T00:00:00Z"
DEFAULT_PURCHASE_OPENS = "2026-07-06T01:00:00Z"
DEFAULT_PURCHASE_CLOSES = "2026-07-07T00:00:00Z"
