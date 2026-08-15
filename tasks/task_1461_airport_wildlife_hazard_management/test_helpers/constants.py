"""Domain thresholds — numeric constants from the PRD business rules."""

THRESHOLDS = {
    # Hazard-level strike thresholds (PRD hazard recompute rules)
    "STRIKES_CRITICAL_HIGH_RISK": 2,     # high-risk count >= 2 -> CRITICAL
    "STRIKES_HIGH_HIGH_RISK": 1,         # high-risk count == 1 -> HIGH
    "STRIKES_HIGH_COUNT": 10,            # total count >= 10 -> HIGH
    "STRIKES_ELEVATED_COUNT": 5,         # total count >= 5 -> ELEVATED
    # Rolling window
    "WINDOW_DAYS": 365,
    # Mandatory-mitigation composite threshold
    "MANDATORY_MITIGATION_THRESHOLD": 60,
    # Runway closure rules
    "CLOSURE_BUFFER_MINUTES": 15,
    "CLOSURE_MAX_DURATION_HOURS": 4,
    # Trends
    "LOOKBACK_DAYS_DEFAULT": 365,
    # Training
    "EXPIRING_SOON_DAYS": 30,
}

TEST_DEFAULTS = {
    "DEFAULT_CLOCK": "2026-08-01T00:00:00Z",
    "PLAN_CYCLE_YEAR": 2026,
}
