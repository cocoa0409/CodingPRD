"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Diagnostic severity tiers (PRD §3.2): inclusive lower bounds.
SEVERE_FLOOR = 120
MODERATE_FLOOR = 60
SEVERE_WEEKLY_UNITS = 160
MODERATE_WEEKLY_UNITS = 100
MILD_WEEKLY_UNITS = 40

# Per-service-line billing rates in cents per 15-minute unit (PRD §3.9).
SERVICE_LINE_RATE_CENTS = {
    "DIRECT_THERAPY": 3200,
    "SUPERVISION": 4800,
    "PARENT_TRAINING": 2400,
}

# Client buffer window (PRD §3.6): 15-minute gap required around a session.
CLIENT_BUFFER_MINUTES = 15

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# A syntactically valid UUID that no created resource will own.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
