"""Domain thresholds and numeric constants named by the PRD's calculations."""

# --- Enrollment projection -------------------------------------------------
COHORT_SURVIVAL_RATE = 0.98
UNIT_YIELD_SINGLE_FAMILY = 0.42
UNIT_YIELD_TOWNHOME = 0.25
UNIT_YIELD_MULTI_FAMILY = 0.13
ENTITLEMENT_WEIGHT_PROPOSED = 0.25
ENTITLEMENT_WEIGHT_ENTITLED = 0.60
ENTITLEMENT_WEIGHT_PERMITTED = 0.85
ENTITLEMENT_WEIGHT_UNDER_CONSTRUCTION = 1.00
ENTITLEMENT_WEIGHT_COMPLETE = 1.00
ENTITLEMENT_WEIGHT_WITHDRAWN = 0.00
DAYS_PER_YEAR = 365
DAYS_PER_MONTH = 30

# --- Capacity utilization --------------------------------------------------
CRITICAL_UTILIZATION_PCT = 110.00

# --- Transportation cost ---------------------------------------------------
BUS_CAPACITY = 71
DAILY_BUS_BASE_USD = 95.00
PER_MINUTE_USD = 1.85
MIN_BILLED_MINUTES = 15
SCHOOL_DAYS_PER_YEAR = 180
WALK_LIMIT_MILES_ELEMENTARY = 1.0
WALK_LIMIT_MILES_MIDDLE = 1.5
WALK_LIMIT_MILES_HIGH = 2.0
MAX_RIDE_MINUTES_ELEMENTARY = 45
MAX_RIDE_MINUTES_MIDDLE = 55
MAX_RIDE_MINUTES_HIGH = 60

WALK_LIMIT_MILES = {
    "ELEMENTARY": WALK_LIMIT_MILES_ELEMENTARY,
    "MIDDLE": WALK_LIMIT_MILES_MIDDLE,
    "HIGH": WALK_LIMIT_MILES_HIGH,
}
MAX_RIDE_MINUTES = {
    "ELEMENTARY": MAX_RIDE_MINUTES_ELEMENTARY,
    "MIDDLE": MAX_RIDE_MINUTES_MIDDLE,
    "HIGH": MAX_RIDE_MINUTES_HIGH,
}

# --- Transfer seat pool ----------------------------------------------------
SEAT_POOL_APPROVE_MINIMUM = 1

# --- Demographic impact ----------------------------------------------------
DEVELOPMENT_FRL_RATE_SINGLE_FAMILY = 0.18
DEVELOPMENT_FRL_RATE_TOWNHOME = 0.32
DEVELOPMENT_FRL_RATE_MULTI_FAMILY = 0.54

UNIT_YIELD = {
    "SINGLE_FAMILY": UNIT_YIELD_SINGLE_FAMILY,
    "TOWNHOME": UNIT_YIELD_TOWNHOME,
    "MULTI_FAMILY": UNIT_YIELD_MULTI_FAMILY,
}
ENTITLEMENT_WEIGHT = {
    "PROPOSED": ENTITLEMENT_WEIGHT_PROPOSED,
    "ENTITLED": ENTITLEMENT_WEIGHT_ENTITLED,
    "PERMITTED": ENTITLEMENT_WEIGHT_PERMITTED,
    "UNDER_CONSTRUCTION": ENTITLEMENT_WEIGHT_UNDER_CONSTRUCTION,
    "COMPLETE": ENTITLEMENT_WEIGHT_COMPLETE,
    "WITHDRAWN": ENTITLEMENT_WEIGHT_WITHDRAWN,
}
DEVELOPMENT_FRL_RATE = {
    "SINGLE_FAMILY": DEVELOPMENT_FRL_RATE_SINGLE_FAMILY,
    "TOWNHOME": DEVELOPMENT_FRL_RATE_TOWNHOME,
    "MULTI_FAMILY": DEVELOPMENT_FRL_RATE_MULTI_FAMILY,
}

# --- Contiguity ------------------------------------------------------------
MIN_COMPONENTS_FOR_VIOLATION = 2

# --- Board vote ------------------------------------------------------------
SUPERMAJORITY_TRIGGER_PCT = 15.00

# --- Transfer eligibility --------------------------------------------------
MIN_GRADE = 0
MAX_GRADE = 12

# --- Variance monitoring ---------------------------------------------------
WATCH_MULTIPLIER = 2

# --- Housing absorption ----------------------------------------------------
ROLLING_ABSORPTION_WINDOW_MONTHS = 12

# --- Regime windows -------------------------------------------------------
MIN_REGIME_YEARS = 2

# --- Engagement revision loop ---------------------------------------------
MAX_REVISION_ROUNDS = 3

# --- The logical clock ----------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"
"""The instant the logical clock reads before any advance call."""

# --- Pagination -----------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_EFFECTIVE_PAGE_LIMIT = 100
MAX_ACCEPTED_PAGE_LIMIT = 200

THRESHOLDS = {
    "CRITICAL_UTILIZATION_PCT": CRITICAL_UTILIZATION_PCT,
    "SUPERMAJORITY_TRIGGER_PCT": SUPERMAJORITY_TRIGGER_PCT,
    "SEAT_POOL_APPROVE_MINIMUM": SEAT_POOL_APPROVE_MINIMUM,
    "MIN_REGIME_YEARS": MIN_REGIME_YEARS,
    "MAX_REVISION_ROUNDS": MAX_REVISION_ROUNDS,
    "WATCH_MULTIPLIER": WATCH_MULTIPLIER,
    "ROLLING_ABSORPTION_WINDOW_MONTHS": ROLLING_ABSORPTION_WINDOW_MONTHS,
}
