"""Domain thresholds — numeric constants drawn from the PRD's calculations and
qualification rules. Generic NON_EXISTENT_UUID comes from the framework.
"""

# Minimum liability insurance required to qualify a contractor (PRD 3.1):
# "at least 1,000,000 cents — that is, at least ten thousand dollars of coverage."
MIN_INSURANCE_CENTS = 1_000_000

# Retainage rate held back on each non-final draw (PRD 3.6: "the retainage rate
# of ten percent").
RETAINAGE_PCT = 0.10

# Bid rank score weights (PRD 3.4): price 0.5, duration 0.3, rating 0.2.
PRICE_WEIGHT = 0.5
DURATION_WEIGHT = 0.3
RATING_WEIGHT = 0.2

THRESHOLDS = {
    "MIN_INSURANCE_CENTS": MIN_INSURANCE_CENTS,
    "RETAINAGE_PCT": RETAINAGE_PCT,
    "PRICE_WEIGHT": PRICE_WEIGHT,
    "DURATION_WEIGHT": DURATION_WEIGHT,
    "RATING_WEIGHT": RATING_WEIGHT,
}

# Test-driving clock defaults. Fixtures pin the server clock to NOW_ISO so the
# bidding window is open, and use far-future expiry/deadline for happy paths.
NOW_ISO = "2026-06-01T00:00:00Z"
AFTER_DEADLINE_ISO = "2026-08-01T00:00:00Z"
DEFAULT_BID_DEADLINE = "2026-07-01T00:00:00Z"
DEFAULT_LICENSE_EXPIRY = "2027-01-01T00:00:00Z"

TEST_DEFAULTS = {
    "BUDGET_CAP_CENTS": 1_000_000,
    "INSURANCE_CENTS": 5_000_000,
    "DURATION_DAYS": 30,
    "WHOLE_JOB_UNIT_COST": 600_000,
}
