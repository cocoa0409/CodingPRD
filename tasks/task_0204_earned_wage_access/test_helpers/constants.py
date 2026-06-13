"""Domain thresholds and shared test literals from the Earned Wage Access PRD."""

# Deterministic test-clock base instant.
CLOCK_BASE = "2026-06-01T00:00:00Z"

# Employer defaults (PRD §3.1).
EMPLOYER_DEFAULTS = {
    "funding_balance_cents": 100000,
    "max_advance_pct_of_available": 0.50,
    "per_period_advance_cap_count": 3,
    "cooling_off_hours": 24,
}

# STANDARD advance-limit policy used across fixtures.
STANDARD_POLICY = {
    "tier": "STANDARD",
    "min_tenure_days": 90,
    "per_advance_floor_cents": 1000,
    "per_advance_ceiling_cents": 50000,
    "cumulative_period_ceiling_cents": 80000,
}

# Fee schedule used across fixtures.
FEE_SCHEDULE = {
    "expedite_flat_fee_cents": 199,
    "expedite_pct_fee": 0.02,
    "max_total_fee_cents": 1500,
    "tip_allowed": True,
}

# Default pay period interval (one week starting at the clock base).
PERIOD_START = "2026-06-01T00:00:00Z"
PERIOD_END = "2026-06-08T00:00:00Z"

# Worker hire date => tenure 365d at the clock base => STANDARD tier.
WORKER_HIRE_DATE = "2025-06-01T00:00:00Z"
WORKER_HOURLY_RATE_CENTS = 2000

# Rest buffer between shifts (PRD §3.3): thirty minutes.
MIN_REST_GAP_MINUTES = 30

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
