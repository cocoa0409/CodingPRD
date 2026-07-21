"""Domain thresholds — numeric constants from the PRD calculations (§3.1–§3.10)."""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401

# Tier thresholds (PRD §3.1): inclusive lower bounds on owned_points.
TIER_THRESHOLDS = {
    "SILVER_MIN": 4000,
    "GOLD_MIN": 7000,
    "PLATINUM_MIN": 13000,
}

# Booking window lengths in days (PRD §3.4).
STANDARD_WINDOW_DAYS = 366
PRIORITY_WINDOW_DAYS = 396

# Seasonal point chart selectors (PRD §3.4).
HIGH_SEASON_MONTHS = [6, 7, 8, 12]  # June, July, August, December
WEEKEND_WEEKDAYS = ["FRI", "SAT"]

# Cancellation refund ladder (PRD §3.5).
FULL_REFUND_DAYS = 60
PARTIAL_REFUND_DAYS = 15
PARTIAL_REFUND_RATIO = 0.5

# Banking / borrowing (PRD §3.2).
BANK_DEADLINE_DAYS = 273  # days after Jan 1 of the source use year
LATE_BANK_RATIO = 0.5
BANK_CAP_PCT = 0.5
BORROW_CAP_PCT = 0.5

# Guest certificate fee (PRD §3.6).
GUEST_CERT_FEE_POINTS = 50

# Statement fees (PRD §3.9 / §2.7).
MAINT_RATE_PER_POINT_USD = 0.0653
CLUB_DUES_RATE_PER_POINT_USD = 0.0089
STATEMENT_DUE_DAYS = 30
GRACE_DAYS = 15

# Logical clock (PRD §2.4).
CLOCK_DEFAULT_UTC = "2026-07-01T00:00:00Z"

# A reusable seasonal chart used across setups: low weekday/weekend, high weekday/weekend.
DEFAULT_CHART = {
    "points_weekday_low": 150,
    "points_weekend_low": 200,
    "points_weekday_high": 250,
    "points_weekend_high": 350,
}
