"""Domain thresholds — numeric constants from PRD calculations (Section 3)."""

# Late-fee assessment (PRD Section 3.7)
FLAT_FEE_CENTS = 2500
MIN_FEE_CENTS = 2500
MAX_FEE_CENTS = 7500
MAX_TOTAL_LATE_FEE_CENTS = 30000

# Late-fee day tiers (PRD Section 3.7)
LATE_FEE_TIER_1_PCT = 0.02  # days_late in [1, 10)
LATE_FEE_TIER_2_PCT = 0.04  # days_late in [10, 30)
LATE_FEE_TIER_3_PCT = 0.06  # days_late >= 30

# Delinquency evaluation (PRD Section 3.8)
DELINQUENCY_COUNT_LIMIT = 3
DELINQUENCY_AMOUNT_LIMIT = 150000

# Refund proration SCHEDULE_BASED brackets (PRD Section 3.9)
BRACKET_0_DAYS = 7      # days_elapsed <= 7   -> retained 0%
BRACKET_25_DAYS = 21    # 8..21               -> retained 25%
BRACKET_50_DAYS = 42    # 22..42              -> retained 50%
# days_elapsed > 42 -> retained 100%

# Plan template ranges (PRD Section 3.1)
INSTALLMENT_COUNT_MIN = 1
INSTALLMENT_COUNT_MAX = 12
DOWN_PAYMENT_PCT_MIN = 0.0
DOWN_PAYMENT_PCT_MAX = 0.5
DEFAULT_LATE_FEE_GRACE_DAYS = 3

# Pagination defaults (PRD Section 2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Canonical fixture calendar (Term FALL2026 spans 122 days, 2026-09-01..2026-12-31)
TERM_START = "2026-09-01T00:00:00.000Z"
TERM_END = "2026-12-31T00:00:00.000Z"
ENROLL_OPEN = "2026-08-01T00:00:00.000Z"
ENROLL_CLOSE = "2026-09-30T00:00:00.000Z"
TERM_TOTAL_DAYS = 122
DEFAULT_CLOCK = "2026-09-15T00:00:00.000Z"
