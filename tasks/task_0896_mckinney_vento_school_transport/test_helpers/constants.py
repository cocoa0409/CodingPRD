"""Domain thresholds — numeric constants from the PRD (§2.6, §3.5, §3.6, §3.7)."""

# Cost projection (PRD §3.5)
PER_MILE_RATE_CENTS = 155
BASE_TRIP_CENTS = 500
SCHOOL_DAYS_PER_MONTH = 20

# Cost-share allocation (PRD §3.6)
SHARE_CAP_CENTS = 100_000
TIER_SMALL_MAX_MILES = 10      # <= 10 miles -> 0.50
TIER_MID_MAX_MILES = 25        # (10, 25]   -> 0.60; > 25 -> 0.75
SERVING_PCT_SMALL = 0.50
SERVING_PCT_MID = 0.60
SERVING_PCT_LARGE = 0.75

# Caseload (PRD §3.1)
DEFAULT_MAX_CASELOAD = 25

# Temporal capacity gates (PRD §3.7) — pinned constants
VEHICLE_BUFFER_MINUTES = 30
DISTRICT_CONCURRENT_TRIP_CAP = 3

# Logical clock default (PRD §2.9)
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# Priority weights (PRD §3.3)
PROVISIONAL_LIVING_WEIGHT = {
    "SHELTER": 40,
    "UNSHELTERED": 50,
    "HOTEL_MOTEL": 30,
    "DOUBLED_UP": 20,
    "FOSTER_PLACEMENT": 35,
    "HOUSED": 0,
}
FINAL_BASIS_WEIGHT = {
    "NIGHT_TO_NIGHT": 50,
    "UNSHELTERED": 50,
    "SHELTER": 40,
    "FOSTER": 35,
    "HOTEL_MOTEL": 30,
    "DOUBLED_UP": 20,
}
FINAL_FOSTER_BONUS = 10
