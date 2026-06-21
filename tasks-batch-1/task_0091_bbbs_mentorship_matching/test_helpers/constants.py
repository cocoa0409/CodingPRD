"""Domain thresholds — numeric constants from the PRD's calculations (§3.3–§3.7)."""

# Interest-compatibility scoring weights and clamp (PRD §3.3 "Scoring and selecting").
SCORE_WEIGHTS = {
    "W_INTEREST": 0.6,
    "W_GEO": 0.25,
    "W_CAPACITY": 0.15,
    "CAPACITY_CAP": 10,
}

# Compliance posture day thresholds (PRD §3.6 "Deriving the compliance posture").
COMPLIANCE_DAYS = {
    "AMBER_CONTACT_DAYS": 30,
    "RED_CONTACT_DAYS": 60,
    "AMBER_ACTIVITY_DAYS": 45,
    "CONTACT_INTERVAL_DAYS": 30,
}

# Background-check validity (PRD §3.1, §3.2).
BACKGROUND_CHECK = {
    "VALIDITY_MONTHS": 24,
    "DMV_ADVERSE_TOLERANCE": 1,
    "CRIMINAL_ADVERSE_TOLERANCE": 0,
    "CHILD_ABUSE_REGISTRY_ADVERSE_TOLERANCE": 0,
}

# Outcome-survey Strength-of-Relationship index (PRD §3.7).
OUTCOME_SURVEY = {
    "SOR_W_REL": 0.5,
    "SOR_W_OUT": 0.5,
    "REMATCH_BONUS": 0.5,
    "STRONG_CUTOFF": 4.0,
    "MODERATE_CUTOFF": 2.5,
}

# Per-guardian meeting buffer in minutes (PRD §3.5 double-booking guard).
MEETING_BUFFER_MINUTES = 60

# Pagination bounds (PRD §2.3).
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "MIN_OFFSET": 0}

# A syntactically valid UUID that never refers to a real resource.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
