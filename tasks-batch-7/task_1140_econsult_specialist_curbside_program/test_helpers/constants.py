"""Domain thresholds and shared test constants (from PRD calculation rules)."""

THRESHOLDS = {
    # Routing selector eligibility ceiling on open consults (strict <).
    "MAX_OPEN_CONSULTS": 5,
    # Clarification round ceiling per consult.
    "MAX_CLARIFICATION_ROUNDS": 2,
    # Quality blend thresholds (basis points).
    "DEFAULT_REVIEW_COMPONENT_BPS": 8500,
    "DEFAULT_TIMELINESS_BPS": 10000,
    "DEMOTE_BELOW_BPS": 7000,
    "RECOVER_AT_BPS": 7500,
    "SUSPEND_BELOW_BPS": 5000,
    "REBUKE_SUSPEND_COUNT": 2,
    # Final-response compensation quality bands (basis points).
    "BAND_EXCELLENT_BPS": 12000,
    "BAND_STANDARD_BPS": 10000,
    "BAND_REDUCED_BPS": 8000,
    "BAND_MINIMAL_BPS": 5000,
    # Verdict band split for review composite.
    "VERDICT_PASS_MIN_BPS": 6000,
    # Conversion scheduling buffer (minutes, applied on both sides).
    "CONVERSION_BUFFER_MINUTES": 30,
    # Expiry rules.
    "EXPIRY_GRACE_HOURS": 24,
    "QUEUE_TTL_HOURS": 72,
}

# Standard fee schedule reused across scenarios (integer cents).
STANDARD_TRACK = {
    "response_time_target_hours": 48,
    "urgent_target_hours": 12,
    "base_response_fee_cents": 10000,
    "conversion_response_fee_cents": 8000,
    "clarification_fee_cents": 2500,
    "late_penalty_cents": 3000,
    "monthly_billing_cap_cents": 1000000,
}

# Logical-clock anchors used throughout the suite.
CLOCK_START = "2026-05-01T00:00:00Z"      # server startup default
T_JUNE_01 = "2026-06-01T00:00:00Z"
T_JUNE_03_SLA = "2026-06-03T00:00:00Z"    # 48h after T_JUNE_01
T_JUNE_03_LATE = "2026-06-03T01:00:00Z"   # 1h past the 48h SLA, inside grace
T_JUNE_04_SWEEP = "2026-06-04T01:00:00Z"  # past sla+24h grace and past queue TTL

# A window covering every consult created in June 2026 (half-open).
WINDOW_START = "2026-05-01T00:00:00Z"
WINDOW_END = "2027-01-01T00:00:00Z"
