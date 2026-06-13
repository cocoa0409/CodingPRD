"""Domain thresholds — numeric constants from the PRD calculations (§2.6, §3.2-§3.7)."""

# Preflight minimums (PRD §3.3): resolution checked before bleed; boundary inclusive.
MIN_DPI = 150
MIN_BLEED_MM = 3

# Loyalty discount basis points by committed tier (PRD §3.6).
SILVER_DISCOUNT_BPS = 500   # 5%
GOLD_DISCOUNT_BPS = 1000    # 10%

# Committed loyalty score weighting + tier thresholds (PRD §3.7).
W_COUNT = 1.0
W_SPEND = 0.5               # lifetime_paid_cents / 10000 (dollars/100) weighted by 0.5
SILVER_SCORE_THRESHOLD = 3.0
GOLD_SCORE_THRESHOLD = 6.0

# Pagination (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# A syntactically valid UUID that is never minted by the server.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
