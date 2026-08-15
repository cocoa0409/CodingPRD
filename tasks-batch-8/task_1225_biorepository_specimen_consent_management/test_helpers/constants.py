"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Consent withdrawal grace period, in hours (PRD §3.1)
    "GRACE_HOURS": 72,
    # Destruction order SLA, in hours (PRD §3.9)
    "DESTRUCTION_SLA_HOURS": 48,
    # Committee size and quorum ratio (PRD §3.6)
    "COMMITTEE_SIZE": 5,
    "QUORUM_RATIO": 0.6,
    "QUORUM_COUNT": 3,
    # Hard cap on revision rounds (PRD §3.6)
    "MAX_REVISION_ROUNDS": 2,
    # Surcharge utilization tier boundary and multiplier (PRD §3.7)
    "SURCHARGE_UTILIZATION": 0.8,
    "SURCHARGE_MULT": 1.25,
    # Handling fee constants (PRD §3.7)
    "BASE_FEE_CENTS": 500,
    "RATE_CENTS_PER_ML": 2.5,
    # Freezer viability ceiling in degree-minutes (PRD §3.4)
    "VIABILITY_LIMIT_DEG_MIN": 120,
    # Default freezer thresholds (PRD §3.4)
    "DEFAULT_WARN_THRESHOLD_C": -70.0,
    "DEFAULT_FAIL_THRESHOLD_C": -60.0,
    # Temperature reading plausibility range (PRD §3.4)
    "TEMP_PLAUSIBLE_MIN_C": -100.0,
    "TEMP_PLAUSIBLE_MAX_C": 25.0,
    # Key access grant mandatory buffer, in hours (PRD §3.8)
    "GRANT_BUFFER_HOURS": 24,
    # Minimum rationale/justification length (PRD §3.6, §3.8)
    "MIN_JUSTIFICATION_CHARS": 20,
}

TEST_DEFAULTS = {
    # The logical clock starts here before any operator intervention (PRD §2.5)
    "CLOCK_START_ISO": "2026-05-01T00:00:00Z",
    "KIT_EXPIRES_AT_FAR": "2027-01-01T00:00:00Z",
    "AGREEMENT_EFFECTIVE_FROM": "2026-04-01T00:00:00Z",
    "AGREEMENT_EFFECTIVE_TO": "2027-04-01T00:00:00Z",
    "CONSENT_EFFECTIVE_FROM": "2026-05-01T00:00:00Z",
    "COLLECTED_AT": "2026-05-02T00:00:00Z",
    "SETPOINT_C": -80.0,
    "SLOT_CAPACITY_ML": 500,
    "VOTE_RATIONALE_APPROVE": "committee approval rationale ok",
    "VOTE_RATIONALE_REJECT": "committee rejection rationale ok",
}
