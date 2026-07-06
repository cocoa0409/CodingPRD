"""Domain thresholds and shared test defaults from the PRD's calculations.

Generic NON_EXISTENT_UUID comes from the framework, not from here.
"""

# Time-entry billable rounding grid (PRD §3.5): raw minutes round up onto a
# 15-minute (0.25 h) grid.
GRID_MINUTES = 15
QUARTER_HOUR = 0.25

# VA match-score weights (PRD §3.3).
MATCH_WEIGHTS = {
    "W_SKILL": 0.5,
    "W_RATING": 0.3,
    "W_CAPACITY": 0.2,
}
RATING_DENOMINATOR = 5.0
CAPACITY_DENOMINATOR = 40.0

# The platform's logical clock startup default (PRD §2.5).
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# Shared defaults used by factories / fixtures.
TEST_DEFAULTS = {
    "MONTHLY_RETAINER_HOURS": 10,
    "BASE_RATE_CENTS": 5000,
    "OVERAGE_RATE_CENTS": 8000,
    "ROLLOVER_CAP_HOURS": 0,
    "WEEKLY_CAPACITY_HOURS": 40,
    "RATING": 4.0,
    "RESPONSE_MINUTES": 60,
    "RESOLUTION_HOURS": 24,
    "BREACH_PENALTY_PCT": 0.0,
}
