"""Domain thresholds and shared time constants (PRD §2.5, §3.3, §3.4, §3.9)."""

# Registry logical clock initial value (PRD §2.5)
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"
# A wall-clock time on day one that is inside default waking hours (08:00-21:00)
NOON_DAY1_ISO = "2026-05-01T12:00:00Z"

THRESHOLDS = {
    # Priority score (PRD §3.3)
    "OVERDUE_CAP_DAYS": 90,
    "ATTEMPT_DECAY_BASE": 20,
    "ATTEMPT_DECAY_PER_ATTEMPT": 4,
    "NO_SHOW_STRIKE_BONUS": 8,
    "REOPEN_BONUS": 12,
    "SCORE_MIN": 0,
    "SCORE_MAX": 100,
    "BAND_P1_MIN": 80,
    "BAND_P2_MIN": 60,
    "BAND_P3_MIN": 30,
    # Campaign defaults (PRD §3.4)
    "QUIET_HOURS_START_MIN": 1260,  # 21:00
    "QUIET_HOURS_END_MIN": 480,     # 08:00
    "MIN_ATTEMPT_INTERVAL_HOURS": 72,
    "MAX_ATTEMPTS_PER_MEMBER": 5,
    # Measure defaults (PRD §3.1)
    "EXCLUSION_WINDOW_DAYS": 90,
    "REPORTING_LAG_DAYS": 30,
    # Incentive payout (PRD §3.9)
    "WORKLOAD_TARGET": 250,
    "PER_GAP_BASE_CENTS": 4500,
    "QUALITY_BONUS_CENTS": 50000,
    "QUALITY_THRESHOLD_BPS": 7000,
    "TIER_LOW_BPS": 10000,
    "TIER_MID_BPS": 12000,
    "TIER_HIGH_BPS": 15000,
    # Appointment default capacity (PRD §3.5)
    "PROVIDER_CAPACITY_PER_SLOT": 1,
}

TEST_DEFAULTS = {
    "PROGRAM_YEAR": 2026,
    "LOOKBACK_DAYS": 365,
    "PANEL_MANAGER_ID": "pm_1",
    "REVIEWER_ID": "qr_1",
    "PERIOD_KEY": "2026-06",
    "MEMBER_DOB": "1960-01-01T00:00:00Z",
    "EVIDENCE_SERVICE_DATE": "2026-04-15T00:00:00Z",
    "CAMPAIGN_START": "2026-05-01T00:00:00Z",
    "CAMPAIGN_END": "2026-12-31T23:59:59Z",
}
