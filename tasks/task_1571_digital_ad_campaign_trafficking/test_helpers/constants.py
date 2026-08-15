"""Domain thresholds — numeric constants from PRD §2.5, §2.6, §3."""

# PRD §2.5: server logical clock startup default
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # PRD §3.1: governance threshold defaults
    "DEFAULT_VIEWABILITY_THRESHOLD_PCT": 0.70,
    "DEFAULT_IVT_THRESHOLD_PCT": 0.02,
    # PRD §3.4: pacing alert ratio and trailing window
    "PACING_ALERT_RATIO": 0.90,
    "TRAILING_WINDOW_DAYS": 3,
    # PRD §3.6: LOWER_OF tolerance gate
    "DISCREPANCY_TOLERANCE": 0.10,
    # PRD §3.2: default rolling frequency-cap window
    "DEFAULT_FREQUENCY_CAP_WINDOW_HOURS": 24,
}

TEST_DEFAULTS = {
    "IO_TOTAL_BUDGET_CENTS": 100000,
    "GOAL_IMPRESSIONS": 100000,
    "CPM_RATE_CENTS": 500,
    "FLIGHT_START": "2026-08-01",
    "FLIGHT_END": "2026-08-31",
    "AD_TAG": '<script src="https://ad.example.com/tag.js"></script>',
}
