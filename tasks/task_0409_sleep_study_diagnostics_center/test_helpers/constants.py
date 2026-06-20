"""Domain thresholds — numeric constants from PRD calculations."""

# AHI severity banding thresholds (events/hour, inclusive at the lower edge).
SEVERITY_BANDS = {
    "MILD_MIN": 5,      # ahi >= 5.0 -> MILD
    "MODERATE_MIN": 15,  # ahi >= 15.0 -> MODERATE
    "SEVERE_MIN": 30,    # ahi >= 30.0 -> SEVERE
}

# CMS-style CPAP adherence thresholds.
ADHERENCE = {
    "MIN_WINDOW_DAYS": 30,
    "MIN_NIGHTS": 21,
    "ADHERENCE_PCT": 0.70,
    "MIN_AVG_MINUTES": 240,
}

# Epworth Sleepiness Scale bounds.
EPWORTH_MIN = 0
EPWORTH_MAX = 24

# SleepBed default sanitation/turnover gap (minutes) after each booked night.
DEFAULT_TURNOVER_BUFFER_MINUTES = 60

# Pagination bounds.
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}
