"""Domain thresholds — numeric constants named in the PRD."""

# Logical clock: before any call, reads exactly this instant (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Escalation: the 3rd consecutive out-of-range result escalates (PRD §3.5).
    "ESCALATION_THRESHOLD": 3,
    # Depletion alert window for auto-drafted replenishment orders (PRD §3.5).
    "DEPLETION_ALERT_DAYS": 14,
    # Trailing telemetry consumption window (PRD §3.3).
    "TELEMETRY_WINDOW_DAYS": 7,
    # Water-savings baseline cycles of concentration (PRD §3.8).
    "BASELINE_COC": 3.0,
    # Coupon rating: exactly 30 days of exposure is reliable (PRD §3.6).
    "RELIABLE_MIN_DAYS": 30,
    # Closed-interval re-passivation buffer for rack positions (PRD §3.6).
    "REPASSIVATION_BUFFER_DAYS": 7,
    # Delinquency grace beyond validation_due_at (PRD §3.7).
    "DELINQUENT_GRACE_DAYS": 14,
    # Invoice aging: OVERDUE once clock passes period_end + 30 days (PRD §2.4).
    "INVOICE_OVERDUE_DAYS": 30,
    # LSI classification bands, both boundaries inclusive (PRD §3.4).
    "SCALE_THRESHOLD": 2.5,
    "CORROSIVE_THRESHOLD": -2.5,
}

CONVERSIONS = {
    "ML_PER_GAL": 3785.411,
    "MPY_CONSTANT": 22300,
    "TDS_CONDUCTIVITY_FACTOR": 0.7,
    "SECONDS_PER_DAY": 86400,
}

TEST_DEFAULTS = {
    "RECIRCULATION_RATE_GPM": 300,
    "SYSTEM_VOLUME_GAL": 6000,
    "CONTAINER_SIZE_GAL": 55,
    "ACTIVE_PCT": 10,
    "UNIT_PRICE_CENTS_PER_GAL": 100,
    "CONTRACT_PRICE_CENTS_PER_GAL": 90,
    "CAPACITY_CAP_ML_PER_MIN": 50,
    "PROPOSED_COC": 3.0,
    "INHIBITOR_TARGET_PPM": 4,
    "PH_MIN": 7.0,
    "PH_MAX": 9.5,
    "CONDUCTIVITY_MAX_UMHOS": 3000,
    "SERVICE_RATE_CENTS_PER_MONTH": 0,
}
