"""Domain thresholds and canonical test data drawn from the PRD's formulas."""

# Numeric constants the PRD pins inside its formulas.
THRESHOLDS = {
    # PRD §2.5 — logical clock value at server startup.
    "CLOCK_STARTUP_UTC": "2026-08-01T00:00:00Z",
    # PRD §3.4 — one-day shoulder buffer on the attendee overlap check.
    "SHOULDER_BUFFER_DAYS": 1,
    # PRD §3.2 — negotiation cycle capped at three submissions.
    "MAX_REVISION_ROUND": 3,
    # PRD §3.6 — pace target ratio of 80 percent.
    "PACE_TARGET_RATIO": 0.80,
    # PRD §3.7 — allowed pickup ratio of 80 percent and the penalty tiers.
    "ALLOWED_PICKUP_RATIO": 0.80,
    "TIER_1_MAX_RATIO": 0.10,
    "TIER_1_PCT": 0.50,
    "TIER_2_MAX_RATIO": 0.25,
    "TIER_2_PCT": 0.70,
    "TIER_3_PCT": 0.90,
    # PRD §3.8 — rogue vendor risk score.
    "RISK_BASE": 10,
    "RISK_PER_INCIDENT": 25,
    "RISK_PER_CHANNEL": 15,
    "RISK_PAYMENT_BONUS": 20,
    "RISK_SCORE_MIN": 0,
    "RISK_SCORE_MAX": 100,
    "RISK_REVIEW_THRESHOLD": 60,
    "HOUSING_RISK_WARNING_THRESHOLD": 2,
    # PRD §3.9 — dispute tolerance band.
    "VARIANCE_TOLERANCE_FLOOR_CENTS": 5000,
    "VARIANCE_TOLERANCE_PCT": 0.01,
}


# Canonical program values shared by the fixtures.
TEST_DEFAULTS = {
    "EVENT_NAME": "Annual Summit",
    "EVENT_CODE": "SUM26",
    "EVENT_START_DATE": "2026-09-14",
    "EVENT_END_DATE": "2026-09-18",
    "CUTOFF_DATE": "2026-08-21",
    "ATTRITION_DEADLINE_DATE": "2026-08-15",
    "STANDARD_COMMISSION_PCT": 0.10,
    "STANDARD_REBATE_PER_ROOM_NIGHT_CENTS": 500,
    "HOTEL_NAME": "Grand Plaza",
    "DISTANCE_TO_VENUE_MILES": 0.3,
    "ROOM_TAX_PCT": 0.1475,
    "TOTAL_ROOMS": 400,
    "CONTRACTED_ROOMS_PER_NIGHT": 10,
    "NEGOTIATED_NIGHTLY_RATE_CENTS": 21900,
    "COMMISSION_PCT": 0.12,
    "REBATE_PER_ROOM_NIGHT_CENTS": 700,
    "REDUCTION_RIGHTS_PCT": 0.20,
    "CONFIRMATION_NUMBER": "CN-SUM26-001",
    # Opaque operator identities (PRD §2.1).
    "COORDINATOR_ID": "coord-1",
    "CONTROLLER_ID": "ctrl-1",
    "COMPLIANCE_OFFICER_ID": "comp-1",
}
