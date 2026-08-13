"""Domain thresholds and well-known values from the PRD's calculation rules."""

WATER_LB_PER_GAL = 8.34
TRUCK_TURNAROUND_MINUTES = 90
DOSE_PRECISION_OZ = 0.1

# Default logical-clock reading before any operator touches it (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
# 2026-08-15 is a Saturday; 2026-08-17 is the following Monday.
SATURDAY_POUR_DATE = "2026-08-15"
MONDAY_POUR_DATE = "2026-08-17"

THRESHOLDS = {
    "WAIT_FREE_MINUTES": 60,
    "WAIT_RATE_PER_MINUTE_CENTS": 250,
    "WAIT_FEE_CAP_CENTS": 15000,
    "MIN_LOAD_YD3": 4.0,
    "SHORT_LOAD_FEE_CENTS": 7500,
    "MAX_WC_RATIO": 0.50,
    "TRUCK_TURNAROUND_MINUTES": TRUCK_TURNAROUND_MINUTES,
}
