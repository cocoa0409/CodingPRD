"""Domain thresholds — numeric constants from the PRD billing and safety narratives."""

# Adverse-event severity scoring weights and the auto-hold threshold (PRD 3.9).
AE_WEIGHTS = {
    "W_SEVERITY": 2,
    "W_REACTION": 1,
    "W_VITAL": 3,
}
AE_HOLD_THRESHOLD = 7

# Pump reservation trailing reprocessing buffer in minutes (PRD 3.5).
PUMP_REPROCESS_MIN = 1440

# Nurse travel buffer in minutes, symmetric on both ends (PRD 3.6).
TRAVEL_BUFFER_MIN = 60

# Pagination defaults (PRD 2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Logical clock startup default (PRD 2.4).
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"
