"""Domain thresholds — numeric constants from PRD calculations and config defaults."""

# Credit-pack tiered pricing (PRD §3.8)
PROCESSING_FEE_CENTS = 300
TIER_5_PCT = 0.05
TIER_10_PCT = 0.10
TIER_20_PCT = 0.15

# Membership freeze proration (PRD §3.7)
CALENDAR_DENOMINATOR_DAYS = 30

# No-show strike scoring (PRD §3.6)
STRIKE_WINDOW_DAYS = 90
SUSPENSION_THRESHOLD = 5
POINTS_NO_SHOW = 2
POINTS_LATE_CANCEL = 1

# Intro assessment weights (PRD §3.4)
W_SHOULDER = 0.30
W_HIP = 0.30
W_SPINE = 0.25
W_ANKLE = 0.15
TIER_ADVANCED_MIN = 80
TIER_INTERMEDIATE_MIN = 60

# Recurring series bounds (PRD §3.9)
OCCURRENCE_MIN = 1
OCCURRENCE_MAX = 26

# Location config defaults (PRD §3.1)
DEFAULT_OPEN_MINUTE = 540
DEFAULT_CLOSE_MINUTE = 1260
DEFAULT_BUFFER_MINUTES = 15
DEFAULT_NO_SHOW_FEE_CENTS = 5000
DEFAULT_LATE_CANCEL_PCT = 0.50
DEFAULT_CANCEL_WINDOW_HOURS = 12

# Logical clock startup default (PRD §2.8)
CLOCK_DEFAULT_UTC = "2026-04-01T00:00:00Z"
