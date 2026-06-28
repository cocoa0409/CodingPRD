"""Domain thresholds — numeric constants from the PRD's pricing and lifecycle rules."""

# Late-fee rule (PRD §3.7): ten-minute grace, $1/min beyond grace, capped at $25.
LATE_GRACE_MINUTES = 10
LATE_FEE_PER_MIN_CENTS = 100
LATE_FEE_CAP_CENTS = 2500

# No-show suspension (PRD §3.8): three strikes suspends the member.
STRIKE_SUSPEND_THRESHOLD = 3

# Tip split (PRD §3.10): standalone keeps 70% direct, event block keeps 50%.
TIP_DIRECT_PCT_STANDALONE = 0.70
TIP_DIRECT_PCT_EVENT = 0.50

# Commission tiers (PRD §3.10): base rate by tier, event cap at 40%.
JUNIOR_RATE = 0.35
SENIOR_RATE = 0.45
MASTER_RATE = 0.55
EVENT_RATE_CAP = 0.40

# Retail commission default (PRD §3.12).
DEFAULT_RETAIL_COMMISSION_PCT = 0.10

# Event-block deposit (PRD §3.11): $20/head, $100 bridal surcharge.
DEPOSIT_PER_HEAD_CENTS = 2000
BRIDAL_SURCHARGE_CENTS = 10000

# Chair turnover buffer default (PRD §3.3).
DEFAULT_TURNOVER_BUFFER_MINUTES = 10

# Default blowout credit cost per service (PRD §3.1).
DEFAULT_BLOWOUT_CREDIT_COST = 1

THRESHOLDS = {
    "LATE_GRACE_MINUTES": LATE_GRACE_MINUTES,
    "LATE_FEE_PER_MIN_CENTS": LATE_FEE_PER_MIN_CENTS,
    "LATE_FEE_CAP_CENTS": LATE_FEE_CAP_CENTS,
    "STRIKE_SUSPEND_THRESHOLD": STRIKE_SUSPEND_THRESHOLD,
    "TIP_DIRECT_PCT_STANDALONE": TIP_DIRECT_PCT_STANDALONE,
    "TIP_DIRECT_PCT_EVENT": TIP_DIRECT_PCT_EVENT,
    "JUNIOR_RATE": JUNIOR_RATE,
    "SENIOR_RATE": SENIOR_RATE,
    "MASTER_RATE": MASTER_RATE,
    "EVENT_RATE_CAP": EVENT_RATE_CAP,
    "DEPOSIT_PER_HEAD_CENTS": DEPOSIT_PER_HEAD_CENTS,
    "BRIDAL_SURCHARGE_CENTS": BRIDAL_SURCHARGE_CENTS,
}
