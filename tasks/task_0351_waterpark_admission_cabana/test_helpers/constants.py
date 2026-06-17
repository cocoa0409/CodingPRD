"""Domain thresholds — numeric constants from the PRD calculations (§3)."""

# Wristband band-color floors (PRD §3.4): height_cm >= floor takes the higher band.
GREEN_MIN_CM = 122
YELLOW_MIN_CM = 107

# Season-pass freeze cap (PRD §3.5): freeze refused when running freeze_days_used
# already stands at 30 or beyond before the episode begins.
MAX_FREEZE_DAYS = 30

# Locker billing (PRD §3.7): every started hour bills a full hour.
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

THRESHOLDS = {
    "GREEN_MIN_CM": GREEN_MIN_CM,
    "YELLOW_MIN_CM": YELLOW_MIN_CM,
    "MAX_FREEZE_DAYS": MAX_FREEZE_DAYS,
    "SECONDS_PER_HOUR": SECONDS_PER_HOUR,
    "SECONDS_PER_DAY": SECONDS_PER_DAY,
}

# Default values used by factories and fixtures.
TEST_DEFAULTS = {
    "TOTAL_GATE_CAPACITY": 1000,
    "BASE_PRICE_CENTS": 5000,
    "WINDOW_CAPACITY": 50,
    "GROUP_THRESHOLD": 10,
    "TURNOVER_BUFFER_MINUTES": 30,
}
