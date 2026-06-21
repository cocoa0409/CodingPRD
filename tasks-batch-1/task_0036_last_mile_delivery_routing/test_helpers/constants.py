"""Domain thresholds — numeric constants from PRD calculations."""

# Service-failure score (§3.6)
SERVICE_FAILURE = {
    "ATTEMPT_PENALTY": 10,
    "ATTEMPT_ESCALATION": 5,
    "HAZMAT_FAILURE_EXTRA": 8,
    "REDELIVERY_RECOVERY_CREDIT": 6,
    "RETURN_PENALTY": 20,
}

# Redelivery surcharge (§3.5)
REDELIVERY_SURCHARGE = {
    "SERVICE_BASE": {"GROUND": 300, "EXPRESS": 500, "PRIORITY": 800},
    "ATTEMPT_STEP": 150,
    "SIGNATURE_EXTRA": 120,
    "HAZMAT_MULT": 1.5,
    "MAX_ATTEMPTS": 3,
}

# Sort handling fee manifest (§3.8)
HANDLING_FEE = {
    "HANDLING_BASE_CENTS": 50,
    "PER_KG_CENTS": 12.5,
}

# Appointment window buffer (§3.7)
APPOINTMENT_BUFFER_MIN = 30

MAX_ATTEMPTS = 3
