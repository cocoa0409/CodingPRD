"""Domain thresholds — numeric constants from the PRD (§2.6, §2.7, §3)."""

# Logical clock startup instant (PRD §2.5).
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Hours-of-service ceilings and windows (PRD §2.6).
    "MAX_DUTY_MINUTES_PER_TOUR": 720,
    "MAX_DUTY_MINUTES_PER_MONTH": 16560,
    "MIN_UNDISTURBED_REST_MINUTES": 600,
    "EARLY_REPORT_WINDOW_MINUTES": 60,
    "CALL_RESPONSE_WINDOW_MINUTES": 120,
    "FATIGUE_BLOCK_THRESHOLD": 80.0,
    "LEAVE_QUOTA_PER_CRAFT_DAY": 1,
    # Projected tour lengths by job_symbol suffix (PRD §2.6).
    "LONG_TOUR_PROJECTED_MINUTES": 700,
    "SHORT_TOUR_PROJECTED_MINUTES": 100,
    "DEFAULT_PROJECTED_TOUR_MINUTES": 480,
}

PAY = {
    # Agreement pay constants (PRD §3.6).
    "BASIC_DAY_CENTS": 30010,
    "OT_MULTIPLIER": 1.5,
    "OVERTIME_THRESHOLD_MINUTES": 480,
    "DEADHEAD_HOURLY_CENTS": 18755,
    "TRAIN_DEADHEAD_MULTIPLIER": 1.075,
}
