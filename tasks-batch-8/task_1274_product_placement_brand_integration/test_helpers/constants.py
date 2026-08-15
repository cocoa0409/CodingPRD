"""Domain thresholds — numeric constants from PRD §3 calculations."""

# Default logical clock reading before any test-driving call (PRD §2.5).
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# contract_billing_value / makegood_compensation constants (PRD §3.5, §3.7).
MAKEGOOD_MULTIPLIER = 1.5
BONUS_CAP_PCT = 0.25
VERBAL_MISS_PENALTY_CENTS = 5000
SEVERE_SHORTFALL_RATIO = 0.5
SEVERE_SURCHARGE = 1.2
MAKEGOOD_PROMO_PENALTY = 1

# measured_exposure_valuation constant (PRD §3.7).
VALUE_RATE_CENTS_PER_SECOND = 7.5

# clearance_conflict_score constants (PRD §3.3).
PROXIMITY_SCORE = 40
WATCHLIST_SCORE = 30
STRICT_WINDOW_DAYS = 7
STANDARD_WINDOW_DAYS = 7
STRICT_DENY_THRESHOLD = 40
STANDARD_DENY_THRESHOLD = 60
