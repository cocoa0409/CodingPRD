"""Domain thresholds and pinned literals taken from the PRD narrative."""

# The logical clock's startup instant (PRD 2.5).
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# Eligibility ladder (PRD 3.4).
THRESHOLDS = {
    "AGE_LIMIT_YEARS": 19,
    "TRANSFER_SITOUT_DAYS": 365,
    "ACADEMIC_MIN_GPA": 2.000,
    "MAX_APPEALS": 2,
    "MIN_BRACKET_SCHOOLS": 4,
    "PROBATION_FORFEITS": 2,
    "SUSPENSION_FORFEITS": 4,
    "MAX_CONTESTS_PER_WINDOW": 3,
    "CONTEST_WINDOW_DAYS": 7,
    "VENUE_TURNOVER_MINUTES": 60,
    "OFFICIAL_TRAVEL_BUFFER_MINUTES": 90,
    "PREGAME_BUFFER_MIN": 75,
    "POSTGAME_BUFFER_MIN": 30,
    "RTP_INITIAL_REST_HOURS": 48,
    "RTP_INTER_STAGE_HOURS": 24,
    "RTP_TOTAL_DURATION_HOURS": 144,
    "RTP_MAX_STAGE": 5,
    "MILEAGE_CAP_MILES": 120,
    "MILEAGE_CENTS_PER_MILE": 62,
    "NIGHT_SURCHARGE_CENTS": 1500,
    "NIGHT_START_HOUR_UTC": 23,
    "PLAYOFF_FLOOR_CENTS": 2500,
    "PLAYOFF_PERCENT_OF_BASE": 0.20,
    "POWER_RATING_RAW_WEIGHT": 0.65,
    "POWER_RATING_OPP_WEIGHT": 0.35,
}

# Participation-fee tier bases in cents (PRD 3.3).
FEE_TIER_BASE_CENTS = {
    "TIER_A": 12345,
    "TIER_B": 8975,
    "TIER_C": 6499,
}

# Multi-sport discount by number of counted prior cases (PRD 3.3).
MULTI_SPORT_DISCOUNT = {0: 0.00, 1: 0.25, 2: 0.40}

# Officiating stipend certification bases in cents (PRD 3.7).
STIPEND_BASE_CENTS = {
    "LEVEL_1": 4000,
    "LEVEL_2": 6000,
    "LEVEL_3": 8500,
}

# Season tier multiplier applied to the certification base (PRD 3.7).
STIPEND_TIER_MULTIPLIER = {
    "TIER_A": 1.25,
    "TIER_B": 1.00,
    "TIER_C": 0.85,
}

# School operating-parameter defaults (PRD 3.2).
SCHOOL_DEFAULTS = {
    "school_day_end_utc_hhmm": "20:30",
    "bus_fleet_size": 4,
    "max_release_minutes_per_request": 240,
    "fee_cap_cents": 20000,
    "venue_concurrent_capacity": 1,
}

# Pagination bounds (PRD 2.3).
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "MIN_OFFSET": 0}

# Fixed operator identifiers used by the opaque roles in tests.
ADMIN_USER_ID = "admin-001"
REVIEWER_USER_ID = "rev-001"
REVIEWER_ALT_USER_ID = "rev-002"
MEDICAL_USER_ID = "med-001"
MEDICAL_ALT_USER_ID = "med-002"
MEDICAL_THIRD_USER_ID = "med-003"
COORDINATOR_USER_ID = "coord-001"
