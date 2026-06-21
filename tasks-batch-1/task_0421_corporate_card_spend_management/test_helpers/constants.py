"""Domain thresholds — numeric constants drawn from the PRD's calculations.

Generic NON_EXISTENT_UUID comes from the framework (re-exported via __init__).
"""

# PRD §3.3 / §3.4 — receipt-required threshold ($75) and match tolerance ($1).
RECEIPT_REQUIRED_THRESHOLD_CENTS = 7500
RECEIPT_TOLERANCE_CENTS = 100

# PRD §3.6 — statement due offset and the CREDIT minimum-payment floor ($25).
STATEMENT_DUE_DAYS = 21
MIN_PAYMENT_FLOOR_CENTS = 2500

# PRD §3.4 — per-transaction cashback cap ($50).
MAX_REWARD_PER_TXN_CENTS = 5000

# PRD §3.7 — per-claim reimbursement cap ($2,000).
REIMBURSEMENT_CAP_CENTS = 200000

# PRD §3.9 — CARD-scope authorization buffer gap (2 days).
AUTH_BUFFER_DAYS = 2

# Default company-level cashback rate (100 bps == 1.0%).
DEFAULT_REWARD_RATE_BPS = 100
