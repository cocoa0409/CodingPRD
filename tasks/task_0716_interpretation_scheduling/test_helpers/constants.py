"""Domain thresholds — numeric constants from PRD calculations and workflows."""

# Logical clock startup default (PRD 2.4).
CLOCK_STARTUP = "2026-03-01T00:00:00Z"

# Selection scoring weights / default rating (PRD 3.3).
SELECTION = {
    "W_RATING": 0.5,
    "W_ACCEPT": 0.3,
    "W_LOAD": 0.2,
    "DEFAULT_RATING": 4.0,
}

# Time-window / fee constants (PRD 3.4, 3.5, 3.6, 3.7).
OFFER_TTL_SECONDS = 120
EARLY_START_GRACE_SECONDS = 300
NO_SHOW_GRACE_SECONDS = 600
LATE_CANCEL_WINDOW_SECONDS = 7200
LATE_CANCEL_PCT = 0.50
NO_SHOW_PCT = 0.50

# Billing unit conversion (PRD 3.5).
SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600

# Deactivation threshold (PRD 3.6).
DEACTIVATION_STRIKES = 3

# Fiscal defaults (PRD 2.9 / 3.1).
DEFAULT_CREDIT_LIMIT_CENTS = 5_000_000

# Reusable rate-plan figures used across fixtures (values chosen by the design index).
MED_PHONE_RATE_CENTS = 195       # PER_MINUTE
MED_PHONE_MIN_BLOCK = 10
COURT_ONSITE_RATE_CENTS = 12000  # PER_HOUR
COURT_ONSITE_MIN_BLOCK = 2
COURT_ONSITE_TRAVEL_CENTS = 4500
