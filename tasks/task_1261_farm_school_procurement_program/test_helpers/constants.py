"""Domain thresholds and shared constants from the PRD business rules."""

# Insurance minimums (PRD section 3.2): a farm of at most 500 acres is small.
SMALL_FARM_MAX_ACRES = 500
SMALL_FARM_MIN_COVERAGE_CENTS = 500000
LARGE_FARM_MIN_COVERAGE_CENTS = 1000000

# Geographic preference scoring (PRD section 3.3).
TIER1_MILES = 25
TIER2_MILES = 50
TIER3_MILES = 100

# Local-purchase incentive tiers (PRD section 3.6), in cents.
INCENTIVE_TIER1_CAP_CENTS = 1000000
INCENTIVE_TIER2_CAP_CENTS = 5000000

# Grant match (PRD section 3.7): fifty cents per grant dollar, per line.
MATCH_RATE = 0.5

# Substitution cap (PRD section 3.8): twenty percent of product planned total.
SUBSTITUTION_CAP_RATE = 0.20

# Logical clock startup value (PRD section 2.8).
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

# Standard program-year shape shared by the test recipes: year starts
# 2026-07-01, week 6 covers 2026-08-10 (a Monday), radius 100 miles.
DEFAULT_YEAR_START = "2026-07-01"
DEFAULT_YEAR_END = "2027-06-24"
DEFAULT_RADIUS_MILES = 100
DEFAULT_GRANT_AWARD_CENTS = 1000000
DEFAULT_LOCAL_SPEND_TARGET_PCT = 30
DEFAULT_PERIOD_MONTH = "2026-08"

# Monday delivery dates inside a weeks-5..10 agreement window for the
# standard year starting 2026-07-01.
MONDAY_WEEK6 = "2026-08-10"
MONDAY_WEEK7 = "2026-08-17"
MONDAY_WEEK8 = "2026-08-24"
