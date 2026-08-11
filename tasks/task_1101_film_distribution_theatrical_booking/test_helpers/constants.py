"""Domain thresholds and shared constants (PRD §2.5, §2.8, §3)."""

# PRD §2.5: the global logical clock reads exactly this at server startup.
LOGICAL_CLOCK_START = "2026-05-01T00:00:00Z"

# PRD §3.2: theatrical_window_end = target_release_date + 90 days.
THEATRICAL_WINDOW_DAYS = 90

# PRD §3.8: automatic holdover threshold is min_weeks_committed * 100000 cents
# (one thousand dollars per committed week), inclusive boundary.
PER_SCREEN_WEEKLY_HOLD_THRESHOLD_CENTS = 100000

# PRD §3.9: running co-op cap is four times the market's weekly budget.
RUNNING_WEEKS_CAP = 4

# PRD §2.8 / §3.3: admissible rental percentages lie between 0.00 and 0.95.
MIN_RENTAL_PCT = 0.00
MAX_RENTAL_PCT = 0.95

THRESHOLDS = {
    "PER_SCREEN_WEEKLY_HOLD_THRESHOLD_CENTS": PER_SCREEN_WEEKLY_HOLD_THRESHOLD_CENTS,
    "RUNNING_WEEKS_CAP": RUNNING_WEEKS_CAP,
    "MIN_RENTAL_PCT": MIN_RENTAL_PCT,
    "MAX_RENTAL_PCT": MAX_RENTAL_PCT,
    "THEATRICAL_WINDOW_DAYS": THEATRICAL_WINDOW_DAYS,
}

TEST_DEFAULTS = {
    "HOUSE_ALLOWANCE_CENTS": 100,
    "GROSS_CENTS": 500000,
    "ADMISSIONS": 2000,
    "WEEKLY_COOP_BUDGET_CENTS": 100000,
}
