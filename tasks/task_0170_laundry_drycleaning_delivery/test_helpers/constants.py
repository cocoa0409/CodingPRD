"""Domain thresholds — numeric constants from PRD calculations and rules."""

# Wash-fold tiered pricing (PRD §3.3)
WF_TIER1_KG = 5.0
WF_RATE1_CENTS_PER_KG = 400
WF_RATE2_CENTS_PER_KG = 300
DRYCLEAN_RATE_CENTS_PER_PIECE = 900
RUSH_MULTIPLIER = 1.25

# Customer risk scoring (PRD §3.8)
LOST_GARMENT_RISK_POINTS = 15
SETTLED_CLAIM_RISK_POINTS = 25
CUSTOMER_BLOCK_THRESHOLD = 100

# Order risk flag (PRD §3.8)
ORDER_RISK_THRESHOLD = 12

# Claim settlement waterfall (PRD §3.10)
PER_ITEM_CAP_CENTS = 20000
DEPRECIATION_PCT = 0.20
ORDER_PAYOUT_CEILING_CENTS = 30000

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# Stable test clock anchor used by deterministic SLA/locker setups.
TEST_CLOCK_UTC = "2026-06-01T08:00:00Z"
