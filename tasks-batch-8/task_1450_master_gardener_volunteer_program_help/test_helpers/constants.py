"""Domain thresholds and numeric constants from the PRD."""

THRESHOLDS = {
    # Composite score weights and caps (PRD §3.1)
    "ESSAY_WEIGHT": 0.4,
    "INTERVIEW_WEIGHT": 0.6,
    "COUNTY_PRIORITY_BONUS": 4,
    "COMPOSITE_CAP": 100,
    # Recognition tiers (PRD §3.8)
    "TIER_SILVER_MIN": 20.0,
    "TIER_GOLD_MIN": 40.0,
    "GOLD_OUTREACH_BONUS": 0.25,
    # Hardship exemption factor (PRD §3.8)
    "HARDSHIP_FACTOR": 0.5,
    # Specialist scoring (PRD §3.5)
    "LATE_PENALTY": 5,
    "RETURN_PENALTY": 3,
    "SCORE_FLOOR": 0,
    "INITIAL_SPECIALIST_SCORE": 100,
    # Referral SLA (PRD §3.5)
    "SLA_HOURS": 48,
    # Rotation fairness (PRD §3.7)
    "CONSECUTIVE_WEEK_LIMIT": 2,
    # Travel buffer between shifts at different locations (PRD §3.4)
    "TRAVEL_BUFFER_MINUTES": 30,
    # No-show strike gate (PRD §3.4)
    "NO_SHOW_LIMIT": 3,
    # Hour quantum and per-entry max (PRD §2.7)
    "HOUR_QUANTUM": 0.25,
    "MAX_ENTRY_HOURS": 12.0,
    # Project credit cap ceiling (PRD §3.6)
    "PROJECT_CAP_MULTIPLIER": 1.25,
    "PROJECT_CAP_MAX": 20.0,
}

# The logical clock's fixed startup default (PRD §2.5)
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "YEAR_LABEL": "2026",
    "START_DATE": "2026-01-01",
    "END_DATE": "2026-12-31",
    "ADMISSION_CAPACITY": 5,
    "HOUR_REQUIREMENT": 40.0,
    "CE_REQUIREMENT": 10.0,
    "TRAINING_MODULE_COUNT": 5,
    "TRAINING_PASS_QUIZ_AVERAGE": 70.0,
    "TRAINING_CAPACITY": 10,
    "RECERT_OPENS_AT": "2026-11-01T00:00:00Z",
}
