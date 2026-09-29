"""Numeric constants and shared test literals drawn from the PRD.

Every value here is stated in the PRD; nothing is invented.
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------

CLOCK_BASE_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Registration thresholds (PRD §3.2)
# ---------------------------------------------------------------------------

THRESHOLD_HEAD_CATTLE = 125_000
THRESHOLD_HEAD_SWINE = 100_000
THRESHOLD_HEAD_LAMB = 35_000

THRESHOLD_HEAD_BY_SPECIES = {
    "CATTLE": THRESHOLD_HEAD_CATTLE,
    "SWINE": THRESHOLD_HEAD_SWINE,
    "LAMB": THRESHOLD_HEAD_LAMB,
}

FIVE_YEAR_AVERAGE_DIVISOR = 5
APPEAL_CEILING = 2

# ---------------------------------------------------------------------------
# Wholesale authorization (PRD §3.1)
# ---------------------------------------------------------------------------

BOXED_BEEF_WHOLESALE_FLOOR_LBS = 2_000_000

# ---------------------------------------------------------------------------
# Confidentiality guideline defaults (PRD §3.3)
# ---------------------------------------------------------------------------

DEFAULT_MIN_REPORTER_COUNT = 3
DEFAULT_MAX_SINGLE_REPORTER_SHARE_PCT = 70.00
DEFAULT_MIN_REPORTED_HEAD = 2000

# ---------------------------------------------------------------------------
# Lateness and correction loop (PRD §3.5)
# ---------------------------------------------------------------------------

MINUTES_PER_DAY = 1440
RESUBMISSION_CEILING = 2

# ---------------------------------------------------------------------------
# Audit materiality (PRD §3.7)
# ---------------------------------------------------------------------------

DEFAULT_MATERIALITY_PCT = 2.00

# ---------------------------------------------------------------------------
# Penalty arithmetic (PRD §3.8)
# ---------------------------------------------------------------------------

BASE_CENTS_LATE_FILING = 250_000
BASE_CENTS_INACCURATE_DATA = 500_000
BASE_CENTS_NON_REGISTRATION = 1_000_000

BASE_CENTS_BY_VIOLATION = {
    "LATE_FILING": BASE_CENTS_LATE_FILING,
    "INACCURATE_DATA": BASE_CENTS_INACCURATE_DATA,
    "NON_REGISTRATION": BASE_CENTS_NON_REGISTRATION,
}

DAY_TIER_MULTIPLIER_LOW = 1.00     # days 1-2, or no lateness
DAY_TIER_MULTIPLIER_MID = 1.50     # days 3-7
DAY_TIER_MULTIPLIER_HIGH = 2.25    # days 8 and beyond

REPEAT_MULTIPLIERS = [1.00, 1.50, 2.00, 3.00]

VOLUME_FACTOR_HEAD_DIVISOR = 1_000_000
VOLUME_FACTOR_MAX_UPLIFT = 0.500
VOLUME_FACTOR_NEUTRAL = 1.000

SUSPENSION_SURCHARGE_SUSPENDED = 1.25
SUSPENSION_SURCHARGE_NEUTRAL = 1.00

PER_ASSESSMENT_CAP_CENTS = 2_000_000

POINTS_LATE_FILING = 2
POINTS_INACCURATE_DATA = 5
POINTS_NON_REGISTRATION = 8

POINTS_BY_VIOLATION = {
    "LATE_FILING": POINTS_LATE_FILING,
    "INACCURATE_DATA": POINTS_INACCURATE_DATA,
    "NON_REGISTRATION": POINTS_NON_REGISTRATION,
}

TIER_1_FLOOR_POINTS = 10
TIER_2_FLOOR_POINTS = 20
TIER_2_POINT_DOUBLING = 2

# ---------------------------------------------------------------------------
# Methodology docket notice minimums (PRD §3.9)
# ---------------------------------------------------------------------------

MIN_COMMENT_PERIOD_DAYS = 30
MIN_EFFECTIVE_NOTICE_DAYS = 30

# ---------------------------------------------------------------------------
# Shared test literals: the standard CATTLE weekly window
# ---------------------------------------------------------------------------

WINDOW_PERIOD_START = "2026-08-03T00:00:00Z"
WINDOW_PERIOD_END = "2026-08-10T00:00:00Z"
WINDOW_SUBMISSION_DEADLINE = "2026-08-11T15:00:00Z"
WINDOW_CORRECTION_DEADLINE = "2026-08-18T15:00:00Z"
WINDOW_PUBLICATION_RELEASE = "2026-08-19T12:00:00Z"

# One minute after the submission deadline, and one day-and-one-minute after,
# used by the lateness boundary tests.
DEADLINE_PLUS_ONE_MINUTE = "2026-08-11T15:01:00Z"
DEADLINE_PLUS_ONE_DAY = "2026-08-12T15:00:00Z"
DEADLINE_PLUS_ONE_DAY_ONE_MINUTE = "2026-08-12T15:01:00Z"
CORRECTION_DEADLINE_PLUS_ONE_SECOND = "2026-08-18T15:00:01Z"

# ---------------------------------------------------------------------------
# Shared test literals: slaughter histories
# ---------------------------------------------------------------------------

# Pools to 630,000 head; five-year average 126,000 -> above the CATTLE floor.
# 126,000 measured head also yields volume_factor 1.126.
HISTORY_ABOVE_CATTLE_FLOOR = {
    "2021": 120000,
    "2022": 124000,
    "2023": 126000,
    "2024": 128000,
    "2025": 132000,
}

# Pools to 610,000 head; five-year average 122,000 -> below the CATTLE floor,
# while the 2025 actual of 150,000 is above it.
HISTORY_BELOW_CATTLE_FLOOR = {
    "2021": 100000,
    "2022": 110000,
    "2023": 120000,
    "2024": 130000,
    "2025": 150000,
}
