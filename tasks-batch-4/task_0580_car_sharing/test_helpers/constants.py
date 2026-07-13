"""Domain thresholds — numeric constants from the Car Sharing PRD §3 calculations.

Generic NON_EXISTENT_UUID comes from the framework barrel export.
"""

# Length-discount thresholds (PRD §3.4).
WEEKLY_THRESHOLD_NIGHTS = 7
MONTHLY_THRESHOLD_NIGHTS = 28

# Final-settlement incidental-fee rates (PRD §3.6).
MILEAGE_OVERAGE_RATE_CENTS = 50
FUEL_CHARGE_PER_PCT_CENTS = 500
LATE_FEE_MULTIPLIER = 1.5
GRACE_HOURS = 2
GRACE_SECONDS = GRACE_HOURS * 3600

# Driver-risk scoring weights (PRD §3.8).
AT_FAULT_WEIGHT = 20
LATE_WEIGHT = 5
MAX_RISK_SCORE = 100

# Booking / payout limits (PRD §3.4, §3.9).
MAX_TRIP_NIGHTS = 90
MIN_PAYOUT_CENTS = 5000

# Vehicle input defaults (PRD §3.1).
DEFAULT_DAILY_MILEAGE_LIMIT = 200
DEFAULT_WEEKLY_DISCOUNT_PCT = 0.10
DEFAULT_MONTHLY_DISCOUNT_PCT = 0.25

# Scheduled-return time-of-day for a trip's end_date (PRD §3.4).
SCHEDULED_RETURN_TIME = "T11:00:00Z"

# Test-scenario default values reused across fixtures/tests.
TEST_DEFAULTS = {
    "BASE_DAILY_PRICE_CENTS": 10000,
    "PLAN_DEDUCTIBLE_CENTS": 100000,
    "PLAN_DAILY_PREMIUM_CENTS": 2500,
    "PLAN_COVERAGE_LIMIT_CENTS": 1500000,
    "PLAN_HOST_EARNINGS_PCT": 0.8,
    "TRIP_START": "2026-06-01",
    "TRIP_END": "2026-06-08",  # 7 nights
    "CHECKIN_CLOCK": "2026-06-01T10:00:00Z",
    "CHECKOUT_CLOCK_ONTIME": "2026-06-08T09:00:00Z",
}
