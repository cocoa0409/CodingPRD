"""Domain thresholds — numeric constants from the Community Solar PRD calculations (§3)."""

# Tiered program fee (PRD §3.10)
CARVE_OUT_FEE_RATE = 0.05
TIER1_CENTS = 5000      # gross <= 5000 → multiplier 1.00
TIER2_CENTS = 20000     # 5000 < gross <= 20000 → multiplier 0.90; > 20000 → 0.80

# Churn-risk score weights (PRD §3.2)
W_SUSPENDED = 40
W_OPEN_DISPUTE = 35
W_LOW_INCOME = 10
W_RECENT_CANCEL = 50
CHURN_SCORE_CAP = 100

# True-up overproduction (PRD §3.12)
ROLLOVER_CAP_KWH = 2000
CAP_KWH_PER_KW = 50

# REC minting (PRD §3.10)
KWH_PER_REC = 1000

# Project defaults (PRD §2.6)
DEFAULT_CARVE_OUT_PCT = 0.40
DEFAULT_PROGRAM_FEE_RATE = 0.10

# Usage cap (PRD §3.3): requested_share_kw * 1000 <= annual_usage_kwh
USAGE_KWH_PER_KW = 1000

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# A generous annual-usage figure so the usage cap never accidentally bites
# in setups not specifically testing it.
HIGH_ANNUAL_USAGE = 1_000_000
