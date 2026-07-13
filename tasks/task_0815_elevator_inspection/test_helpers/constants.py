"""Domain thresholds — numeric constants from the PRD's calculations."""

# Registration flat fee (cents)
REGISTRATION_FEE_CENTS = 10000

# Base renewal fee by device category (cents)
BASE_RENEWAL_FEE_CENTS = {
    "PASSENGER_ELEVATOR": 30000,
    "FREIGHT_ELEVATOR": 25000,
    "ESCALATOR": 40000,
    "MOVING_WALK": 35000,
    "DUMBWAITER": 15000,
}

# Late-penalty accrual
LATE_RATE_PER_MONTH = 0.10
LATE_CAP_RATIO = 1.0

# Risk class derived from category
RISK_CLASS = {
    "PASSENGER_ELEVATOR": "HIGH",
    "FREIGHT_ELEVATOR": "MEDIUM",
    "ESCALATOR": "HIGH",
    "MOVING_WALK": "MEDIUM",
    "DUMBWAITER": "LOW",
}

# Risk multiplier used by both citation fine and accident risk score
RISK_MULTIPLIER = {"HIGH": 1.5, "MEDIUM": 1.2, "LOW": 1.0}

# Recurrence interval / certificate interval (months) by category
INTERVAL_MONTHS = {
    "PASSENGER_ELEVATOR": 12,
    "FREIGHT_ELEVATOR": 12,
    "ESCALATOR": 6,
    "MOVING_WALK": 6,
    "DUMBWAITER": 24,
}

# Citation fine tiers
BASE_FINE_CENTS = {"MINOR": 5000, "MAJOR": 20000, "CRITICAL": 50000}
REPEAT_SURCHARGE_CENTS = 10000
REPEAT_SURCHARGE_CAP_COUNT = 3
FINE_CAP_CENTS = 100000
OUTSTANDING_INDEX_RATE = 0.0725

# Citation grace
CITATION_DUE_GRACE_MONTHS = 2

# Deficiency resolution grace (months) by severity
RESOLUTION_GRACE_MONTHS = {"MINOR": 6, "MAJOR": 3, "CRITICAL": 1}

# Accident scoring
SEVERITY_WEIGHT = {"MINOR": 10, "MODERATE": 30, "SEVERE": 60, "FATAL": 100}
UNSUBSTANTIATED_FACTOR = 0.25
OPEN_CRITICAL_DEFICIENCY_BONUS = 20

# Inspector schedule buffer
INSPECTION_BUFFER_PERIODS = 1

# Pagination
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
