"""Domain thresholds — numeric constants from PRD §2.4, §3.4, §3.5, §3.8."""

# Logical clock (PRD §2.4): server-startup default reading.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Billable days (PRD §3.4).
SECONDS_PER_DAY = 86400
DAYS_PER_WEEK = 7
DAYS_PER_MONTH = 28

# Trip charges (PRD §3.5).
TRIP_FEE_CENTS = 15000
FREE_STANDBY_MINUTES = 30
STANDBY_RATE_CENTS_PER_MINUTE = 250
LABOR_RATE_CENTS_PER_HOUR = 9500

# Claims (PRD §3.8).
WAIVER_LIABILITY_PCT = 0.10
RECOVERY_CREDIT_PCT = 0.80

# Driver route buffer (PRD §2.9).
ROUTE_BUFFER_MINUTES = 45

# Common rate card used across tests (aerial 19ft scissor lift).
DEFAULT_CLASS_RATES = {
    "daily_rate_cents": 14500,
    "weekly_rate_cents": 43500,
    "monthly_rate_cents": 99000,
    "min_rental_days": 1,
    "max_working_height_ft": 25,
    "replacement_value_cents": 2_500_000,
}
