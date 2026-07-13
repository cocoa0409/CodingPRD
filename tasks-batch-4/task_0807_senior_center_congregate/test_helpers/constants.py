"""Domain thresholds — numeric constants from the PRD funding, meal, and wellness narratives."""

# Per-unit cost in whole cents by service category (PRD 3.3).
UNIT_COST_CENTS = {
    "CONGREGATE_MEAL": 850,
    "TRANSPORTATION": 1200,
    "WELLNESS": 1500,
    "ACTIVITY": 400,
}

# Monthly voluntary-contribution statement (PRD 3.6).
CONGREGATE_MEAL_UNIT_COST_CENTS = 850
CONTRIBUTION_RATE = 0.15

# Wellness enrollment lapse threshold in consecutive absences (PRD 3.7).
LAPSE_ABSENCE_THRESHOLD = 2

# Vehicle turnaround buffer in minutes, applied on each side of the trip window (PRD 3.5).
VEHICLE_TURNAROUND_BUFFER_MIN = 15

# Pagination defaults (PRD 2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Logical clock startup default before any /_clock/set_current_utc call (PRD 2.8).
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"
