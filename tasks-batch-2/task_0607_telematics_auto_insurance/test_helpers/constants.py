"""Domain thresholds — numeric constants from PRD §2 and §3 workflows/calculations."""

# Risk-multiplier tier table (PRD §2.8)
MULT_FLOOR = 0.85
MULT_CEILING = 1.60
TIER_SAFE_UPPER = 10.0       # score < 10.0 -> SAFE 0.85
TIER_STANDARD_UPPER = 25.0   # 10.0 <= score < 25.0 -> STANDARD 1.00
TIER_ELEVATED_UPPER = 50.0   # 25.0 <= score < 50.0 -> ELEVATED 1.25
                             # score >= 50.0 -> HIGH 1.60
MULT_SAFE = 0.85
MULT_STANDARD = 1.00
MULT_ELEVATED = 1.25
MULT_HIGH = 1.60

# Scoring / quote / claim constants (PRD §3.3, §3.4, §3.8)
MIN_SCORING_TRIPS = 3
QUOTE_VALIDITY_DAYS = 14
CRASH_FNOL_SEVERITY = 4
MAX_CLAIM_REOPENS = 2
RESERVE_BASE_CENTS = 100000

# Mileage / billing constants (PRD §3.6)
PERIODS_PER_YEAR = 12

# Safe-trip discount (PRD §3.5)
SAFE_TRIP_MIN_MILES = 5.0
SAFE_TRIP_DISCOUNT_CENTS = 250

# Renewal discount cap (PRD §3.9)
RENEWAL_MAX_DISCOUNT_CENTS = 50000

# Pagination defaults (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

# Default logical clock at startup (PRD §2.4)
DEFAULT_CLOCK_UTC = "2026-01-01T00:00:00Z"

# Shared rate-plan literals used across difficulty/corner recipes.
SHARED_RATE_PLAN = {
    "name": "CA UBI",
    "state_code": "CA",
    "base_premium_cents": 200000,
    "per_mile_rate_cents": 0.5,
    "included_miles_per_period": 1000,
    "hard_brake_weight": 2.0,
    "speeding_weight": 1.5,
    "phone_use_weight": 1.0,
}
