"""Domain thresholds — numeric constants from PRD calculations (§2, §3.4, §3.6, §3.7, §3.9)."""

# Billing / late fee (PRD §3.4)
INVOICE_DUE_DAYS = 30
DELINQUENCY_GRACE_DAYS = 15
LATE_TIER1_RATE = 0.05          # days_past_due <= 30
LATE_TIER2_RATE = 0.10          # days_past_due <= 60
LATE_TIER3_RATE = 0.15          # days_past_due > 60
SIZE_MULTIPLIER = {"SMALL": 1.00, "MEDIUM": 1.25, "LARGE": 1.50, "JUMBO": 2.00}
MIN_LATE_FEE_CENTS = 2500
MAX_LATE_FEE_CENTS = 25000

# Invoice charge rounding (PRD §3.4)
INSURANCE_RIDER_ANNUAL_RATE_BP = 150         # 1.50% of declared contents value per year
PRECIOUS_METAL_SURCHARGE_ANNUAL_RATE_BP = 50  # 0.50% of item declared value per year

# Surrender refund (PRD §3.6)
DAYS_PER_MONTH_APPROX = 30
DAYS_PER_YEAR = 365

# Proceeds waterfall (PRD §3.9)
ADMIN_FEE_CENTS = 5000
DEFAULT_DRILLING_FEE_CENTS = 15000

# Dual control (PRD §3.7)
REQUIRED_WITNESSES = 2

# Branch room occupancy (PRD §3.7)
CLEANUP_BUFFER_MINUTES = 30

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Logical clock default (PRD §2.4)
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Convenience test defaults
MEDIUM_ANNUAL_RATE_CENTS = 24000
