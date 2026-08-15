"""Domain thresholds — numeric constants from PRD calculations (sections 2.9, 3.7, 3.8)."""

# Rework penalty ledger increments (PRD 2.9)
REJECT_PENALTY = 10
DENY_PENALTY = 5
EXPIRY_PENALTY = 7
DELIVERY_EXCEPTION_PENALTY = 3
LATE_DELIVERY_PENALTY = 5
LOST_PENALTY = 8

# Posture thresholds; comparisons are inclusive on the lower bound (PRD 2.9)
WATCH_THRESHOLD = 20
ESCALATED_THRESHOLD = 40

# Travel-time pay tiers (PRD 3.8)
TIER1_CAP_MIN = 60
TIER2_CAP_MIN = 120
TIER2_MULTIPLIER_NUM = 5   # 1.25x
TIER2_MULTIPLIER_DEN = 4
TIER3_MULTIPLIER_NUM = 3   # 1.5x
TIER3_MULTIPLIER_DEN = 2

# Mileage pay: ordinary round-trip commute factor (PRD 3.8)
COMMUTE_ROUND_TRIP_FACTOR = 2

# Logical clock: reads exactly 2026-08-01T00:00:00Z before any set call (PRD 1)
CLOCK_INITIAL_UTC = "2026-08-01T00:00:00Z"

DEFAULT_TIMEZONE = "America/Chicago"
