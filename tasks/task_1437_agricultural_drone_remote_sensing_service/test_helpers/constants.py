"""Domain thresholds — numeric constants named in PRD prose."""

# Flight weather limit (PRD section 3.4): capture admits wind of at most
# 20 knots; a weather abort requires wind above 20 knots.
WIND_LIMIT_KT = 20

# Scheduling buffer (PRD section 2.11): each mission's window is padded by
# 30 minutes on each side for the same-field conflict scan.
BUFFER_MINUTES = 30

# Billing tiers (PRD section 3.5): the FINAL variant prices the first 200
# overage acres of a mission at the full rate and every acre beyond at the
# overage rate multiplied by 0.80 (rounded half-up to a whole cent).
TIER1_OVERAGE_CAP = 200
TIER2_DISCOUNT = 0.80

# Anomaly scoring (PRD section 3.6).
NDVI_STRESS_THRESHOLD = 0.400
STAND_MIN_PLANTS = 20000
STAND_TARGET_PLANTS = 30000
SEVERITY_LOW_MIN = 1
SEVERITY_MEDIUM_MIN = 10
SEVERITY_HIGH_MIN = 50

# Health-score alert weights (PRD section 3.6).
SEVERITY_WEIGHT_LOW = 2
SEVERITY_WEIGHT_MEDIUM = 5
SEVERITY_WEIGHT_HIGH = 12

# Input invariants (PRD sections 3.1 and 3.2).
MIN_LIABILITY_COVERAGE_CENTS = 50_000_000
MAX_ALTITUDE_FT = 400

# Logical clock (PRD section 2.5): startup default.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "LIABILITY_COVERAGE_CENTS": 50_000_000,
    "SUBSCRIPTION_STARTED_ON": "2026-01-01",
    "PART107_EXPIRES_ON": "2027-01-01",
}
