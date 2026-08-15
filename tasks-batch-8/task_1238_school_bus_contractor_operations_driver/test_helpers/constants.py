"""Domain thresholds and defaults — numeric constants named in the PRD."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID

NONEXISTENT_UUID = NON_EXISTENT_UUID

# Logical clock value at server startup (PRD section 2.5); never wall-clock.
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # Driver training eligibility (inclusive)
    "REQUIRED_BEHIND_WHEEL_MINUTES": 2400,
    "REQUIRED_CLASSROOM_MINUTES": 1200,
    # Weekly driving-time caps
    "WEEKLY_SOFT_CAP_MINUTES": 2400,
    "WEEKLY_HARD_CAP_MINUTES": 2700,
    # Route doubling
    "MAX_DOUBLING_DELAY_MINUTES": 45,
    # Ridership punctuality
    "ON_TIME_GRACE_MINUTES": 5,
    "TIER_EXCELLENT_X100": 9500,
    "TIER_SATISFACTORY_X100": 9000,
    # Incident SLA hours by severity
    "CRITICAL_SLA_HOURS": 24,
    "HIGH_SLA_HOURS": 72,
    "DEFAULT_SLA_HOURS": 168,
    # Charter cancellation tiers (whole hours before pickup)
    "FREE_CANCEL_HOURS": 72,
    "REDUCED_CANCEL_HOURS": 24,
    # Charter quote shelf life
    "QUOTE_VALID_HOURS": 72,
}

# Standard contract commercial terms used across scenarios.
CONTRACT_DEFAULTS = {
    "daily_rate_per_bus_cents": 50000,
    "school_days_per_year": 180,
    "fuel_base_price_cents": 400,
    "penalty_mode": "FLAT_PER_ROUTE",
    "shortage_penalty_flat_cents": 15000,
    "shortage_penalty_per_student_minute_cents": 25,
    "assumed_minutes_per_missed_route": 45,
    "monthly_cap_cents": 10000000,
    "charter_hourly_rate_cents": 12000,
    "charter_per_mile_cents": 250,
    "start_date": "2026-01-01",
    "end_date": "2026-12-31",
}

TEST_DEFAULTS = {
    "REGION_FUEL_INDEX_CODE": "WEST",
    "CREDIT_LIMIT_CENTS": 5000000,
    "BILLING_DISPUTE_WINDOW_DAYS": 30,
    "HOURLY_WAGE_CENTS": 3000,
    "BUS_CAPACITY": 48,
    "BUS_MPG_X10": 80,
    "BUS_NEXT_INSPECTION_DUE": "2026-12-31",
    "ROUTE_SCHOOL_SITE": "Lincoln",
}
