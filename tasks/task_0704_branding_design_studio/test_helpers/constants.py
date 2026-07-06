"""Domain thresholds — numeric constants from PRD calculations and global rules."""

# Late-fee tiers on overdue invoices (PRD §3.6).
LATE_TIER1_RATE = 0.015   # <= 30 days overdue
LATE_TIER2_RATE = 0.030   # > 30 days overdue
LATE_TIER1_MAX_DAYS = 30  # inclusive boundary: exactly 30 days stays tier-1

# Retainer care-cycle overage tiers (PRD §3.10).
TIER1_HOURS_CAP = 5       # first five overage hours are tier-1

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# Logical-clock startup default (PRD §2.11).
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"
