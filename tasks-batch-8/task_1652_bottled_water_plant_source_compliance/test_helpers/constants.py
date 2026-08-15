"""Domain thresholds and defaults from the PRD's calculation rules (§2.9, §3)."""

# Treatment validation verdict thresholds (§3.3)
UV_DOSE_MIN = 40.0
OZONE_CT_MIN = 1.6
TURBIDITY_MAX = 0.3
MICRO_PORE_MAX_SPRING = 0.2
RO_REJECTION_MIN_NON_SPRING = 95.0

# Wash verdict thresholds (§3.8)
RINSE_TEMP_MIN_C = 71.1
SANITIZER_MIN_PPM = 50.0

# Bottle lifecycle ceiling (§3.8)
MAX_WASH_CYCLES = 150

# Community report conversion (§3.9)
GAL_PER_ACRE_FOOT = 325851.0

# Plant posture watch threshold (§3.2) — exact integer comparison
WATCH_USAGE_FRACTION = 0.90

# Preform reorder target days (§3.5)
TARGET_DAYS = 2

# Lab-test default due-date offsets in days (§3.4)
DUE_OFFSET_DAYS = {
    "SOURCE_RAW": 7,
    "FINISHED_PRODUCT": 2,
    "BOTTLE_SANITATION": 1,
}

# DUE flip lead window in days (§3.4)
DUE_LEAD_DAYS = 3

# SOURCE_RAW overdue suspension grace in days (§3.2/§3.4)
SOURCE_OVERDUE_GRACE_DAYS = 7

# Startup logical clock (§2.4)
STARTUP_CLOCK = "2026-08-01T00:00:00Z"
STARTUP_DATE = "2026-08-01"

# Common factory defaults
DEFAULTS = {
    "DAILY_CAP_GALLONS": 10000,
    "MONTHLY_CAP_GALLONS": 200000,
    "VALID_FROM": "2026-01-01",
    "VALID_TO": "2026-12-31",
    "LINE_DAILY_CAPACITY": 8000,
}
