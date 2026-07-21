"""Domain thresholds — numeric constants from PRD calculations and rules."""

# Trade-in valuation (PRD §3.6)
GRADE_MULTIPLIER = {"A": 1.0, "B": 0.75, "C": 0.5, "D": 0.25}
STORE_CREDIT_BONUS_PCT = 0.10

# Rentals (PRD §3.7)
DAILY_LATE_FEE_CENTS = 500
RENTAL_BUFFER_HOURS = 24

# Sales (PRD §3.8)
TAX_RATE = 0.0725
TIER_RATE = {"STANDARD": 1.0, "SILVER": 1.5, "GOLD": 2.0}
MAX_POINTS_PER_SALE = 5000

# Waitlist promotion ranking (PRD §3.5)
TIER_RANK = {"STANDARD": 1, "SILVER": 2, "GOLD": 3}

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Logical clock (PRD §2.10)
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"
