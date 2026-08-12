"""Domain thresholds — numeric constants stated in the PRD (§2.4, §2.10, §3)."""

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

# Sterility shelf-life tiers in hours (PRD §2.10).
SHELF_HOURS_WRAPPED = 720
SHELF_HOURS_RIGID_CONTAINER = 2160

# Biological indicator incubation allowance in hours (PRD §3.4/§3.5).
BI_INCUBATION_HOURS = 3

# Repair-vs-replace decision ladder constants (PRD §3.3).
MAX_REPAIRS = 3
REPAIR_COUNT_FACTOR = 0.25
CRITICAL_REMAINING_CYCLES = 10
CRITICAL_FACTOR = 1.5
REPLACE_RATIO_LIMIT = 0.6

# Load reprocessing chargeback constants (PRD §3.5).
BASE_FEE_CENTS = 1000
METHOD_MULTIPLIERS = {
    "STEAM_GRAVITY": 1.0,
    "STEAM_PREVAC": 1.2375,
    "LOW_TEMP_H2O2": 1.7625,
}

# IUSS rolling-window monitoring (PRD §3.6/§3.8).
IUSS_WINDOW_HOURS = 168
CASE_WINDOW_HOURS = 720
SUPERVISOR_THRESHOLD = 4

# Technician competency scoring (PRD §3.8).
FAIL_VERIFY_PTS = 2
CYCLE_FAIL_PTS = 8
H2O2_COMPETENCY_GATE = 70
DECAY_TIER1_DAYS = 30
DECAY_TIER2_DAYS = 60
COMPETENCY_WINDOW_DAYS = 90

# Reservation turnover buffer in minutes (PRD §3.6).
TURNOVER_BUFFER_MINUTES = 45

# Loaner intake lead-time tiers (PRD §3.7).
STANDARD_LEAD_HOURS = 24
BULK_LEAD_HOURS = 48
BULK_THRESHOLD = 10

# Pagination envelope defaults (PRD §2.3).
PAGE_DEFAULT_LIMIT = 10
PAGE_MAX_LIMIT = 100
