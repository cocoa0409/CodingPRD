"""Domain thresholds and shared constants from the PRD."""

# The eight size codes the bank recognizes (PRD per-size inventory ledger section).
SIZE_CODES = [
    "NEWBORN",
    "SIZE_1",
    "SIZE_2",
    "SIZE_3",
    "SIZE_4",
    "SIZE_5",
    "SIZE_6",
    "TRAINING_PANTS",
]

# Published fair-market valuation table for donated product (PRD intake section).
FAIR_MARKET_CENTS = {
    "NEWBORN": 35,
    "SIZE_1": 32,
    "SIZE_2": 30,
    "SIZE_3": 28,
    "SIZE_4": 26,
    "SIZE_5": 24,
    "SIZE_6": 22,
    "TRAINING_PANTS": 40,
}

# Household allotment: fifty units per child per month (PRD household section).
UNITS_PER_CHILD_PER_MONTH = 50

# Allocation formula constants (PRD monthly-allocation-run section).
BASE_FLOOR_UNITS = 100
CAPACITY_CAP_FRACTION = 0.5

# Forecast windows (PRD forecasting section).
TRAILING_WINDOW_DAYS = 28
DONATION_WINDOW_DAYS = 90
WEEKS_IN_WINDOW = 4

# The logical clock starts at exactly this instant (PRD logical-clock section).
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
CURRENT_PERIOD = "2026-08"
NEXT_PERIOD = "2026-09"
PAST_PERIOD = "2026-07"

# Default grant window used by fixtures (covers the default clock month).
GRANT_WINDOW_START = "2026-07-01T00:00:00Z"
GRANT_WINDOW_END = "2027-06-30T00:00:00Z"

# Default distribution-event window (after the default clock reading).
DEFAULT_EVENT_STARTS = "2026-08-10T09:00:00Z"
DEFAULT_EVENT_ENDS = "2026-08-10T12:00:00Z"

# Default volunteer shift window.
DEFAULT_SHIFT_STARTS = "2026-08-10T09:00:00Z"
DEFAULT_SHIFT_ENDS = "2026-08-10T11:00:00Z"
