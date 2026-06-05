"""Domain thresholds — numeric constants from PRD calculations and global rules."""

# Temporal constants (PRD §3.6, §3.5).
SLOT_MINUTES = 12            # confirmed booking occupancy window [start, start+12min)
TEE_INTERVAL_MINUTES = 8     # minimum spacing between TeeTimes on the same course

# Score differential (PRD §2.7).
STANDARD_SLOPE = 113

# Official-index caps (PRD §3.4).
SOFT_CAP_THRESHOLD = 3.0
SOFT_CAP_FACTOR = 0.5
HARD_CAP_CEILING = 5.0

# Course defaults (PRD §2.8).
DEFAULT_PEAK_START_HOUR = 7
DEFAULT_PEAK_END_HOUR = 15
DEFAULT_MEMBER_DISCOUNT_PCT = 0.20

# Group-type capacities (PRD §3.5).
TWOSOME_CAPACITY = 2
FOURSOME_CAPACITY = 4
