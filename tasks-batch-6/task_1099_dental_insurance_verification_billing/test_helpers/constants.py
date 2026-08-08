"""Domain thresholds — numeric constants from PRD calculations."""

# PRD §2.4 / §3.2: a verification expires 30 days after verified_at.
VERIFICATION_VALIDITY_DAYS = 30

# PRD §3.5 / §3.9: frequency window is the trailing 365-day window.
FREQUENCY_WINDOW_DAYS = 365

# PRD §3.1 / §3.6 / §3.9: collections threshold in cents.
COLLECTIONS_THRESHOLD_CENTS = 50000

# PRD §3.8: 15-day grace window before a membership is overdue.
MEMBERSHIP_GRACE_DAYS = 15

# PRD §3.8: two consecutive overdue periods cancel the membership.
MAX_PAST_DUE_PERIODS = 2

# PRD §3.6: appeals capped at 2.
APPEAL_LIMIT = 2

# Default plan coinsurance percentages (PRD §3.1 / §3.5).
DEFAULT_PREVENTIVE_PCT = 100
DEFAULT_BASIC_PCT = 80
DEFAULT_MAJOR_PCT = 50

# PRD §2.4: server default logical clock before any set.
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
