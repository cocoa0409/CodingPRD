"""Domain thresholds — numeric constants from the PRD's calculations (§3, §2.9)."""

# The server logical clock's startup default (PRD §2.5).
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

# Certification cycle constants (PRD §3.2).
CERT_VALIDITY_DAYS = 365
EXPIRING_WINDOW_DAYS = 30
CARRYOVER_CAP = 8  # hours

CERT_REQUIRED_HOURS = {
    "FIREFIGHTER_1": 24,
    "EMT_BASIC": 20,
    "PARAMEDIC": 40,
    "HAZMAT": 16,
    "DRIVER_OPERATOR": 12,
    "CPR": 4,
}

# Points tier thresholds (PRD §3.6).
SILVER_MIN = 10
GOLD_MIN = 20
RATE_CENTS_PER_POINT = {"BRONZE": 0, "SILVER": 150, "GOLD": 250}

# Turnout points (PRD §3.6).
INCIDENT_TYPE_BASE = {
    "STRUCTURE_FIRE": 5,
    "MVA": 4,
    "EMS": 3,
    "ALARM": 2,
    "OTHER": 1,
}
ROLE_MULT = {
    "OFFICER": 1.5,
    "PARAMEDIC": 1.4,
    "EMT": 1.2,
    "FIREFIGHTER": 1.0,
    "PROBATIONARY": 0.5,
}
SCENE_CAP = 6
SCENE_POINTS_PER_HOUR = 1
OFFICER_IC_BONUS = 2

# Duty points (PRD §3.4).
DUTY_POINTS_PER_HOUR = 0.5
DUTY_MIN_POINTS = 2

# Scheduling / fiscal gates.
REST_BUFFER_HOURS = 8
DUES_OVERDUE_LIMIT = 0
