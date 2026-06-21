"""Domain thresholds — numeric constants from the PRD calculations (§2.7, §3.7, §3.8)."""

# Occupancy tier factors for cost-share (PRD §3.7).
TIER_FULL_THRESHOLD = 4      # N >= 4 -> full-vanpool discount
TIER_FULL_FACTOR = 0.80
TIER_MID_THRESHOLD = 3       # N == 3
TIER_MID_FACTOR = 0.90
TIER_LOW_FACTOR = 1.00       # N <= 2

# Reliability event weights (PRD §3.8).
COMPLETION_WEIGHT = 2.0
NO_SHOW_WEIGHT = -15.0
LATE_CANCEL_WEIGHT = -6.0
GRH_OVERUSE_WEIGHT = -4.0
SCORE_FLOOR = 0.0
SCORE_CEIL = 100.0
RELIABILITY_BASE = 100.0

# Reservation reliability gate (PRD §3.6): stored score strictly below 70.0 blocks.
RELIABILITY_GATE = 70.0

# Rider double-booking buffer (PRD §3.6): fifteen minutes on each side.
RIDER_BUFFER_MIN = 15

# Match-score weights (PRD §3.4).
DAY_WEIGHT = 10.0
SEAT_ROOM_WEIGHT = 1.0
DRIVER_RELIABILITY_WEIGHT = 0.05

# GRH default (PRD §3.1).
GRH_MAX_EVENTS_DEFAULT = 4

# MatchRequest expiry window (PRD §3.4): older than fourteen days.
MATCH_REQUEST_EXPIRY_DAYS = 14
