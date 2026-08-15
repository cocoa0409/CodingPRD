"""Domain thresholds and well-known values from the PRD.

The logical clock starts at exactly 2026-08-01T00:00:00Z before any
clock-setting call (PRD section on the logical clock).
"""

# Usage forecast (PRD section on usage capture and consumption forecasting)
FORECAST_WINDOW_DAYS = 90
LEAD_TIME_DAYS = 7
DEFAULT_HORIZON_DAYS = 30

# Order rollup (PRD section on order placement, pricing, and settlement)
DELIVERY_MINIMUM_CENTS = 5000

# Fuel surcharge tiers (diesel-index percentage bands)
FUEL_INDEX_TIER_LOW = 3.00    # below -> 4 percent
FUEL_INDEX_TIER_HIGH = 4.00   # at least -> 9 percent; between -> 6 percent
DIST_BAND_MID_MILES = 25      # below -> 1.0 multiplier
DIST_BAND_HIGH_MILES = 75     # at least -> 1.5 multiplier; between -> 1.25

# Dilution training (PRD section on the closed-loop chemical program)
PASS_SCORE_PCT = 80
TRAINING_VALIDITY_DAYS = 365

# Substitution proposals (PRD section on shortage response)
PROPOSAL_TTL_DAYS = 7

# Logical clock startup default
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Common request defaults
DEFAULT_DELIVERY_DATE = "2026-08-05T00:00:00Z"
DEFAULT_FUEL_INDEX = 2.50
DEFAULT_CREDIT_LIMIT_CENTS = 1_000_000
DEFAULT_GROUP_CODE = "GPO-1"
DEFAULT_SERVICE_ZONE = "Z1"
DEFAULT_DISTANCE_MILES = 10
DEFAULT_DELIVERY_DAY = "MON"
