"""Domain thresholds and constants named in the PRD (§2.5, §3.2, §3.4, §3.6, §3.10)."""

# Logical clock startup default (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Referral response deadline in calendar days (PRD §3.2).
REFERRAL_RESPONSE_DAYS = 15

# RCA completion deadline in calendar days from complaint receipt (PRD §3.4).
RCA_DEADLINE_DAYS = 30

# Retention period after terminal transition (PRD §3.5).
RETENTION_YEARS = 5

# Restitution approval authority cap in cents (PRD §3.6).
RESTITUTION_AUTHORITY_CAP_CENTS = 2500000

# High-value claim threshold in cents for the timeliness score bonus (PRD §3.8).
HIGH_VALUE_CLAIM_CENTS = 1000000

# Early-warning snapshot thresholds (PRD §3.10).
EW_MIN_COUNT = 3
EW_RATE_BPS = 5000
EW_OPEN_COUNT = 10

# Product posture thresholds (PRD §3.10).
POSTURE_WATCH_SUBSTANTIATED = 3
POSTURE_FREEZE_SUBSTANTIATED = 5

# Fixed holiday set used by the business-day age calculation (PRD §3.5).
HOLIDAYS = ["2026-01-01", "2026-07-04", "2026-12-25"]

# Full basis-points rate meaning "the full amount" on a restitution line (PRD §3.6).
FULL_RATE_BPS = 10000
