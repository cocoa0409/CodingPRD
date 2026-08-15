"""Domain thresholds and shared values — numeric constants from the PRD."""

# Fixed startup reading of the logical clock (PRD section on the logical
# program clock: before any clock-setting call, the clock reads exactly this).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Risk classification (PRD section on enrollment and risk classification).
    "RISK_CAPACITY_CAP": 40,
    "RISK_EQUIPMENT_CAP": 30,
    "RISK_HIGH_MIN": 70,       # score >= 70 is HIGH (inclusive)
    "RISK_MEDIUM_MIN": 40,     # score >= 40 is MEDIUM (inclusive)
    "CUISINE_POINTS": {"LOW_GREASE": 10, "MEDIUM_GREASE": 20, "HIGH_GREASE": 30},
    # Pumping cadence per risk class (days).
    "FREQ_HIGH_DAYS": 90,
    "FREQ_MEDIUM_DAYS": 180,
    "FREQ_LOW_DAYS": 365,
    # Interceptor sizing (PRD section on interceptor sizing).
    "MIN_CAPACITY_GAL": 50,
    "SEAT_GAL": 2,
    "FRYER_GAL": 15,
    "CHARBROILER_GAL": 40,
    "RETENTION_MINUTES": 30,
    "CUISINE_ADDER_GAL": {"LOW_GREASE": 0, "MEDIUM_GREASE": 25, "HIGH_GREASE": 50},
    # Inspection scoring.
    "INSPECTION_PASS_SCORE": 70,     # exactly 70 passes; 69 fails
    "DEDUCTION_MINOR": 3,
    "DEDUCTION_MAJOR": 8,
    "DEDUCTION_CRITICAL": 20,
    # Violation cure windows (days from creation) and citation fines (cents).
    "CURE_DAYS": {"MINOR": 30, "MAJOR": 14, "CRITICAL": 3},
    "FINE_CENTS": {"MINOR": 10000, "MAJOR": 50000, "CRITICAL": 250000},
    # Disposal reconciliation tolerance: ratio must not exceed 0.05.
    "DISPOSAL_TOLERANCE": 0.05,
    # Hauler auto-suspension threshold.
    "MISMATCH_SUSPEND_COUNT": 3,
    # Same-zone campaign buffer in days.
    "CAMPAIGN_ZONE_BUFFER_DAYS": 14,
}

TEST_DEFAULTS = {
    "PUMPED_VOLUME_GAL": 1000,
    "PUMP_DATE": "2026-08-01T00:00:00Z",
    "DISPOSED_AT": "2026-08-01T12:00:00Z",
    "INSURANCE_EXPIRES_ON": "2027-06-01T00:00:00Z",
    "VARIANCE_EFFECTIVE_FROM": "2027-01-01T00:00:00Z",
    "VARIANCE_EFFECTIVE_TO": "2027-07-01T00:00:00Z",
}
