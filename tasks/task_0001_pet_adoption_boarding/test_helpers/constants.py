"""Domain thresholds from scaffold Table 3."""

# Home visit constants
HOME_VISIT_PASS_THRESHOLD = 70
HOME_VISIT_TTL_DAYS = 180

# Adoption fee constants
SENIOR_AGE_MONTHS = 96
SENIOR_DISCOUNT = 0.5

# Boarding quote constants
PEAK_UTILIZATION = 0.8
PEAK_SURCHARGE = 0.1
MEDICAL_MULTIPLIER = 1.5
BEHAVIORAL_MULTIPLIER = 1.25

# Check-in constant
EARLY_CHECKIN_GRACE_HOURS = 24  # reasonable default; PRD references EARLY_CHECKIN_GRACE_HOURS

# Pagination
DEFAULT_LIMIT = 50
MIN_LIMIT = 1
MAX_LIMIT = 200
DEFAULT_OFFSET = 0

# Test defaults (cents)
TEST_DEFAULTS = {
    "ADOPTION_FEE_BASE": 20000,   # $200.00 in cents
    "BOARDING_RATE_PER_NIGHT": 5000,  # $50.00 in cents
    "BOARDING_CAPACITY": 10,
    "AGE_MONTHS_ADULT": 24,
    "AGE_MONTHS_SENIOR": 120,  # >= 96 -> senior
}
