"""Domain thresholds and pinned numeric constants stated in the PRD."""

# The logical clock's birth instant (PRD 2.4).
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-05-01"

# Basis-point scale: 10000 bp == a factor of exactly 1.0 (PRD 2.8).
BP_SCALE = 10000

# Support points by tier (PRD 3.2 / 3.5).
SUPPORT_POINTS = {
    "INDEPENDENT": 25,
    "INTERMITTENT": 50,
    "SUBSTANTIAL": 100,
    "ONE_TO_ONE": 0,
}

# Risk multipliers in basis points (PRD 3.5).
RISK_MULTIPLIER_BP = {
    "LOW": 10000,
    "MODERATE": 12500,
    "HIGH": 15000,
}

# Staffing arithmetic (PRD 3.5).
STAFF_POINT_CAPACITY = 400
MIN_GROUP_STAFF = 1

# Enrolment / assessment / transport windows.
ENROLLMENT_CUTOFF_HOURS = 24          # PRD 3.3
ASSESSMENT_VALID_DAYS = 365           # PRD 3.4
STAFF_TURNAROUND_BUFFER_MINUTES = 30  # PRD 3.5
TRANSPORT_ARRIVAL_BUFFER_MINUTES = 15 # PRD 3.7
INSPECTION_CYCLE_DAYS = 180           # PRD 3.6

# Money (PRD 3.7 / 3.8).
ACCESSIBLE_SURCHARGE_CENTS = 250
ZONE_BASE_FARE_CENTS = 300
ZONE_PER_TENTH_MILE_CENTS = 85
SIBLING_DISCOUNT_BP = 1500

# Staffing unlock cap (PRD 3.5).
MAX_UNLOCKS = 2

# Subsidy-required income bands that a lapsed award demotes (PRD 3.4).
SUBSIDY_REQUIRED_BANDS = ("BAND_A", "BAND_B")

TEST_DEFAULTS = {
    "PER_SESSION_CENTS": 4000,
    "SERIES_CENTS": 24000,
    "SLOT_CAPACITY": 2,
    "SESSION_START": "2026-06-10T14:00:00Z",
    "SESSION_END": "2026-06-10T16:00:00Z",
}
