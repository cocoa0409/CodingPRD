"""Domain thresholds — numeric constants drawn from the PRD's calculations.

These are the literal values the PRD pins for scoring, fees, reimbursement,
distance, cooldowns, and 1099 reporting.
"""

# Certification (PRD 3.2): an attempt PASSES when raw_score is at least 70.
CERT_PASS_THRESHOLD = 70

# Reliability bonus tiers (PRD 3.6 shopper fee):
#   reliability_score >= 90 -> 20% bonus; >= 75 -> 10%; else 0.
TIER_HIGH_THRESHOLD = 90
TIER_MID_THRESHOLD = 75
TIER_HIGH_BONUS_PCT = 0.20
TIER_MID_BONUS_PCT = 0.10

# Mileage reimbursement: travel_distance_km * 35 cents per km (PRD 2.5 / 3.5).
MILEAGE_RATE_CENTS_PER_KM = 35

# Reliability score penalties (PRD 3.6 / 3.7).
REJECT_RELIABILITY_PENALTY = 10
NO_SHOW_RELIABILITY_PENALTY = 20
RELIABILITY_MIN = 0.0
RELIABILITY_MAX = 100.0

# Revision / dispute round caps (PRD 3.6 / 3.8).
MAX_REVISION_ROUNDS = 2
MAX_DISPUTE_ROUNDS = 3

# 1099 reporting threshold in cents (PRD 3.9): crossing to >= 60000 triggers it.
IRS_1099_THRESHOLD_CENTS = 60000

# Haversine earth radius in km (PRD 3.4).
EARTH_RADIUS_KM = 6371.0088

# Default wave rotation cooldown (PRD 3.3).
DEFAULT_ROTATION_COOLDOWN_DAYS = 30

# Logical clock startup default (PRD 2.9).
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"
