"""Domain thresholds — numeric constants from PRD calculations and policies."""

# Strike accumulation / suspension (PRD 2.9)
STRIKE_WINDOW_DAYS = 30
STRIKE_SUSPEND_THRESHOLD = 3

# Shoe rental (PRD 3.7)
SHOE_RENTAL_FEE_CENTS = 500

# Retail order volume discount tiers (PRD 3.10)
TIER1_MIN_QTY = 3
TIER1_PCT = 0.05
TIER2_MIN_QTY = 6
TIER2_PCT = 0.10

# Studio penalty-policy defaults (PRD 3.1)
DEFAULT_LATE_CANCEL_WINDOW_MINUTES = 720
DEFAULT_LATE_CANCEL_FEE_CENTS = 2000
DEFAULT_NO_SHOW_FEE_CENTS = 3000

# Waitlist capacity default (PRD 3.2)
DEFAULT_WAITLIST_CAPACITY = 10

# MEMBERSHIP remaining-credits sentinel (PRD 3.3)
MEMBERSHIP_REMAINING_SENTINEL = -1

# Server startup default logical clock (PRD 2.4)
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"

# Pagination defaults (PRD 2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
