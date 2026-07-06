"""Domain thresholds — numeric constants from the PRD calculations and windows."""

# Fee tier floors (cents); each floor is inclusive of its lower bound.
TIER_2_FLOOR_CENTS = 1_000_000
TIER_3_FLOOR_CENTS = 7_500_000
TIER_4_FLOOR_CENTS = 50_000_000

# Base administrative amount looked up by tier (cents).
BASE_FEE_BY_TIER = {
    "TIER_1": 75_000,
    "TIER_2": 175_000,
    "TIER_3": 400_000,
    "TIER_4": 700_000,
}

# Multipliers.
MEDIATION_CASE_TYPE_MULT = 0.5
ARBITRATION_CASE_TYPE_MULT = 1.0
PANEL_3_MULT = 1.5
PANEL_1_MULT = 1.0

# Temporal windows.
HEARING_NOTICE_DAYS = 7
APPEAL_WINDOW_DAYS = 30
NEUTRAL_BUFFER_MINUTES = 30

# Field defaults.
DEFAULT_PANEL_SIZE = 1
DEFAULT_STRIKES_PER_PARTY = 2

# Logical clock startup default.
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Pagination bounds.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
