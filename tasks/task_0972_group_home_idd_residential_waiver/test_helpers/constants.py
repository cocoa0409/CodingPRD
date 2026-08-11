"""Domain thresholds — numeric constants from PRD calculations."""

THRESHOLDS = {
    # Staffing weighting (PRD staffing-check)
    "WHEELCHAIR_WEIGHT": 2,
    "DEFAULT_WEIGHT": 1,
    "DAY_RATIO_DEFAULT": 4,
    "NIGHT_RATIO_DEFAULT": 8,
    # Census projection window in days
    "PROJECTION_DAYS": 14,
    # Billable unit calculation
    "UNIT_MINUTES": 15,
    "DAY_UNIT_MIN_MINUTES": 360,
    # Recoupment rate on full payments (10% of gross)
    "RECOUP_RATE_NUM": 10,
    "RECOUP_RATE_DEN": 100,
    # Incident reporting windows (hours)
    "CRITICAL_WINDOW_HOURS": 24,
    "HIGH_WINDOW_HOURS": 48,
    "OTHER_WINDOW_HOURS": 72,
    # Medication adherence window (days, closed both ends)
    "ADHERENCE_WINDOW_DAYS": 30,
    # MAR administered_time tolerance (minutes)
    "MAR_WINDOW_MINUTES": 60,
    # Shift rest buffer (hours)
    "SHIFT_REST_BUFFER_HOURS": 8,
    # Vehicle capacity in occupied slots (wheelchair seat counts 2)
    "VEHICLE_SLOT_CAPACITY": 8,
    "WHEELCHAIR_SLOT_WEIGHT": 2,
    # Fiscal caps in cents
    "PER_AUTH_CAP_CENTS": 5_000_000,
    "PER_INDIVIDUAL_CAP_CENTS": 20_000_000,
    # BSP review windows (days)
    "BSP_REVIEW_DAYS_LEVEL_2": 180,
    "BSP_REVIEW_DAYS_LEVEL_1": 365,
}

TEST_DEFAULTS = {
    "AGENCY_NAME": "Agency A",
    "HOME_NAME": "Home A",
    "LICENSE_NUMBER": "LIC-1",
    "GOALS_SUMMARY": "Community integration goals",
    "PLAN_YEAR_START": "2026-01-01",
    "PLAN_YEAR_END": "2026-12-31",
    "HIRE_DATE": "2025-01-15",
    "DEFAULT_AUTH_UNITS": 24,
    "DEFAULT_RATE_CENTS": 1500,
    "SPAN_START": "2026-01-01",
    "SPAN_END": "2026-12-31",
    "BASE_CLOCK": "2026-06-01T00:00:00Z",
}

# Logical clock startup instant (PRD: the Logical Clock).
CLOCK_STARTUP_ISO = "2026-05-01T00:00:00Z"
