"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Vendor collection discount (PRD §3.3)
VENDOR_DISCOUNT_BPS = 150
VENDOR_DISCOUNT_CAP_CENTS = 100000

# Assessment penalty & interest (PRD §3.5)
NEGLIGENCE_PENALTY_BPS = 2500          # AUDIT_DEFICIENCY, 25%, no cap
LATE_FILING_PENALTY_BPS = 1000         # LATE_FILING, 10%
LATE_FILING_PENALTY_CAP_CENTS = 500000
MONTHLY_INTEREST_BPS = 100             # 1% per 30-day month, on base+penalty
DAYS_PER_MONTH = 30

# Refund interest (PRD §3.7)
REFUND_GRACE_DAYS = 90                 # STATUTORY_DELAY / TAXPAYER_ERROR grace
DAILY_INTEREST_BPS = 3

# Nexus determination (PRD §3.5)
NEXUS_THRESHOLD_CENTS = 10000000

# Appeal window (PRD §3.6)
APPEAL_WINDOW_DAYS = 60

# Logical clock startup default (PRD §2.5)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
