"""Domain thresholds — numeric constants from the PRD computations (Sections 2.10, 3)."""

# Risk-score weights (PRD 3.4): name hit 50, company hit 30, missing photo ID 15.
RISK_SCORE_WEIGHTS = {
    "NAME_HIT_WEIGHT": 50,
    "COMPANY_HIT_WEIGHT": 30,
    "NO_PHOTO_ID_WEIGHT": 15,
}
RISK_SCORE_MIN = 0
RISK_SCORE_MAX = 100

# Delivery handling surcharge (PRD 3.8): 7.5 percent per parcel, round-half-up.
SURCHARGE_RATE = 0.075

# Visit duration (PRD 3.6): elapsed seconds / 60, rounded up.
SECONDS_PER_MINUTE = 60

# Contractor parking billing tiers (PRD 3.7).
FREE_MINUTES = 60
TIER2_SPAN = 180          # minutes 61..240 billed in tier 2
TIER2_RATE_CENTS = 200    # cents per started hour in tier 2
TIER3_RATE_CENTS = 500    # cents per started hour beyond 240 minutes

# Parking cleaning buffer (PRD 3.3): 15-minute gap required between reservations.
CLEANING_BUFFER_MINUTES = 15

# Pagination defaults (PRD 2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
