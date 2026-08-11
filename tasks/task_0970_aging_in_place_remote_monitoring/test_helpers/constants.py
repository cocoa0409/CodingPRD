"""Domain thresholds — numeric constants from PRD sections 2.4 and 3."""

# Logical clock startup default (PRD 2.4).
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # Billing (PRD 3.2)
    "DAYS_IN_CYCLE": 30,
    # Wellness scoring weights (PRD 3.8)
    "W_ACTIVITY": 0.40,
    "W_ADHERENCE": 0.35,
    "W_DEVICE": 0.25,
    "ADHERENCE_PENALTY_THRESHOLD": 60,
    "ADHERENCE_PENALTY_FACTOR": 0.8,
    "FALL_CAP": 59,
    # Adherence (PRD 3.8)
    "PUNCTUAL_GRACE_MINUTES": 15,
    # Activity (PRD 3.8)
    "ACTIVE_DAY_MOTION_THRESHOLD": 3,
    # Device health (PRD 3.8)
    "OFFLINE_DEDUCTION": 10,
    "LOW_BATTERY_DEDUCTION": 5,
    # Battery alerts (PRD 3.4)
    "LOW_BATTERY_THRESHOLD": 20,
    "CRITICAL_BATTERY_THRESHOLD": 10,
    # Sweep (PRD 2.4 / 3)
    "OFFLINE_MINUTES": 90,
    "DOSE_HORIZON_HOURS": 48,
    "INACTIVITY_HOURS": 12,
    "MISSED_STREAK_CRITICAL": 2,
    "MISSED_STREAK_ROUTINE": 3,
    # Install windows (PRD 3.3)
    "WINDOW_MIN_MINUTES": 60,
    "WINDOW_MAX_MINUTES": 240,
    "TRAVEL_BUFFER_MINUTES": 30,
    # Dose windows (PRD 3.6)
    "DOSE_WINDOW_MIN_MINUTES": 15,
    "DOSE_WINDOW_MAX_MINUTES": 240,
}

TEST_DEFAULTS = {
    "SENIOR_DOB": "1940-01-01",
    "PLAN_FEE_CENTS": 6000,
    "INCLUDED_MOTION_SENSORS": 2,
    "EXTRA_SENSOR_FEE_CENTS": 199,
    "MAX_CONTACTS": 5,
    "CHECKIN_INTERVAL_HOURS": 48,
    "CONTACT_TIMEOUT_SECONDS": 3600,
}
