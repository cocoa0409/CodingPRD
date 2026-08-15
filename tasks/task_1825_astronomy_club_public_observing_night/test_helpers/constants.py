"""Domain thresholds — numeric constants from the PRD's calculations."""

# Logical clock default at process startup
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Dues proration
    "DAYS_FULL_YEAR": 365,
    # Overdue fee
    "GRACE_DAYS": 2,
    "DAILY_FEE_CENTS": 500,
    "FEE_CAP_CENTS": 10000,
    # Membership clock thresholds
    "GRACE_PERIOD_DAYS": 7,
    "LAPSE_PERIOD_DAYS": 37,
    "COLLIMATION_INTERVAL_DAYS": 180,
    "MOON_ILLUMINATION_LIMIT": 40,
    "WEATHER_CANCEL_THRESHOLD": 70,
    "GROUP_CAPACITY_PER_EVENT": 60,
    # Dark-sky reporting
    "MIN_READINGS_PER_REPORT": 3,
    "GRADE_A_MIN": 21.50,
    "GRADE_B_MIN": 20.50,
    "GRADE_C_MIN": 19.50,
    "GRADE_D_MIN": 18.50,
    # No-show strikes
    "STRIKE_WINDOW_DAYS": 365,
    "STRIKE_THROTTLE_LIMIT": 2,
    # SQM reading range
    "SQM_MIN": 10.00,
    "SQM_MAX": 22.99,
    # Group deposit tiers
    "DEPOSIT_TIER1_FREE_UP_TO": 10,
    "DEPOSIT_TIER2_RATE_CENTS": 1000,
    "DEPOSIT_TIER2_UP_TO": 30,
    "DEPOSIT_TIER3_RATE_CENTS": 2000,
}

# Solar-session fixed daylight table: [06:00Z, 20:00Z) of the same UTC date
SOLAR_DAYLIGHT_START_HHMM = "06:00"
SOLAR_DAYLIGHT_END_HHMM = "20:00"

TEST_DEFAULTS = {
    "TIER_DUES_INDIVIDUAL": 120000,
    "TIER_DUES_FAMILY": 180000,
    "TIER_DUES_STUDENT": 60000,
}
