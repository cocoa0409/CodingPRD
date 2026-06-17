"""Domain thresholds and numeric constants drawn from the PRD's calculations.

NON_EXISTENT_UUID comes from the framework.
"""

# Class-year priority ranks (PRD §3.3): lower is a better priority.
CLASS_YEAR_RANK = {
    "SENIOR": 1,
    "JUNIOR": 2,
    "SOPHOMORE": 3,
    "FRESHMAN": 4,
}

# Bed capacity derived from room_type (PRD §3.1).
BED_CAPACITY = {
    "SINGLE": 1,
    "DOUBLE": 2,
    "TRIPLE": 3,
    "SUITE_DOUBLE": 2,
}

# Meal-plan weekly fee derived from tier (PRD §3.8).
TIER_FEE_CENTS = {
    "NONE": 0,
    "COMMUTER": 4000,
    "STANDARD": 9000,
    "UNLIMITED": 13500,
}

# Default per-night break charge when nightly_break_rate_cents is omitted (PRD §3.1).
DEFAULT_NIGHTLY_BREAK_RATE_CENTS = 4500

# Pagination bounds (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "MIN_OFFSET": 0,
}
