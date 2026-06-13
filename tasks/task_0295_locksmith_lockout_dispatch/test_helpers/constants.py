"""Domain thresholds — numeric constants from PRD calculations (§3.5, §3.6, §3.14)."""

# Flat call-out base rates per service_type (PRD §3.5), in cents.
BASE_RATE_CENTS = {
    "LOCKOUT": 9000,
    "REKEY": 12000,
    "INSTALL": 15000,
    "SAFE": 20000,
}

# Labor rate for the measured final total (PRD §3.5), in cents per hour.
LABOR_RATE_CENTS_PER_HOUR = 8000

# Surcharge constants (PRD §3.6).
AFTER_HOURS_START_MINUTE = 1080   # 18:00 inclusive
AFTER_HOURS_END_MINUTE = 480      # 08:00 exclusive (before 08:00 is after-hours)
AFTER_HOURS_MULTIPLIER = 1.5
EMERGENCY_LOCKOUT_MULTIPLIER = 1.25

# Promised-ETA projection (PRD §3.2).
QUEUE_PENALTY_MINUTES = 10

# ETA-window overlap travel buffer (PRD §3.3).
BUFFER_MINUTES = 15

# Warranty window (PRD §3.14).
WARRANTY_DAYS = 90

THRESHOLDS = {
    "AFTER_HOURS_START_MINUTE": AFTER_HOURS_START_MINUTE,
    "AFTER_HOURS_END_MINUTE": AFTER_HOURS_END_MINUTE,
    "AFTER_HOURS_MULTIPLIER": AFTER_HOURS_MULTIPLIER,
    "EMERGENCY_LOCKOUT_MULTIPLIER": EMERGENCY_LOCKOUT_MULTIPLIER,
    "QUEUE_PENALTY_MINUTES": QUEUE_PENALTY_MINUTES,
    "BUFFER_MINUTES": BUFFER_MINUTES,
    "WARRANTY_DAYS": WARRANTY_DAYS,
    "LABOR_RATE_CENTS_PER_HOUR": LABOR_RATE_CENTS_PER_HOUR,
}
