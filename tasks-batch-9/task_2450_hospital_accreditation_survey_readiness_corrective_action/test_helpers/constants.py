"""Domain thresholds and numeric constants stated by the PRD."""

# The logical clock's fixed starting instant (PRD §2.4) and its rendered form.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_RENDERED = "2026-08-01T00:00:00.000Z"

# Deficiency ticket severity → base day allowance (PRD §3.5).
SEVERITY_DAYS = {
    "LOW": 45,
    "MODERATE": 30,
    "HIGH": 14,
    "IMMEDIATE_THREAT": 1,
}

# Deficiency ticket severity → penalty points (PRD §3.5).
SEVERITY_POINTS = {
    "LOW": 1,
    "MODERATE": 3,
    "HIGH": 7,
    "IMMEDIATE_THREAT": 15,
}

# Observation result → credit used by tracer scoring (PRD §3.4).
OBSERVATION_CREDIT = {
    "COMPLIANT": 1.0,
    "PARTIAL": 0.5,
    "NON_COMPLIANT": 0.0,
}

THRESHOLDS = {
    # Unit posture and readiness (PRD §3.3)
    "POSTURE_RESTRICT_POINTS": 15,
    "PENALTY_CAP": 40,
    "BAND_READY": 90.00,
    "BAND_CONDITIONAL": 75.00,
    "BAND_AT_RISK": 60.00,
    # Chapter early warning (PRD §3.1)
    "CHAPTER_DEFICIENT_LIMIT": 2,
    "CHAPTER_PPR_ESCALATION_LIMIT": 2,
    # Tracer occupancy (PRD §3.4)
    "TRACER_TURNAROUND_MINUTES": 60,
    # Rounding capacity (PRD §3.5)
    "ROUNDING_CAPACITY_PER_TYPE": 2,
    # Survey window prediction (PRD §3.6)
    "WINDOW_OPEN_MONTHS": 18,
    "WINDOW_CLOSE_MONTHS": 36,
    "COMMAND_CENTER_LEAD_DAYS": 30,
    "FOLLOW_UP_DAYS": 60,
    # Finding classification (PRD §3.7)
    "RATE_PATTERN": 0.3400,
    "RATE_WIDESPREAD": 0.8000,
    "HARM_BONUS": 2,
    "RISK_INDEX_CAP": 6,
    "RESPONSE_DEADLINE_DAYS_HIGH": 45,
    "RESPONSE_DEADLINE_DAYS_OTHER": 60,
    # Evidence of standards compliance (PRD §3.8)
    "CLARIFICATION_ROUND_LIMIT": 2,
    "CLARIFICATION_EXTENSION_DAYS": 21,
    "CLARIFICATION_CAP_DAYS": 10,
    # Periodic performance review (PRD §3.9)
    "PPR_RATING_POINTS_COMPLIANT": 100,
    "PPR_RATING_POINTS_PARTIAL": 50,
    "PPR_RATING_POINTS_NON_COMPLIANT": 0,
    "PPR_STATE_POINTS_EVIDENCE_COMPLETE": 100,
    "PPR_STATE_POINTS_MAPPED": 50,
    "OVERSTATEMENT_GAP": 10.00,
    # Pagination (PRD §2.3)
    "PAGINATION_DEFAULT_LIMIT": 10,
    "PAGINATION_MIN_LIMIT": 1,
    "PAGINATION_MAX_LIMIT": 100,
    # Evidence minimum (PRD §3.1)
    "EVIDENCE_MIN_COUNT_DEFAULT": 2,
}

TEST_DEFAULTS = {
    "CHAPTER_CODE": "EC",
    "CHAPTER_NAME": "Environment of Care",
    "CHAPTER_WEIGHT_PCT": 100,
    "STANDARD_CODE": "EC.02.06.01",
    "STANDARD_TITLE": "Safe environment",
    "UNIT_NAME": "ICU-1",
    "UNIT_TYPE": "ICU",
    "BED_COUNT": 12,
    "CYCLE_LABEL": "CYCLE-2026",
}

# Syntactically valid UUIDs that address nothing.
UNKNOWN_UUIDS = {
    "chapter": "11111111-1111-4111-8111-111111111101",
    "standard": "11111111-1111-4111-8111-111111111102",
    "owner_assignment": "11111111-1111-4111-8111-111111111103",
    "evidence": "11111111-1111-4111-8111-111111111104",
    "unit": "11111111-1111-4111-8111-111111111105",
    "tracer": "11111111-1111-4111-8111-111111111106",
    "rounding_session": "11111111-1111-4111-8111-111111111107",
    "ticket": "11111111-1111-4111-8111-111111111108",
    "survey_window": "11111111-1111-4111-8111-111111111109",
    "finding": "11111111-1111-4111-8111-111111111110",
    "ppr": "11111111-1111-4111-8111-111111111111",
}
