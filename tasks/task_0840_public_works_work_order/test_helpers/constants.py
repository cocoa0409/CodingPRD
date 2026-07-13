"""Domain thresholds — numeric constants from the PRD's calculations."""

# PCI / condition scoring (PRD §3.3, §3.1)
PCI = {
    "AGE_PENALTY_PER_YEAR": 1.5,
    "MAX_AGE_PENALTY": 25,
    "PREVENTIVE_AGE_FACTOR": 0.5,
    "SEVERITY_WEIGHT": {"ROAD": 1.0, "SIGN": 0.6, "SIGNAL": 0.8},
}

# condition_state thresholds (PRD §3.1) — inclusive lower bounds
CONDITION_THRESHOLDS = {
    "GOOD_MIN": 85,
    "FAIR_MIN": 70,
    "POOR_MIN": 55,
}

# tiered labor cost (PRD §3.5)
LABOR = {
    "OT_THRESHOLD_HOURS": 8,
    "OT_MULTIPLIER": 1.5,
}

# capitalization / betterment (PRD §3.8)
CAPITALIZATION = {
    "CAPITALIZATION_THRESHOLD_CENTS": 500000,
    "BETTERMENT_PCT": 0.25,
}

# 311 priority + SLA (PRD §3.2)
SLA_HOURS = {
    "EMERGENCY": 4,
    "HIGH": 48,
    "MEDIUM": 120,
    "LOW": 240,
}
PRIORITY_BY_CATEGORY = {
    "SIGNAL_OUTAGE": "EMERGENCY",
    "POTHOLE": "HIGH",
    "SIGN_DAMAGE": "MEDIUM",
}

# crew dispatch mobilization buffer (PRD §3.5)
MOBILIZATION_BUFFER_MINUTES = 30

# logical clock default at server startup (PRD §2.7)
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"
