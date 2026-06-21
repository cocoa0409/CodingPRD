"""Domain thresholds and numeric constants from PRD calculations."""

# Pinned tuition constant (PRD 3.3): four sessions per month.
SESSIONS_PER_MONTH = 4

# Practice-score decay base (PRD 3.7): 0.95 per whole day.
DECAY_BASE = 0.95

# Milliseconds in one day, used for the day-age floor in weighted_progress_score.
MS_PER_DAY = 86_400_000

# Studio policy defaults (PRD 2.5).
DEFAULT_MAKEUP_CREDIT_CAP = 3
DEFAULT_CANCELLATION_NOTICE_HOURS = 24
DEFAULT_MAKEUP_CREDIT_VALID_DAYS = 30
DEFAULT_TURNOVER_BUFFER_MIN = 10

# Default family discount tiers (PRD 2.5 / 3.4).
DEFAULT_FAMILY_DISCOUNT_TIERS = [
    {"min_active_enrollments": 1, "discount_pct": 0},
    {"min_active_enrollments": 2, "discount_pct": 0.05},
    {"min_active_enrollments": 3, "discount_pct": 0.10},
    {"min_active_enrollments": 4, "discount_pct": 0.15},
]

# The deterministic clock value a freshly-created studio starts at (PRD 2.4).
STUDIO_DEFAULT_CLOCK = "2026-01-01T00:00:00.000Z"

TEST_DEFAULTS = {
    "HOURLY_RATE_CENTS": 6000,
    "DURATION_MIN": 60,
}
