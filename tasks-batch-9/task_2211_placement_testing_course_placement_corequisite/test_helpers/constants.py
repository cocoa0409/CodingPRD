"""Domain thresholds — numeric constants named by the PRD's calculations."""

# --------------------------------------------------------------------------- #
# Logical clock (PRD §2.5)
# --------------------------------------------------------------------------- #
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------- #
# Scoring and the retake budget (PRD §3.3)
# --------------------------------------------------------------------------- #
THRESHOLDS = {
    "SCALED_SCORE_MULTIPLIER": 6.25,
    "IRREGULARITY_PENALTY": 25,
    "MIN_SCALED_SCORE": 0,
    "MAX_SCALED_SCORE": 1000,
    "MIN_RAW_SCORE": 0,
    "MAX_RAW_SCORE": 160,
    "MAX_ATTEMPTS_PER_SUBJECT": 3,
    "RETAKE_TIER_1_DAYS": 14,
    "RETAKE_TIER_2_DAYS": 30,
    "RETAKE_TIER_3_DAYS": 180,
    "ROOM_TURNAROUND_MINUTES": 30,
    "PROCTOR_DAILY_CAP_MINUTES": 480,
    "MAX_SESSION_MINUTES": 480,
    # Confidence, validity and staleness (PRD §3.5)
    "TRANSCRIPT_WEIGHT": 0.5,
    "TEST_WEIGHT": 0.35,
    "SELF_GUIDED_WEIGHT": 0.15,
    "SELF_GUIDED_COMPONENT_VALUE": 60.00,
    "TRANSCRIPT_GPA_SCALE": 4.00,
    "TEST_SCORE_SCALE": 1000,
    "COMPONENT_CAP": 100.00,
    "VALIDITY_TIER_HIGH_MIN": 85.0,
    "VALIDITY_TIER_MID_MIN": 70.0,
    "VALIDITY_DAYS_HIGH": 730,
    "VALIDITY_DAYS_MID": 365,
    "VALIDITY_DAYS_FLOOR": 180,
    "STALENESS_GRACE_DAYS": 1095,
    "STALENESS_DIVISOR": 73.0,
    "STALENESS_CAP": 20.0,
    "EVIDENCE_VERIFY_MIN_CONFIDENCE": 70.0,
    # Appeals (PRD §3.7)
    "APPEAL_FILING_WINDOW_DAYS": 30,
    "APPEAL_RESUBMISSION_WINDOW_DAYS": 14,
    "APPEAL_ROUND_LIMIT": 2,
    "APPEAL_OVERRIDE_CONFIDENCE": 90.0,
    "APPEAL_OVERRIDE_VALIDITY_DAYS": 365,
    # Registration (PRD §3.9)
    "MAX_TERM_UNITS": 18.0,
    "WAITLIST_CAP": 10,
    # Validation studies (PRD §3.4)
    "MIN_SUBGROUP_N": 10,
    "VALIDATION_MIN_SUCCESS_RATE": 0.7000,
    "DI_MIN_INDEX": 0.8000,
    # Equity report (PRD §3.9)
    "EQUITY_LOOKAHEAD_DAYS": 240,
}

# Grade ranking used by prerequisite satisfaction (PRD §3.9).
GRADE_RANK = {
    "A": 4,
    "B": 3,
    "C": 2,
    "P": 2,
    "D": 1,
    "F": 0,
    "NP": 0,
    "W": 0,
    None: 0,
}

# Measure precedence — the selector's second sort key (PRD §3.5).
MEASURE_PRECEDENCE = {
    "TRANSCRIPT_GPA": 0,
    "TEST_SCORE": 1,
    "SELF_GUIDED": 2,
}

SUCCESS_GRADES = ["A", "B", "C", "P"]

TEST_DEFAULTS = {
    "TERM_CODE": "2026FA",
    "ROOM_CODE": "R01",
    "SEAT_CAPACITY": 30,
    "SECTION_SEAT_CAPACITY": 30,
    "SESSION_STARTS_AT": "2026-08-10T09:00:00Z",
    "SESSION_ENDS_AT": "2026-08-10T11:00:00Z",
    "MEETS_START_AT": "2026-09-01T09:00:00Z",
    "MEETS_END_AT": "2026-09-01T10:00:00Z",
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "OVERRIDE_EXPIRES_AT": "2027-01-01T00:00:00Z",
}
