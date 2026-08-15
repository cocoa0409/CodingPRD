"""Domain thresholds — numeric constants from the PRD."""

THRESHOLDS = {
    # PRD §3.3: auto-advisory fires when outage extent reaches 500 (inclusive)
    "ADVISORY_OUTAGE_THRESHOLD": 500,
    # PRD §3.5: chlorine residual pass threshold (inclusive)
    "MIN_CHLORINE_MG_L": 0.20,
    # PRD §3.5: minimum spacing between consecutive samples
    "MIN_SAMPLE_SPACING_HOURS": 20,
    # PRD §3.7: claim filing window after confirmation (inclusive)
    "CLAIM_FILING_WINDOW_DAYS": 90,
    # PRD §3.6: restoration deadline after repair
    "RESTORATION_DEADLINE_DAYS": 14,
    # PRD §3.8: repeat-break trailing window
    "REPEAT_BREAK_WINDOW_MONTHS": 36,
    # PRD §3.8: condition posture derivation thresholds
    "WATCH_THRESHOLD": 2,
    "CANDIDATE_THRESHOLD": 3,
    # PRD §3.4: crew dispatch travel buffer
    "TRAVEL_BUFFER_MINUTES": 60,
    # PRD §3.2: anomaly correlation window (absolute difference)
    "CORRELATION_WINDOW_HOURS": 6,
    # PRD §3.4: material waste factor for actual cost
    "MATERIAL_WASTE_FACTOR": 1.10,
}

# Logical clock startup default (PRD §2.4)
LOGICAL_CLOCK_START = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "HOURLY_RATE_CENTS": 6000,
    "EST_PIPE_LENGTH_FT": 4,
}
