"""Domain thresholds — numeric constants from PRD calculation rules."""

# Logical clock: the position the clock reads before any call sets it.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Bed-hold expiry minutes by case acuity (PRD acceptance section).
HOLD_MINUTES = {"CRITICAL": 60, "EMERGENT": 120, "URGENT": 240, "STABLE": 480}

# Insurance SLA minutes by EMTALA obligation (PRD payer-notification section).
SLA_MINUTES = {
    "EMTALA_APPLIES": 60,
    "EMERGENCY_EXCEPTION": 60,
    "EMTALA_NOT_APPLIES": 240,
}

# Transport estimate constants (PRD transport section).
SPEED_MPH = {
    "GROUND_BLS": 40,
    "GROUND_ALS": 45,
    "AIR_ROTOR": 120,
    "AIR_FIXED_WING": 160,
}
MODE_OVERHEAD = {
    "GROUND_BLS": 10,
    "GROUND_ALS": 10,
    "AIR_ROTOR": 25,
    "AIR_FIXED_WING": 45,
}
CREW_BUFFER = {"BLS": 0, "ALS": 0, "CCT": 10, "CRITICAL_CARE": 15}
CRITICAL_ACUITY_SURCHARGE = 10

# Crew minimum per acuity (PRD transport section).
CREW_REQUIRED = {
    "CRITICAL": "CCT",
    "EMERGENT": "ALS",
    "URGENT": "BLS",
    "STABLE": "BLS",
}

# Air-mode minimum distances, inclusive (PRD transport section).
AIR_MIN_DISTANCE = {"AIR_ROTOR": 30, "AIR_FIXED_WING": 100}

# Occupancy saturation hysteresis (PRD occupancy section).
SATURATION_ENTER_PCT = 95.0
SATURATION_EXIT_PCT = 90.0
AUTO_DIVERSION_HOURS = 4

# Refusal EMTALA risk scoring (PRD refusal section).
REFUSAL_CATEGORY_BASE = {
    "NO_BED_AVAILABLE": 30,
    "CAPABILITY_UNAVAILABLE": 25,
    "DIVERSION_ACTIVE": 40,
    "UNSTABLE_FOR_TRANSFER": 10,
    "CAPACITY_EXCEEDED": 20,
}
REFUSAL_OBLIGATION_ADD = {
    "EMTALA_APPLIES": 50,
    "EMERGENCY_EXCEPTION": 20,
    "EMTALA_NOT_APPLIES": 0,
    "UNDETERMINED": 0,
}
REFUSAL_PRIOR_CAP = 3
REFUSAL_PRIOR_POINTS = 10
RISK_HIGH_MIN = 70
RISK_ELEVATED_MIN = 40

# Quality review scoring (PRD quality-review section).
TIMELINESS_TARGET_MINUTES = 240
TIMELINESS_PENALTY_PER_MINUTE = 0.25
W_TIMELINESS = 0.40
W_DOCUMENTATION = 0.35
W_PROTOCOL = 0.25
PROTOCOL_REFUSAL_DEDUCT = 20
PROTOCOL_LATE_NOTIFICATION_DEDUCT = 30
PROTOCOL_EXPIRED_HOLD_DEDUCT = 40

# Validation minimum lengths.
REFUSAL_NARRATIVE_MIN = 50
REVIEW_FINDINGS_MIN = 30
CERTIFICATION_MIN = 30

# Reusable compliant narratives (length-safe).
DEFAULT_REFUSAL_NARRATIVE = (
    "Refusal documented per transfer-center policy; no capacity available tonight."
)
DEFAULT_REVIEW_FINDINGS = (
    "Reviewed the timeline, documentation, and communications; findings recorded."
)
DEFAULT_CERTIFICATION = (
    "Patient requires emergent intervention; benefits of transfer outweigh risks."
)
