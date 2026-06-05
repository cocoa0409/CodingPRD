"""Domain thresholds — numeric constants from PRD calculations."""

# Financing debt-to-income gate (PRD Section 3.7).
MAX_DTI = 0.43
MONTHLY_PAYMENT_FACTOR = 0.005

# Commission defaults used throughout tests (PRD Section 2.8).
DEFAULT_TOTAL_COMMISSION_PCT = 0.06
DEFAULT_COOP_SPLIT_PCT = 0.50

# Net-to-seller seller concession is fixed at 0 cents (PRD Section 3.9).
SELLER_CONCESSION_CENTS = 0

# Lockbox showing buffer default (PRD Section 2.9).
DEFAULT_TURNAROUND_MINUTES = 30
