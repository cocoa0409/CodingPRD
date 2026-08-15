"""Domain thresholds — numeric constants from PRD calculations."""

# PRD §2.5: logical clock startup value before any clock-setting call.
CLOCK_STARTUP_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # PRD §3.7 adverse impact
    "FOUR_FIFTHS_THRESHOLD": 0.8000,
    "MIN_GROUP_N": 2,
    "PROJECTED_SELECTION_COMPOSITE": 0.7000,
    # PRD §3.6 calibration
    "CALIBRATED_THRESHOLD": 0.7000,
    "LAPSE_FLOOR": 0.5000,
    "LENIENCY_PENALTY_FACTOR": 0.5,
    "CALIBRATION_LAPSE_DAYS": 365,
    # PRD §3.8 decision quorum
    "MIN_QUORUM": 2,
    "MAX_QUORUM": 3,
    # PRD §3.6 sessions / scorecards
    "SESSION_MIN_MINUTES": 15,
    "SESSION_MAX_MINUTES": 240,
    "SCORECARD_SUBMIT_WINDOW_HOURS": 72,
    # PRD §3.4 requisitions / cycles
    "DEFAULT_RETENTION_DAYS": 730,
    "MIN_RETENTION_DAYS": 180,
    "MAX_RETENTION_DAYS": 3650,
    "DEFAULT_MAX_SESSIONS_PER_DAY": 8,
    # PRD §3.3 rubric
    "RUBRIC_WEIGHT_SUM": 1.0000,
    "RUBRIC_MIN_ITEMS": 2,
    # PRD §3.8 text lengths
    "RATIONALE_MIN_LENGTH": 50,
    "FEEDBACK_TEXT_MIN_LENGTH": 20,
    "VOID_REASON_MIN_LENGTH": 20,
    "JUSTIFICATION_MIN_LENGTH": 20,
    "RESOLUTION_NOTE_MIN_LENGTH": 20,
    "LEDGER_NOTE_MIN_LENGTH": 10,
    "DENY_DECISION_NOTE_MIN_LENGTH": 10,
}

# Canonical rubric used across the suite: COMM weight 0.6 / scale 5, ANAL 0.4 / 5.
DEFAULT_RUBRIC_ITEMS = [
    {"competency_code": "COMM", "weight": 0.6, "scale_max": 5},
    {"competency_code": "ANAL", "weight": 0.4, "scale_max": 5},
]

# Canonical administration window used across the suite.
DEFAULT_WINDOW_START = "2026-08-10T00:00:00Z"
DEFAULT_WINDOW_END = "2026-08-20T00:00:00Z"
DEFAULT_SCHEDULED_FOR = "2026-08-10T09:00:00Z"
DEFAULT_WORK_INSTANT = "2026-08-10T09:00:00Z"

TEST_DEFAULTS = {
    "VENDOR_NAME": "Acme Assessments",
    "INSTRUMENT_CODE": "COG-A",
    "INSTRUMENT_TITLE": "Cognitive Battery A",
    "INSTRUMENT_MAX_SCORE": 100,
    "INSTRUMENT_PASS_FLOOR": 40,
    "GUIDE_TITLE": "Structured Guide v1",
    "REQUISITION_TITLE": "Senior Analyst",
    "REQUISITION_DEPARTMENT": "Risk",
    "REQUISITION_OPENINGS": 2,
    "CYCLE_LABEL": "Fall Cycle",
    "PRACTICE_SCORE": 0.85,
    "EVIDENCE_FROM": "2026-07-01T00:00:00Z",
    "EVIDENCE_UNTIL": "2027-08-01T00:00:00Z",
    "DECISION_RATIONALE": (
        "Candidate demonstrated strong structured problem solving "
        "and communication across panels."
    ),
    "FEEDBACK_TEXT": "Strong panel performance; advance to final round.",
    "VOID_REASON": "Interviewer disclosed a conflict of interest.",
    "FREEZE_REASON_NOTE": "Manual compliance hold for review.",
    "RESOLUTION_NOTE": "Reviewed and cleared by compliance.",
}
