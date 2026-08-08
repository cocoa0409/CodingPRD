"""Domain thresholds — numeric constants from the PRD's calculations and safety rules."""

# Session pricing (PRD §3.7)
BASE_RATE_CENTS = {
    "MONITORED_EXERCISE": 15000,
    "EDUCATION": 8000,
    "ASSESSMENT": 10000,
}
RISK_MULTIPLIER = {
    "LOW": 1.00,
    "MODERATE": 1.10,
    "HIGH": 1.25,
}
TELEMETRY_SURCHARGE_CENTS = 3000
MAX_BILLED_PER_SESSION_CENTS = 20000

# Adverse vitals thresholds (PRD §3.5)
SPO2_MIN_THRESHOLD = 85   # strict <: 85 is NOT adverse, 84 is
RPE_MAX_THRESHOLD = 18    # inclusive >=: 18 IS adverse, 17 is not

# Missed-session escalation (PRD §3.5)
MAX_CONSECUTIVE_MISSED = 3

# Session authorization cap (PRD §2.8)
SESSION_CAP = 36

# Clinician turnover buffer (PRD §2.10)
CLINICIAN_TURNOVER_BUFFER_MINUTES = 15

# Maintenance tiering (PRD §3.8)
MAINTENANCE_INTENSIVE_THRESHOLD_PCT = 10.0
MONTHLY_ALLOWANCE = {
    "STANDARD": 4,
    "INTENSIVE": 8,
}

# Server logical clock startup default (PRD §2.4)
CLOCK_START = "2026-05-01T00:00:00Z"
