"""Domain thresholds — numeric constants from the PRD's pricing and capacity rules."""

# Scholarship tier table (PRD §3.6): NONE -> 0, PARTIAL -> 0.5, FULL -> 1.0.
TIER_TABLE = {
    "NONE": 0.0,
    "PARTIAL": 0.5,
    "FULL": 1.0,
}

# CAMP programs add a flat materials surcharge per enrolled week (PRD §3.6).
CAMP_MATERIALS_SURCHARGE_CENTS = 1500

# Household sibling discount rate (PRD §3.6): ten percent.
SIBLING_PCT = 0.10

# Rain relocation overflow tolerance (PRD §3.5): alternate capacity may be exceeded by at most 1.
RAIN_OVERFLOW_TOLERANCE = 1

# Pagination defaults (PRD §2.3).
PAGINATION = {
    "default_limit": 10,
    "min_limit": 1,
    "max_limit": 100,
    "default_offset": 0,
}

# Common values reused across fixtures.
TEST_DEFAULTS = {
    "CAMP_BASE_CENTS": 20000,
    "AFTERSCHOOL_BASE_CENTS": 15000,
    "DEFAULT_AGE_AS_OF_DATE": "2026-06-01",
    "DEFAULT_BIRTH_DATE": "2016-03-01",  # age 10 as of 2026-06-01
    "DEFAULT_WEEK_START": "2026-06-08",
    "DEFAULT_HOME_ZIP": "94101",
}
