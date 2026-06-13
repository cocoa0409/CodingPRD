"""Domain thresholds — numeric defaults from PRD calculations and field defaults."""

# Default values the server applies when the optional input is omitted (PRD §3.1, §3.2, §3.6).
DEFAULTS = {
    "GATE_BUFFER_MINUTES": 10,        # PRD §3.1: buffer_minutes defaults to 10
    "REMOTE_STAND_CAPACITY": 1,       # PRD §3.1: capacity defaults to 1
    "GSE_TURNAROUND_MINUTES": 0,      # PRD §3.1: turnaround_minutes defaults to 0
    "FLIGHT_MIN_TURN_MINUTES": 45,    # PRD §3.2: min_turn_minutes defaults to 45
    "SLOT_TOLERANCE_MINUTES": 15,     # PRD §3.6: tolerance_minutes defaults to 15
}

# Pagination bounds (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "MIN_OFFSET": 0,
}
