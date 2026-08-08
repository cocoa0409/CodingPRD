"""Domain thresholds — numeric constants from the PRD's calculations."""

THRESHOLDS = {
    # Compliance gate (PRD §3.3 / §2.6)
    "MAX_ABS_DEVIATION_PCT": 5.0,       # inclusive: exactly 5.00% still compliant
    "MAX_OVERALL_RANGE_PCT": 10.0,
    # Compliance-check result thresholds (PRD §3.3)
    "DEVIATION_PASS_PCT": 5.0,
    "DEVIATION_WARN_PCT": 10.0,
    # Provisional voter estimate (PRD §3.6)
    "REGISTRATION_RATE": 0.85,
    # Venue double-booking buffer (PRD §3.4)
    "SETUP_BUFFER_MINUTES": 60,
    # Majority-minority strict threshold (PRD §3.3)
    "MAJORITY_MINORITY_PCT": 50.0,
}

# Clock default at server startup (PRD §2.5)
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"
