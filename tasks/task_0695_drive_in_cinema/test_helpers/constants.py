"""Domain thresholds — numeric constants from PRD calculations and policies."""

# Concession order service fee (PRD §3.8): 5% of subtotal, rounded once.
SERVICE_FEE_PCT = 0.05

# Voluntary-cancel refund policy tiers (PRD §3.6), by hours-before-start.
TIER_48H_PCT = 1.00
TIER_24H_PCT = 0.50
TIER_2H_PCT = 0.25
TIER_LATE_PCT = 0.00

# Venue operational defaults (PRD §3.1).
DEFAULT_TURNAROUND_BUFFER_MINUTES = 30
DEFAULT_NO_SHOW_GRACE_MINUTES = 15
DEFAULT_TIMEZONE = "UTC"

# Showtime pricing defaults (PRD §3.3).
DEFAULT_INCLUDED_OCCUPANTS = 2
DEFAULT_PER_EXTRA_PERSON_CENTS = 0
DEFAULT_DOUBLE_FEATURE_SURCHARGE_CENTS = 0

# Check-in window: no earlier than 60 minutes before start_utc (PRD §3.5).
CHECK_IN_WINDOW_MINUTES = 60

# Logical clock startup default (PRD §2.8).
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"

# Pagination bounds (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
