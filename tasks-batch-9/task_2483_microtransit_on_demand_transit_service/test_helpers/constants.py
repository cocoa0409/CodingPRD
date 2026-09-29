"""Domain thresholds and pinned numeric constants taken from the PRD's
corridor-geometry, matching, fare, fleet-sizing, scorecard and subsidy rules."""

# Corridor geometry and the travel-time model (PRD §2.6)
TRAVEL_MINUTES_PER_INDEX = 3

# Matching engine score terms (PRD §3.5)
DETOUR_TERM_MULTIPLIER = 4
DETOUR_TERM_CAP = 100
SURGE_PENALTY = 15
WAV_TIGHT_PENALTY = 8
SEAT_SLACK_CAP = 12
SEAT_SLACK_WEIGHT = 2
MAX_MATCH_ATTEMPTS = 2

# Fare rule (PRD §3.7)
BAND_EDGE_SHORT_MINUTES = 10
BAND_EDGE_MEDIUM_MINUTES = 20
BAND_SURCHARGE_CENTS = {"SHORT": 0, "MEDIUM": 75, "LONG": 150}
CATEGORY_MULTIPLIER = {"FULL": 1.00, "REDUCED": 0.50, "PARATRANSIT": 0.00}

# Fleet sizing (PRD §3.3)
TRIPS_PER_BLOCK_HOUR = 4
SURGE_THRESHOLD_PEAK_FACTOR = 1.50
MAX_SURGE_BLOCKS = 6

# Subsidy computation (PRD §3.9)
OPERATING_COST_CENTS_PER_REVENUE_HOUR = 8250
ADMIN_OVERHEAD_PCT = 0.12

# Equivalent-service test (PRD §3.8)
WAV_EQUIVALENCE_MAX_RATIO = 1.25

# Roster consequences (PRD §3.6) and scheduling exclusions (PRD §3.4)
DECLINE_SUSPENSION_THRESHOLD = 3
DRIVER_REST_BUFFER_MINUTES = 30

# Curb-congestion bucketing (PRD §3.5)
CURB_BUCKET_MINUTES = 15

# Logical clock (PRD §2.5)
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# The service day every fixture replays. 2026-08-03 is a Monday, so the UTC
# service date and the Monday-anchored ISO week start coincide.
SERVICE_DATE = "2026-08-03"
WEEK_START_DATE = "2026-08-03"

THRESHOLDS = {
    "TRAVEL_MINUTES_PER_INDEX": TRAVEL_MINUTES_PER_INDEX,
    "MAX_MATCH_ATTEMPTS": MAX_MATCH_ATTEMPTS,
    "SURGE_THRESHOLD_PEAK_FACTOR": SURGE_THRESHOLD_PEAK_FACTOR,
    "WAV_EQUIVALENCE_MAX_RATIO": WAV_EQUIVALENCE_MAX_RATIO,
    "DECLINE_SUSPENSION_THRESHOLD": DECLINE_SUSPENSION_THRESHOLD,
    "DRIVER_REST_BUFFER_MINUTES": DRIVER_REST_BUFFER_MINUTES,
}

# Default zone policy the fixtures build on. Chosen so that a S0 -> S4 trip has
# a baseline direct ride of 12 minutes, a detour allowance of 6 minutes and a
# MEDIUM-band quote of 325 cents for a FULL rider.
TEST_DEFAULTS = {
    "ZONE_NAME": "Riverbend Microtransit",
    "ZONE_CODE": "RBM",
    "MAX_WALK_METERS": 600,
    "DETOUR_TOLERANCE_PCT": 0.25,
    "DETOUR_TOLERANCE_FLOOR_MINUTES": 6,
    "BASE_FARE_CENTS": 250,
    "FARE_CAP_CENTS_DAILY": 600,
    "FARE_CAP_CENTS_WEEKLY": 2500,
    "ON_TIME_WINDOW_MINUTES": 10,
    "CURB_CAPACITY_PER_BUCKET": 2,
    "WALK_SHED_METERS": 400,
    "SEAT_CAPACITY": 6,
    "WAV_POSITIONS": 2,
    "BLOCK_START_UTC": "2026-08-03T06:00:00Z",
    "BLOCK_END_UTC": "2026-08-03T10:00:00Z",
    "REQUESTED_PICKUP_UTC": "2026-08-03T07:00:00Z",
}

# A well-formed UUID that never names a row in any collection.
ABSENT_UUID = "00000000-0000-4000-8000-000000000000"
