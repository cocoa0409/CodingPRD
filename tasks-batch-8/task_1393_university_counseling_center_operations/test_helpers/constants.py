"""Domain thresholds — numeric constants from PRD sections 3.3-3.9."""

# Intake risk scoring (PRD section 3.3)
ATTEMPT_MULTIPLIER = 3
IDEATION_BONUS = 15
MAX_POINTS = 100
CRITICAL_MIN = 60
HIGH_MIN = 35
MODERATE_MIN = 15
PHQ9_MAX = 27
GAD7_MAX = 21

# Session entitlement derivation (PRD section 3.4)
MIN_LIMIT = 2
DEFAULT_INTERSESSION_BASE = 6
EXEMPTION_BONUS_SESSIONS = 4

# Billing (PRD section 3.5)
RATE_PER_MINUTE = 250
LATE_CANCEL_FEE_CENTS = 5000
NO_SHOW_FEE_CENTS = 7500
INSURANCE_CENTER_SHARE = 0.80
SPLIT_CENTER_SHARE = 0.50

# Referral windows (PRD section 3.9)
ENGAGEMENT_CONFIRM_DAYS = 14
REFERRAL_LAPSE_DAYS = 30

# Capacity report (PRD section 3.9)
WEEKS_IN_TERM = 15

# Logical clock (PRD section 2.5)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
EPOCH_ANCHOR_ISO = "1970-01-01T00:00:00Z"

# Default term used across scenarios
DEFAULT_TERM = "2026-FALL"
