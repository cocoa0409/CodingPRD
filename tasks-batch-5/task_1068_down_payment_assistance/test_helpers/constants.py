"""Domain thresholds — numeric constants from the PRD calculations."""

# Assistance minimum-contribution tiers (PRD Section 3.4), selected from ami_pct.
#   ami_pct <= 50.00            -> 0
#   50.00 < ami_pct <= 65.00    -> 1 percent
#   65.00 < ami_pct <= 80.00    -> 3 percent
TIER_PCT_LOW_MAX_AMI = 50
TIER_PCT_MID_MAX_AMI = 65
TIER_PCT_HIGH_MAX_AMI = 80
TIER_PCT_MID = 1
TIER_PCT_HIGH = 3

# Certificate validity (PRD Section 3.3): issued_at + 365 days.
CERT_VALIDITY_DAYS = 365

# Enrollment scheduling buffer (PRD Section 3.3).
SESSION_BUFFER_MINUTES = 30

# Program defaults (PRD Section 3.1).
DEFAULT_RECAPTURE_TERM_MONTHS = 120
DEFAULT_APPRECIATION_SHARE_PCT = 30

# Closing occupation window default (PRD Section 3.6).
DEFAULT_WINDOW_DAYS = 7

# Logical clock startup default (PRD Section 2.6).
CLOCK_STARTUP_DEFAULT = "2026-07-01T00:00:00Z"

# Pagination defaults (PRD Section 2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
