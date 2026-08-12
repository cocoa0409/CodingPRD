"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # HSA reorder floor: a final claim denial that drops the balance below this
    # suspends every ACTIVE resupply program of the patient.
    "REORDER_FLOOR_CENTS": 500,
    # Adherence: a final score strictly below this auto-suspends on return.
    "ADHERENCE_SUSPEND_THRESHOLD": 0.50,
    # Fitting samples: rolling closed lookback window and per-category cap.
    "SAMPLE_WINDOW_DAYS": 90,
    "MAX_SAMPLES_PER_CATEGORY_PER_90D": 2,
}

# Logical clock startup default (PRD: exactly 2026-05-01T00:00:00Z before any set).
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "RX_MONTHLY_QUANTITY": 20,
    "MEDICARE_CYCLE_MONTHS": 3,
    "OSTOMY_PACK_FEE_CENTS": 1850,
    "OSTOMY_PACK_SIZE": 10,
    "OSTOMY_RETAIL_PRICE_CENTS": 300,
    "OSTOMY_MAX_UNITS_PER_CYCLE": 60,
    "WOUND_PACK_FEE_CENTS": 999,
    "WOUND_PACK_SIZE": 8,
    "WOUND_RETAIL_PRICE_CENTS": 650,
    "WOUND_MAX_UNITS_PER_CYCLE": 30,
}
