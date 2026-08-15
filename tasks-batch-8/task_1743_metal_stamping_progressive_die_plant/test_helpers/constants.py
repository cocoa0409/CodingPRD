"""Domain thresholds and shared constants from the PRD."""

# Logical clock: before any advance call the server reads exactly this instant (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Changeover teardown allowance appended to planned_end (PRD §2.10).
TEARDOWN_BUFFER_MINUTES = 30

# Rolling SMED window: newest N completed changeovers, N = min(10, count) (PRD §3.6).
SMED_ROLLING_WINDOW_MAX = 10

# Index-adjusted piece price floor in cents (PRD §3.10).
PRICE_FLOOR_CENTS = 1

# Precision discipline (PRD §2.7).
WEIGHT_DECIMALS = 3
SCRAP_RATE_DECIMALS = 6
SMED_AVERAGE_DECIMALS = 2

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# Standard setup timestamps used across fixtures (same plant day).
CHANGEOVER_START = "2026-08-01T06:00:00Z"
CHANGEOVER_END = "2026-08-01T07:00:00Z"
RUN_WINDOW_START = "2026-08-01T08:00:00Z"
RUN_WINDOW_END = "2026-08-01T09:00:00Z"
ORDER_DUE_DATE = "2026-08-20T00:00:00Z"

# Segregation-of-duties operator ids (PRD §2.1, §3.5, §3.9): the creator of a
# PPAP submission or layered audit must differ from the user who dispositions it.
PE_CREATOR_USER_ID = "user-pe-creator"
QE_REVIEWER_USER_ID = "user-qe-reviewer"
QE_DISPOSITIONER_USER_ID = "user-qe-dispositioner"

# Common engineering defaults.
DEFAULT_MATERIAL_SPEC = "HSLA340"
DEFAULT_THICKNESS_MM = 1.2
DEFAULT_NET_WEIGHT_KG = 0.62
DEFAULT_GROSS_WEIGHT_PER_PART_KG = 0.85
DEFAULT_BASE_PIECE_PRICE_CENTS = 1800
DEFAULT_BASE_INDEX_VALUE = 900
DEFAULT_PASS_THROUGH_PCT = 0.5
