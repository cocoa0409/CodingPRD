"""Domain thresholds — numeric constants drawn from the PRD's calculation rules."""

# Late-cancel / no-show fee schedule (PRD section 3.8).
FEE_CONSTANTS = {
    "LATE_CANCEL_BASE_CENTS": 1500,
    "NO_SHOW_BASE_CENTS": 2500,
    "TIER2_SURCHARGE_CENTS": 1000,   # prior strikes 2 or 3
    "TIER3_SURCHARGE_CENTS": 2500,   # prior strikes 4 or more
}

# Member standing / strike rules (PRD section 3.7).
STANDING_CONSTANTS = {
    "NO_SHOW_BLOCK_THRESHOLD": 3,
    "STRIKE_WINDOW_DAYS": 30,
    "CHECKIN_LEAD_HOURS": 2,
}

# Scheduling conflict buffers (PRD section 3.5).
SCHEDULE_CONSTANTS = {
    "INSTRUCTOR_TRAVEL_BUFFER_MIN": 30,
    "ROOM_CLEANING_BUFFER_MIN": 15,
}

# Default seat / waitlist values (PRD section 3.5).
SESSION_DEFAULTS = {
    "DEFAULT_WAITLIST_CAPACITY": 5,
}
