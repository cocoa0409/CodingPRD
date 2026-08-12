"""Domain thresholds — numeric constants from the PRD (§3.5, §3.6, §3.7)."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401 (re-exported)

THRESHOLDS = {
    # penalty accrual (PRD §3.7 link 3)
    "BASE_DAILY_PENALTY_CENTS": 9999,
    "PENALTY_CAP_CENTS": 5000000,
    "TIER1_MEMBER_THRESHOLD": 10000,
    "TIER2_MEMBER_THRESHOLD": 50000,
    "REPEAT_STEP": 0.5,
    "REPEAT_CAP": 3,
    # rollup components (PRD §3.7 link 4)
    "PER_ERROR_PENALTY_CENTS": 25000,
    "LATE_CORRECTION_PENALTY_CENTS": 50000,
    # ghost network detection (PRD §3.5)
    "GHOST_STRIKE_THRESHOLD": 3,
    # directory correction SLA (PRD §3.6)
    "CORRECTION_SLA_HOURS": 72,
    # complaint filing window (PRD §3.6)
    "COMPLAINT_WINDOW_DAYS": 90,
}

TEST_DEFAULTS = {
    "CLOCK_START": "2026-05-01T00:00:00Z",
    "STANDARD_CARDIOLOGY_URBAN": {
        "specialty": "CARDIOLOGY",
        "geo_class": "URBAN",
        "max_members_per_provider": 1200,
        "max_travel_minutes": 30,
        "max_travel_miles": 15,
        "max_wait_days_routine": 15,
        "max_wait_days_urgent": 2,
    },
    "STANDARD_DERMATOLOGY_URBAN": {
        "specialty": "DERMATOLOGY",
        "geo_class": "URBAN",
        "max_members_per_provider": 15000,
        "max_travel_minutes": 45,
        "max_travel_miles": 30,
        "max_wait_days_routine": 20,
        "max_wait_days_urgent": 3,
    },
}
