"""Domain thresholds — numeric constants from PRD calculation rules."""

# Logical clock default (PRD §2.9: the value before any explicit set).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Royalty rates in basis points (PRD §3.7: 6%/9% before recoupment, 8%/11% after).
PRE_RECOUP_TIER1_BPS = 600
PRE_RECOUP_TIER2_BPS = 900
POST_RECOUP_TIER1_BPS = 800
POST_RECOUP_TIER2_BPS = 1100

# Performance protective caps (PRD §3.4).
WEEKLY_SHOW_CAP = 8          # 8th allowed, 9th rejected
DAILY_SHOW_CAP = 2           # 3rd same-date show rejected
CURTAIN_GAP_MINUTES = 120    # later curtain >= earlier curtain + duration + 120

# Crew pay tiers (PRD §3.5).
STRAIGHT_TIME_HOURS = 8      # exactly 8h pays no overtime
OVERTIME_1_5_CAP_HOURS = 4   # hours beyond 8, up to 4 more, at 1.5x
DOUBLE_TIME_START_HOURS = 12 # at exactly 12h the double-time component is zero
CREW_CANCEL_WINDOW_HOURS = 24  # < 24h before start accrues penalty; == 24h pays 0
CREW_CANCEL_PENALTY_HOURS = 4  # four hours at the line rate per planned line

# Stop cancellation penalty tiers in whole days out (PRD §3.8).
CANCEL_TIER1_MAX_DAYS_OUT = 30   # <= 30 days: 50% of guarantee
CANCEL_TIER2_MAX_DAYS_OUT = 60   # 31..60 inclusive: 25%; day 61 pays nothing

# Per-diem ranges (PRD §3.6).
PER_DIEM_MIN_DAYS = 1
PER_DIEM_MAX_DAYS = 7
PER_DIEM_MAX_TRAVEL_DAYS = 2

TEST_DEFAULTS = {
    "TOUR_NAME": "Tour A",
    "BUDGET_TOTAL_CENTS": 50_000_000,
    "CAPITALIZATION_CENTS": 10_000_000,
    "PER_DIEM_DAILY_CENTS": 20_000,
    "ROYALTY_TIER_THRESHOLD_CENTS": 1_000_000,
    "VENUE_NAME": "Venue V",
    "VENUE_CITY": "Chicago",
    "STAGE_WIDTH_FT": 44,
    "FLY_CAPACITY_LINES": 30,
    "POWER_AMPS": 400,
    "CREW_AVAILABLE": 20,
    "GUARANTEE_CENTS": 4_000_000,
    "SPLIT_PCT": 70,
    "PLAY_WEEK_START": "2026-09-07",
    "PLAY_WEEK_END": "2026-09-13",
    "LOAD_IN_DATE": "2026-09-05",
    "TRAVEL_IN_DAYS": 1,
    "PERF_DATE": "2026-09-08",
    "CURTAIN_TIME": "19:30",
    "DURATION_MINUTES": 150,
    "WEEKLY_SALARY_CENTS": 800_000,
    "CREW_RATE_CENTS_PER_HOUR": 2000,
}
