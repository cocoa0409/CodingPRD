"""Domain thresholds and shared fixtures data from the PRD (sections 2.5, 3.x)."""

# PRD 3.1: cbc_required is true when group_revenue_eur is at least 750000000.
CBCR_THRESHOLD_EUR = 750_000_000

# PRD 3.4: match tolerance of 100 cents between the two booked amounts.
MATCH_TOLERANCE_CENTS = 100

# PRD 3.8: per-diem interest spread of 85 basis points per annum.
POOL_SPREAD_BP = 85

# PRD 3.2: comparables_bp must contain at least five entries.
MIN_COMPARABLES = 5

# PRD 2.5: the logical clock reads exactly 2026-08-01T00:00:00Z before being set.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# Shared study comparables used across the suite; nearest-rank quartiles of
# [300, 400, 500, 600, 700] with n=5 are ranks 2/3/4 -> 400 / 500 / 600.
STUDY_COMPARABLES_BP = [300, 400, 500, 600, 700]
STUDY_P25_BP = 400
STUDY_MEDIAN_BP = 500
STUDY_P75_BP = 600

DEFAULT_MARKUP_BP = 200
DEFAULT_EFFECTIVE_FROM = "2026-01-01"
DEFAULT_EFFECTIVE_TO = "2027-01-01"
DEFAULT_YEAR_INDEX = 2026
DEFAULT_GROUP_REVENUE_EUR = 100_000_000
