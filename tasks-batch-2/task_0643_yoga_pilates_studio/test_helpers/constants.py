"""Domain thresholds — numeric constants from the Yoga & Pilates Studio PRD."""

# Membership / cycle (PRD §3.3, §3.8)
CYCLE_LENGTH_DAYS = 30          # cycle_end = cycle_start + 30 days
DAYS_PER_MONTH = 30            # daily-rate denominator for renewal proration

# Late-cancel / no-show fees (PRD §3.6, §3.7)
LATE_CANCEL_WINDOW_HOURS = 12   # cutoff = start_utc - 12h; >= cutoff is LATE
LATE_CANCEL_BASE_CENTS = 1500   # base late-cancel fee
NO_SHOW_BASE_CENTS = 2500       # base no-show fee

# Repeat-offender surcharge tiers (PRD §3.7)
REPEAT_OFFENDER_TIER1 = 2       # prior strikes >= 2 -> +25% surcharge
REPEAT_OFFENDER_TIER2 = 4       # prior strikes >= 4 -> +50% surcharge
SURCHARGE_TIER1_PCT = 0.25
SURCHARGE_TIER2_PCT = 0.50

# Account standing (PRD §2.9)
NO_SHOW_SUSPEND_THRESHOLD = 3   # no_show_strike_count >= 3 -> SUSPENDED

# Freeze cap (PRD §3.4)
FREEZE_MAX_DAYS_PER_CYCLE = 21  # max cumulative frozen days per cycle

# Workshop room buffer (PRD §3.9)
WORKSHOP_BUFFER_MINUTES = 30    # buffer-inclusive non-overlap on each side

# Pagination defaults (PRD §2.3)
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# Logical clock default at server startup (PRD §2.4)
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"

# Sentinel for unlimited membership credits (PRD §3.3)
UNLIMITED_CREDITS = -1
