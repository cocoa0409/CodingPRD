"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# Fraud-score scoring weights (PRD §3.7)
FRAUD = {
    "FLAG_WEIGHT": 12,
    "GPS_TOLERANCE_M": 50,
    "GPS_STEP": 5,
    "DURATION_FLOOR_MIN": 8,
    "SHORT_DURATION_PENALTY": 25,
}

# Payroll / scheduling constants (PRD §3.9, §3.5)
PAY = {
    "OT_PREMIUM_RATE": 0.5,
}
REST_BUFFER_MINUTES = 240  # PRD §3.5 contact cooldown

# Field defaults applied by the server when optional tuning fields are omitted (PRD §3.1, §3.9)
DEFAULTS = {
    "FRAUD_SCORE_THRESHOLD": 60,
    "MAX_ATTEMPTS": 6,
    "MILEAGE_RATE_CENTS_PER_MILE": 67,
    "OVERTIME_THRESHOLD_CENTS": 200000,
}
