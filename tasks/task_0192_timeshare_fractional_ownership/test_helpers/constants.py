"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Season multipliers applied to points_per_week_base (PRD §3.1, §3.4).
SEASON_MULT = {
    "PLATINUM": 1.50,
    "GOLD": 1.00,
    "SILVER": 0.60,
}

# Reservation pricing (PRD §3.4).
EARLY_BIRD_DAYS = 180
EARLY_BIRD_DISCOUNT = 0.10

# Maintenance fee proration (PRD §3.7, §3.9).
DAYS_IN_YEAR = 365

# Delinquency late-charge engine (PRD §3.8).
LATE_RATE = 0.05

# Exchange credit divisors by network (PRD §3.6).
CREDIT_DIVISOR = {
    "RCI": 100,
    "II": 120,
}

# Canonical resort governance defaults (PRD §3.1).
DEFAULT_RESCISSION_DAYS = 7
DEFAULT_BORROW_SURCHARGE_PCT = 0.10
DEFAULT_DELINQUENCY_GRACE_DAYS = 30
DEFAULT_FORECLOSURE_THRESHOLD_PERIODS = 2
DEFAULT_CURRENT_USE_YEAR = 2026

# Canonical config used by most fixtures.
BASE_POINTS_PER_WEEK = 1000
BASE_ANNUAL_FEE_CENTS_PER_1000 = 20000  # $200 per 1000 points
