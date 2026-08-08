"""Domain thresholds — numeric constants from the PRD's accounting rules."""

# DSMT unit rounding (PRD §2.8)
UNIT_MINUTES = 30
HOURS_PER_UNIT = 0.5

# Benefit-hour caps (PRD §2.8 / §3.3)
INITIAL_BENEFIT_HOURS = 10.0
FOLLOWUP_BENEFIT_HOURS = 2.0

# Per-unit billing rates in cents (PRD §3.7)
INDIVIDUAL_UNIT_RATE_CENTS = 5000
GROUP_UNIT_RATE_CENTS = 1500

# A1c projection (PRD §3.9)
A1C_REDUCTION_PER_HOUR = 0.1
A1C_FLOOR = 6.5

# No-show suspension (PRD §3.6)
NO_SHOW_SUSPENSION_THRESHOLD = 3

# Device loan window (PRD §3.8)
DEVICE_LOAN_DAYS = 90

# Room buffer (PRD §3.5)
ROOM_BUFFER_MINUTES = 15

# Startup logical-clock default (PRD §2.5)
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"
