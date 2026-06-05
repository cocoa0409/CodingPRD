"""Domain thresholds — numeric constants from PRD wage-computation rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Daily / weekly overtime thresholds (PRD §3.1, §3.6).
THRESHOLDS = {
    "DAILY_OT_THRESHOLD_HOURS": 8,
    "DAILY_DT_THRESHOLD_HOURS": 12,
    "WEEKLY_OT_THRESHOLD_HOURS": 40,
    "SEVENTH_DAY_FIRST_TIER_HOURS": 8,
    "DETENTION_GRACE_MINUTES": 15,
}

# Premium multipliers (PRD §3.6).
OT_PREMIUM_MULTIPLIER = 0.5
DT_PREMIUM_MULTIPLIER = 1.0

# Wage / minimum-wage defaults (PRD §3.1, §3.7).
TEST_DEFAULTS = {
    "FEDERAL_MIN_WAGE_CENTS": 725,
    "FEDERAL_TIPPED_CASH_WAGE_CENTS": 213,
    "STATE_MIN_WAGE_CENTS": 725,
    "BASE_RATE_CENTS": 2000,
}

# A well-formed UUID that names no resource (for 404 tests where the design
# instance supplies its own literal, this is an alternate convenience value).
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
