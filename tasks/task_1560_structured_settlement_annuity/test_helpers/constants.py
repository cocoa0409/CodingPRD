"""Domain thresholds — numeric constants from PRD rules (§2.3, §2.4, §3.4, §3.6, §3.7)."""

# The logical clock before any clock-setting call (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Check staling: an ISSUED check goes STALE_DATED strictly past 180 days (PRD §3.4).
STALE_CHECK_DAYS = 180

# A COURT_APPROVED petition expires strictly past 60 days after court_order_date (PRD §3.6).
PETITION_EFFECTUATION_WINDOW_DAYS = 60

# A with-prejudice denial bars refiling until one year after the order (PRD §3.6).
REFILE_BAR_DAYS = 365

# HARDSHIP commutation fee: 3% of the present-value total, capped (PRD §3.7).
HARDSHIP_FEE_PCT = 0.03
HARDSHIP_FEE_CAP_CENTS = 25000

# Pagination envelope (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
