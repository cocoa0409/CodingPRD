"""Domain thresholds — numeric constants from the PRD's calculations.

Sourced from PRD §3.2 (abuse floor, annualization/projection factors),
§3.5 (room cleanup buffer), and §3.7 (plan duration bounds).
"""

THRESHOLDS = {
    # §3.2: abuse floor of fifteen thousand dollars, i.e. 1,500,000 cents.
    "ABUSE_FLOOR_CENTS": 1_500_000,
    # §3.2: annualized income is current monthly income multiplied by twelve.
    "ANNUALIZE_MONTHS": 12,
    # §3.2/§3.7: sixty-month commitment horizon / projection window.
    "PROJECTION_MONTHS": 60,
    # §3.5: thirty-minute cleanup buffer on each side of a room's interval.
    "ROOM_BUFFER_MINUTES": 30,
    # §3.7: commitment period must be at least thirty-six and at most sixty months.
    "PLAN_DURATION_MIN_MONTHS": 36,
    "PLAN_DURATION_MAX_MONTHS": 60,
}

# Common test input values reused across fixtures.
TEST_DEFAULTS = {
    "MEDIAN_ANNUAL_INCOME_CENTS": 6_000_000,
    "STATE_CODE": "CA",
    "HOUSEHOLD_SIZE": 1,
}
