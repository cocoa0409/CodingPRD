"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # SLA windows in days per urgency (PRD §3.3).
    "SLA_STAT_DAYS": 2,
    "SLA_URGENT_DAYS": 7,
    "SLA_ROUTINE_DAYS": 30,
    # No-show posture (PRD §3.2).
    "NO_SHOW_STRIKE_LIMIT": 3,
    "STRIKE_WEIGHT": 25,
    "OVERDUE_WEIGHT": 0.5,
    "OVERDUE_HOURS": 24,
    "RISK_CAP": 100,
    # Appointment buffer / grace (PRD §3.6).
    "BOOKING_BUFFER_MINUTES": 15,
    "NO_SHOW_GRACE_MINUTES": 15,
    # Consult note return window (PRD §3.7).
    "NOTE_RETURN_DAYS": 14,
    # Leakage watch threshold (PRD §3.8).
    "LEAKAGE_WATCH_COUNT": 2,
}

MATCH_CONSTANTS = {
    "BASE_SCORE": 50,
    "PREFERRED_BONUS": 25,
    "STANDARD_BONUS": 10,
    "UTILIZATION_PENALTY": -15,
    "UTILIZATION_THRESHOLD": 0.8,
    "STAT_BONUS": 20,
    "URGENT_BONUS": 10,
    "REGION_BONUS": 5,
    "SCORE_MIN": 0,
    "SCORE_MAX": 100,
}

# Per-specialty base values in cents (PRD §3.8).
SPECIALTY_BASE_CENTS = {
    "CARDIOLOGY": 42000,
    "ORTHOPEDICS": 33500,
    "NEUROLOGY": 50000,
    "DERMATOLOGY": 18000,
    "ENDOCRINOLOGY": 26000,
}
