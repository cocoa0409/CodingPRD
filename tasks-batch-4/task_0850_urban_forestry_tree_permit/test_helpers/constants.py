"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# Protected classification & replacement-count tiers (dbh in inches; inclusive lower bounds).
DBH_TIER_1 = 8.0    # < 8.0 -> 0 replacements; also the inclusive is_protected boundary
DBH_TIER_2 = 18.0   # [8.0, 18.0) -> 1 replacement
DBH_TIER_3 = 30.0   # [18.0, 30.0) -> 2 replacements; >= 30.0 -> 3 replacements

# Mitigation fee constants.
REPLACEMENT_SITE_FACTOR = 1.075
BASAL_AREA_FACTOR = 0.5454
CONDITION_FACTOR = {
    "GOOD": 1.0,
    "FAIR": 0.75,
    "POOR": 0.5,
    "DEAD": 0.25,
}

# Risk-rating scoring constants.
TARGET_BONUS = 3
SCORE_CAP = 16
BAND_MODERATE_MIN = 4
BAND_HIGH_MIN = 8
BAND_SEVERE_MIN = 12

# Pagination defaults.
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# The server's startup logical-clock default (PRD §2.8).
DEFAULT_CLOCK_ISO = "2026-03-01T00:00:00Z"
