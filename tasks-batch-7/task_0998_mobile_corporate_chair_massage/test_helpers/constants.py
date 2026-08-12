"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Travel fee (PRD §3.7): high-volume discount on the settled variant.
HIGH_VOLUME_SESSION_THRESHOLD = 20
HIGH_VOLUME_DISCOUNT_PCT = 0.20

# Cancellation fee tiers, in whole hours until event start (PRD §3.7).
CANCELLATION_TIER1_HOURS = 24
CANCELLATION_TIER2_HOURS = 72
CANCELLATION_TIER3_HOURS = 168

# Satisfaction credit tiers on average rating x100 (PRD §3.8).
SATISFACTION_TIER_LOW_X100 = 200
SATISFACTION_TIER_MID_X100 = 300

# Payout line computation (PRD §3.7).
MINUTES_PER_HOUR = 60

# Logical clock boot value (PRD §2.4).
DEFAULT_LOGICAL_CLOCK = "2026-05-01T00:00:00Z"

# Pagination defaults (PRD §2.3).
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100
