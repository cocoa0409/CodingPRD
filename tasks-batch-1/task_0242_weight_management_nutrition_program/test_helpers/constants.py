"""Domain thresholds — numeric constants from the PRD's calculations and gates.

Generic ``NON_EXISTENT_UUID`` is re-exported from the framework via the barrel.
"""

# Progress / BMI / risk-band constants (PRD §2.6, §3.3, §3.6)
GOAL_FRACTION = 0.10            # nominal 10%-of-body-weight target band
ASSUMED_BASELINE_FAT = 0.30     # assumed baseline body-fat fraction for lean-adjusted progress
HIGH_BMI = 35.0
MOD_BMI = 30.0

# Eligibility composite score (PRD §3.9)
ELIGIBILITY_THRESHOLD = 35
BMI_BASE = 25.0
BMI_WEIGHT = 4
COMORBID_WEIGHT = 15
BMI_CAP = 40
COMORBID_CAP = 30
TIER_PTS_RX = 20
TIER_PTS_COACHING = 10
TIER_PTS_MEAL = 5

# Rx BMI gate (PRD §3.10)
RX_BMI_MIN = 30.0
RX_BMI_COMORBID_MIN = 27.0

# Graduation (PRD §3.11)
MIN_COUNTED_WEIGHINS = 3

# Billing / proration (PRD §3.11)
SECONDS_PER_DAY = 86400
DEFAULT_CYCLE_LENGTH_DAYS = 30

# Program defaults (PRD §3.1)
DEFAULT_COACH_MAX_ACTIVE_MEMBERS = 50
EPOCH_UTC = "1970-01-01T00:00:00.000Z"

# Test-default fee values (cents)
TEST_DEFAULTS = {
    "MONTHLY_FEE_CENTS": 6000,
    "ENROLLMENT_FEE_CENTS": 2500,
    "HEIGHT_CM": 170,
    "INTAKE_WEIGHT_KG": 95,
}
