"""Domain thresholds and money constants from the PRD's calculation rules (§3)."""

# Logical clock (PRD §2.5): startup default reading.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Rate card (PRD §3.1), cents.
NANO_BASE_CPM = 1500
MICRO_BASE_CPM = 2200
MID_BASE_CPM = 3000
MACRO_BASE_CPM = 4500
MIN_FLAT_FEE_CENTS = 50000

# Deal fee computation (PRD §3.4).
MULTI_DELIVERABLE_DISCOUNT = 0.10
WHITELIST_PER_DELIVERABLE_CENTS = 75000
EXCL_TIER1_MAX = 500000
EXCL_TIER2_MAX = 2000000

# Invoice computation (PRD §3.8).
SERVICE_FEE_PCT = 0.05
INVOICE_NET_DAYS = 30

# Performance bonus (PRD §3.7), cents / views / bps.
BONUS_T1_VIEWS = 250000
BONUS_T1_CENTS = 25000
BONUS_T2_VIEWS = 1000000
BONUS_T2_CENTS = 100000
BONUS_T3_VIEWS = 5000000
BONUS_T3_CENTS = 400000
BONUS_ENG_KICKER_BPS = 400
BONUS_KICKER_MULT = 1.25

# Commission split (PRD §3.8), cents / basis points.
COMMISSION_T1_MAX = 5000000
COMMISSION_T2_MAX = 20000000
COMMISSION_RATE_T1_BPS = 2000
COMMISSION_RATE_T2_BPS = 1500
COMMISSION_RATE_T3_BPS = 1200

# Late fee accrual (PRD §3.8).
LATE_FEE_PCT = 0.015
LATE_FEE_PERIOD_DAYS = 7

# Payout schedule (PRD §3.8).
PAYOUT_NET_DAYS = 7

# Caps and limits (PRD §3.1, §3.3, §3.4, §3.5, §3.6, §3.9).
STRIKE_LIMIT = 3
MAX_DISCLOSURE_RECHECKS = 2
MAX_RESHOOTS_PER_DELIVERABLE = 1
MAX_PITCH_NEGOTIATION_ROUNDS = 3
MAX_DEAL_NEGOTIATION_ROUNDS = 4
MIN_PUBLISH_GAP_HOURS = 48

# Opaque operator identifiers recorded as actor stamps (PRD §2.1, §2.10).
BM_USER_ID = "bm-operator-1"
BM_USER_ID_2 = "bm-operator-2"
CO_USER_ID = "co-operator-1"
FIN_USER_ID = "fin-operator-1"
FIN_USER_ID_2 = "fin-operator-2"
TM_USER_ID = "tm-operator-1"
ADMIN_USER_ID = "platform-admin-1"
