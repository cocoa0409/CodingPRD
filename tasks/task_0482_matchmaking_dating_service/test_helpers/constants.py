"""Domain thresholds — numeric constants from the PRD's calculations and gates."""

# Compatibility scoring (PRD §3.3)
COMPATIBILITY_WEIGHTS = {
    "W_ATTR": 0.40,
    "W_PREF": 0.35,
    "W_LOC": 0.15,
    "W_ACT": 0.10,
}
COMPATIBILITY_THRESHOLD = 70  # introduction admitted when score >= 70.00

# Guarantee credit costs (PRD §3.4)
PRIORITY_COST = 2
STANDARD_COST = 1
PROMO_COST = 0

# Coaching discipline (PRD §3.7)
COACHING_STRIKE_LIMIT = 3
STRIKE_DECAY_DAYS = 30
COACHING_BUFFER_MIN = 30  # minutes; closed buffer between coaching and a date

# Refund proration (PRD §3.9)
DAYS_PER_MONTH = 30

# Convenient default clock instant used across setups.
DEFAULT_CLOCK = "2026-06-01T00:00:00Z"
