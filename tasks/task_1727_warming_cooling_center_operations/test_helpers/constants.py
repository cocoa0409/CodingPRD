"""Domain thresholds and timeline anchors from the PRD.

Numeric rules: PRD §2.4 (logical clock), §2.7 (inclusive thresholds),
§3.1 (breach run, 15-minute gap), §3.3 (overnight window), §3.5 (vehicle
turnaround), §3.6 (meal buffers), §3.8 (no-show grace).
"""

# --- Logical clock (PRD §2.4) ------------------------------------------------
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"
SETUP_CLOCK = "2026-08-10T08:00:00Z"

# --- Breach trigger (PRD §3.1) ------------------------------------------------
MAX_GAP_MINUTES = 15            # a gap of exactly 15 keeps the run; 16 breaks it
MINUTES_PER_HOUR = 60
DEFAULT_COOLING_THRESHOLD_F = 100.0
DEFAULT_WARMING_THRESHOLD_F = 32.0
DEFAULT_SUSTAINED_HOURS = 1
DEFAULT_SCHEDULED_END = "2026-08-12T00:00:00Z"
# Five readings at 15-minute gaps spanning exactly 60 minutes qualify.
BREACH_RUN_DATE = "2026-08-10"
BREACH_RUN_TIMES = [
    "2026-08-10T06:00:00Z",
    "2026-08-10T06:15:00Z",
    "2026-08-10T06:30:00Z",
    "2026-08-10T06:45:00Z",
    "2026-08-10T07:00:00Z",
]

# --- Overnight coverage window (PRD §3.3) --------------------------------------
OVERNIGHT_START_HOUR = 22
OVERNIGHT_END_HOUR = 6
OVERNIGHT_MINUTES = 480
OVERNIGHT_SHIFT_START = "2026-08-10T22:00:00Z"
OVERNIGHT_SHIFT_END = "2026-08-11T06:00:00Z"

# --- Dispatch / no-show (PRD §3.5, §3.8) ----------------------------------------
NO_SHOW_GRACE_MINUTES = 60
DEFAULT_TURNAROUND_MINUTES = 30

# --- Locker pinning (PRD §2.6, §3.4) --------------------------------------------
BAGS_PER_LOCKER = 2             # lockers_used = ceil(bag_count / 2)

# --- Meal planning buffers (PRD §3.6) -------------------------------------------
BREAKFAST_BUFFER = 1.10
LUNCH_BUFFER = 1.15
DINNER_BUFFER = 1.25

# --- Common payload defaults -----------------------------------------------------
DEFAULT_SITE = {
    "name": "Rec Center",
    "address": "1 Main St",
    "bed_capacity": 4,
    "pet_capacity": 0,
    "locker_capacity": 0,
}
