"""Domain constants (PRD §3 / SCAFFOLD §1.3 calculations)."""

# garment_line_price (PRD §3.3)
WF_TIER1_KG = 5.0
WF_RATE1_CENTS_PER_KG = 400
WF_RATE2_CENTS_PER_KG = 300
DRYCLEAN_RATE_CENTS_PER_PIECE = 900
RUSH_MULTIPLIER = "1.25"  # used as Decimal string

# customer_risk_score (PRD §3.8)
LOST_GARMENT_RISK_POINTS = 15
SETTLED_CLAIM_RISK_POINTS = 25
CUSTOMER_BLOCK_THRESHOLD = 100

# order_risk_flag (PRD §3.8)
ORDER_RISK_THRESHOLD = 12

# subscription_billing (PRD §3.6)
# inclusion always valued at tier-1 rate
# WF_RATE1_CENTS_PER_KG reused

# claim_settlement (PRD §3.10)
PER_ITEM_CAP_CENTS = 20000
DEPRECIATION_PCT = "0.20"  # Decimal string
ORDER_PAYOUT_CEILING_CENTS = 30000

# SLA durations in hours (PRD §3.4: standard is the longer, rush is the shorter).
# PRD/scaffold leave exact magnitudes unspecified; chosen so standard > rush.
STANDARD_SLA_HOURS = 48
RUSH_SLA_HOURS = 24

# Appeals (PRD §3.10): max appeals a claim may exhaust before final denial.
MAX_APPEALS = 2

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Roles (PRD §2.1)
ROLES = ["PlatformAdmin", "Customer", "DispatchAgent", "PlantOperator", "ClaimsAdjuster"]
