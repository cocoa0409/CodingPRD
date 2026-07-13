"""Domain thresholds — numeric constants from PRD calculations and rules."""

# The logical clock's startup default (PRD 2.5).
CLOCK_DEFAULT_UTC = "2026-03-01T00:00:00Z"

# Clearance-time calculation (PRD 3.1).
AVG_VEHICLE_OCCUPANCY = 2.5

# Staff-shift handover buffer in minutes (PRD 3.4).
MIN_HANDOVER_BUFFER_MIN = 30

# Field defaults (PRD 3.1, 3.4).
DEFAULT_IPAWS_BUDGET = 5
DEFAULT_ADA_RESERVED_PCT = 0.10
DEFAULT_POWER_BACKUP = True

# Pagination (PRD 2.3).
PAGINATION = {
    "limit_default": 10,
    "limit_min": 1,
    "limit_max": 100,
    "offset_default": 0,
}

# A syntactically valid UUID that no resource will ever own.
NONEXISTENT_UUID = "00000000-0000-0000-0000-000000000000"

# A wide staff-shift window that always covers the default logical clock.
COVERING_SHIFT_START = "2026-02-01T00:00:00Z"
COVERING_SHIFT_END = "2026-12-01T00:00:00Z"
