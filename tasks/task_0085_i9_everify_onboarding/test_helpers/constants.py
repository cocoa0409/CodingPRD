"""Domain thresholds — numeric constants from the PRD's deadline and scoring rules."""

# Business-day arithmetic (PRD §2.6, §3.2).
BUSINESS_DAYS = 3
FEDERAL_HOLIDAYS_2026 = [
    "2026-01-01",
    "2026-01-19",
    "2026-02-16",
    "2026-05-25",
    "2026-06-19",
    "2026-07-03",
    "2026-09-07",
    "2026-11-11",
    "2026-11-26",
    "2026-12-25",
]

# STEM OPT cap-gap ceiling (PRD §3.6).
CAP_GAP_CEILING_DAYS = 180

# Receipt resolution window (PRD §3.3).
RECEIPT_RESOLUTION_DAYS = 90

# TNC referral window (PRD §3.4).
TNC_REFERRAL_BUSINESS_DAYS = 10

# Compliance-risk score weights (PRD §3.8).
W_OVERDUE = 40
W_EVERIFY_LATE = 25
W_OPEN_TNC = 20
W_UNRESOLVED_RECEIPT = 15
W_EXPIRING_AUTH = 10
RISK_CLAMP_MAX = 100
EXPIRING_WINDOW_DAYS = 30

# Pagination bounds (PRD §2.3).
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
