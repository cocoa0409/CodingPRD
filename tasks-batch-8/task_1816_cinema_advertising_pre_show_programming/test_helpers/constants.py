"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Attendance forecast constants (PRD §3.1).
OCCUPANCY = {
    "MAJOR_METRO": 0.40,
    "REGIONAL": 0.32,
    "SMALL_MARKET": 0.25,
}
DAYPART_FACTOR = {
    "MATINEE": 0.80,
    "EVENING": 1.20,
}
RATING_DEMAND = {
    "G": 0.90,
    "PG": 1.00,
    "PG13": 1.10,
    "R": 1.05,
    "NC17": 0.70,
}
OPENING_WEEK_DAYS = 7
OPENING_WEEK_MULTIPLIER = 1.25

# Reel capacity constants (PRD §3.1 / §3.3).
REEL_CAPACITY_SECONDS = 1200
NATIONAL_POOL_SECONDS = 720
LOCAL_POOL_SECONDS = 480

# Showtime buffered-overlap turnaround (PRD §3.1).
TURNAROUND_MINUTES = 30

# Make-good constants (PRD §3.7).
MAKE_GOOD_THRESHOLD_PCT = 0.05
MAKE_GOOD_MULTIPLIER = 1.10

# Logical clock startup default (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Shared scenario constants used across the test suite:
# 200-seat MAJOR_METRO screen airing a PG13 feature released 2026-08-10.
SEAT_COUNT = 200
FEATURE_RELEASE_DATE = "2026-08-10"
OPENING_EVENING_START = "2026-08-14T19:00:00Z"   # opening-week evening -> forecast 132
STANDARD_EVENING_START = "2026-08-25T19:00:00Z"  # outside window -> forecast 105
OPENING_MATINEE_START = "2026-08-14T14:00:00Z"   # opening-week matinee -> forecast 88
DAY7_EVENING_START = "2026-08-17T19:00:00Z"      # release+7d inclusive -> forecast 132
DAY8_EVENING_START = "2026-08-18T19:00:00Z"      # release+8d -> forecast 105
AFTER_SHOW_CLOCK = "2026-08-14T21:30:00Z"
AFTER_SHOW_CLOCK_DAY2 = "2026-08-15T21:30:00Z"

FORECAST_OPENING_EVENING = 132   # floor(200 x 0.40 x 1.20 x 1.10 x 1.25)
FORECAST_STANDARD_EVENING = 105  # floor(200 x 0.40 x 1.20 x 1.10)
FORECAST_OPENING_MATINEE = 88    # floor(200 x 0.40 x 0.80 x 1.10 x 1.25)

CPM_CENTS = 2500                 # -> 2.5 cents per impression
FLIGHT_START = "2026-08-10"
FLIGHT_END = "2026-08-20"
