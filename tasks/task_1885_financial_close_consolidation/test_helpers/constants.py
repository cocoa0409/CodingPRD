"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # §3.6 reconciliation tolerance: is_within_tolerance uses abs(diff) <= 500
    "RECON_TOLERANCE_MINOR": 500,
    # §3.8 elimination tolerance: abs(residual_minor) <= 500
    "ELIM_TOLERANCE_MINOR": 500,
    # §3.9 flux percentage threshold: variance_pct >= 10.0
    "FLUX_PCT_THRESHOLD": 10.0,
    # §3.6 aging: days_past >= 31 lands in AGE_31_60
    "AGING_OVER_30_DAYS": 30,
    # §3.4 accrual estimation prior window
    "PRIOR_WINDOW": 3,
    # §3.7 temporal monetary fraction (constant 1.0 for the modeled populations)
    "MONETARY_FRACTION": 1.0,
    # seconds per day used in aging / days-to-close computations
    "DAY_SECONDS": 86400,
}

TEST_DEFAULTS = {
    "MATERIALITY_THRESHOLD_MINOR": 10000,
    "REPORTING_CURRENCY": "USD",
    # Period P1 canonical window
    "P1_START": "2026-01-01T00:00:00Z",
    "P1_END": "2026-01-31T00:00:00Z",
    # Logical clock instant safely inside P1
    "CLOCK_IN_PERIOD": "2026-01-15T00:00:00Z",
}
