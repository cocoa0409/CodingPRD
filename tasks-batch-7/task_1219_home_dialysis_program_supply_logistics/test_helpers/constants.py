"""Domain thresholds — numeric constants from PRD calculation rules."""

THRESHOLDS = {
    # PRD 3.2 — a score of at least 80 passes
    "MODULE_PASS_PCT": 80,
    # PRD 3.3 — assessment evaluation
    "SQFT_TO_UNITS": 4,
    "MAX_STORAGE_UNITS": 400,
    "MIN_STORAGE_SQFT": 25,
    "CHLORAMINE_MAX_PPM": 0.1,
    # PRD 3.5 — order money
    "BASE_HANDLING_CENTS": 500,
    "VOLUME_DISCOUNT_THRESHOLD_CENTS": 20000,
    "VOLUME_DISCOUNT_RATIO": 0.05,
    "WEEKS_PER_MONTH": 4,
    # PRD 3.8 — return credit tiers
    "RETURN_FULL_CREDIT_LIMIT": 10,
    "RETURN_OVERAGE_CREDIT_RATIO": 0.5,
    # PRD 3.4 — maintenance interval
    "MAINTENANCE_INTERVAL_HOURS": 500,
    # PRD 2.10 / 3.x — time constants
    "RECERT_DAYS": 365,
    "ASSESSMENT_VALIDITY_DAYS": 730,
    "DRILL_VALIDITY_DAYS": 90,
    "REVIEW_SLA_DAYS": 5,
    "ROLLING_WINDOW_DAYS": 28,
    # PRD 3.7 — slot guards
    "SLOT_MIN_MINUTES": 60,
    "SLOT_MAX_MINUTES": 480,
    "SLOT_DAILY_CAP": 2,
    # Delivery appointment window limits (PRD 3.5)
    "APPT_MIN_MINUTES": 120,
    "APPT_MAX_MINUTES": 720,
}

TEST_DEFAULTS = {
    "PROGRAM_NAME": "HD Program",
    "REVIEW_CADENCE_TREATMENTS": 2,
    "MAX_MISSED_LOG_STREAK": 3,
    "WASTE_RATIO_ALERT_THRESHOLD": 0.1,
    "PATIENT_FULL_NAME": "Pat Zero",
    "PRESCRIPTION_TREATMENTS_PER_WEEK": 3,
    "PRESCRIPTION_UNITS_PER_TREATMENT": 6,
    "MACHINE_MODEL": "HomeX",
    "ORDER_MONTH": "2026-05",
    "STORAGE_AREA_SQFT": 100,
    "CHLORAMINE_OK_PPM": 0.05,
    # Startup logical clock per PRD 2.5
    "CLOCK_START": "2026-05-01T00:00:00Z",
}

# Canonical single-SKU catalog used by most fixtures.
DEFAULT_CATALOG = [
    {
        "sku": "DIALYSATE_2L",
        "name": "Dialysate 2L bag",
        "unit_price_cents": 1200,
        "handling_rate_cents": 10.5,
        "unit_credit_cents": 300,
    },
]
