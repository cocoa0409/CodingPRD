"""Domain thresholds — numeric constants from the PRD calculations and global rules.

NON_EXISTENT_UUID comes from the framework. Values here are the literals named in
PRD §2.7, §2.9, §3.2, §3.5, and §3.7.
"""

# IAB counted-download minimum (PRD §3.7: "the IAB minimum of 1,048,576 bytes (one mebibyte)").
IAB_MIN_BYTES = 1_048_576

# Transcode retry ceiling (PRD §3.2: "the maximum of three attempts").
MAX_TRANSCODE_ATTEMPTS = 3

# MID_ROLL silence buffer on each side (PRD §3.6: "a one-second buffer on each side").
MID_ROLL_BUFFER_MS = 1000

# Pricing multipliers (PRD §3.5).
PREMIUM_MULTIPLIER = 1.25
HIGH_FILL_MULT = 1.20
MID_FILL_MULT = 1.10
LOW_FILL_MULT = 1.00

# Placement cost floor (PRD §3.5: "the placement floor of 100 cents").
MIN_PLACEMENT_CENTS = 100

# Logical clock startup default (PRD §2.9).
CLOCK_DEFAULT_UTC = "2026-01-01T00:00:00Z"

# Default publisher revenue share (PRD §3.1: "When revenue_share_pct is omitted it defaults to 0.70").
DEFAULT_REVENUE_SHARE_PCT = 0.70
