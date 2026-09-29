"""Domain thresholds and numeric constants stated by the PRD."""

# The logical clock's startup value.
CLOCK_START_UTC = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # A ratio that lands exactly on 50 percent is substantial.
    "SUBSTANTIAL_THRESHOLD_PCT": 50.00,
    # counted_in_cumulative requires cost_usd at least 500.00.
    "COUNTED_COST_MINIMUM_USD": 500.00,
    # A qualifying repetitive-loss claim pays at least 1000.00.
    "QUALIFYING_CLAIM_MINIMUM_USD": 1000.00,
    # Outreach coverage tiers.
    "OUTREACH_PARTIAL_COVERAGE_PCT": 75.00,
    "OUTREACH_FULL_COVERAGE_PCT": 90.00,
    "OUTREACH_FULL_POINTS": 50,
    "OUTREACH_PARTIAL_POINTS": 25,
    # Sanction tiers: 25 or more is SUSPENDED, 10 or more is ON_PROBATION.
    "SUSPENSION_POINTS": 25,
    "PROBATION_POINTS": 10,
    "PROBATION_CREDIT_POINTS": 4,
    # Severity weights.
    "SEVERITY_WEIGHT_MINOR": 2,
    "SEVERITY_WEIGHT_MAJOR": 6,
    "SEVERITY_WEIGHT_CRITICAL": 12,
    "DEFAULTED_ORDER_PENALTY": 5,
    # Class arithmetic.
    "CLASS_POINTS_PER_BLOCK": 500,
    "WORST_CLASS": 10,
    "BEST_CLASS": 1,
    # Bounded loops (exclusive ceilings).
    "MAX_REVISION_ROUND": 3,
    "MAX_EXTENSION_COUNT": 2,
    # Elevation arithmetic.
    "ZONE_FLOOR_FREEBOARD_FT": {"A": 1.0, "AE": 1.0, "AO": 1.0, "VE": 2.0},
    "SUBSTANTIAL_BUMP_FT": 0.5,
    "FLOODPROOFING_CREDIT_FT": 1.0,
    "NGVD29_OFFSET_FT": -0.85,
    "NAVD88_OFFSET_FT": 0.0,
    # Derived deadlines.
    "PERMIT_EXPIRY_DAYS": 365,
    "APPEAL_WINDOW_DAYS": 30,
    "RETENTION_YEARS": 5,
    "DOC_EXPIRY_YEARS": 5,
    "REPETITIVE_LOSS_WINDOW_YEARS": 10,
    "SWEEP_BUFFER_DAYS": 7,
    # Activity ceilings.
    "A430_FREEBOARD_POINTS_PER_FOOT": 100,
    "A430_FREEBOARD_MAX_FEET": 5.0,
    "A430_CUMULATIVE_SI_POINTS": 90,
    "A430_CUMULATIVE_SI_MIN_YEARS": 10,
    "A420_POINTS_PER_AREA": 50,
    "A420_CAP": 200,
    "A510_POINTS": 60,
}

TEST_DEFAULTS = {
    "FREEBOARD_FT": 1.0,
    "CUMULATIVE_PERIOD_YEARS": 10,
    "MARKET_VALUE_USD": 200_000.00,
    "BASE_FLOOD_ELEVATION_FT": 12.0,
    "HIGHEST_ADJACENT_GRADE_FT": 10.0,
}
