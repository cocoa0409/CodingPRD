"""Domain thresholds — numeric constants from PRD calculations and rules."""

# Geographic / arrival-estimation constants (PRD §2.5).
EARTH_RADIUS_MILES = 3958.7613
AVG_SPEED_MPH = 40

# Dispatch selection / re-offer constants (PRD §3.6, §3.7).
MAX_DISPATCH_RADIUS_MILES = 50
MAX_DISPATCH_ATTEMPTS = 3

# Annual-period length (PRD §3.2).
ANNUAL_PERIOD_DAYS = 365

# A clock instant used by time-sensitive fixtures (PRD §2.10). Any pinned UTC
# value works; the design index uses 2026-06-01 noon as the canonical anchor.
DEFAULT_CLOCK = "2026-06-01T12:00:00Z"
