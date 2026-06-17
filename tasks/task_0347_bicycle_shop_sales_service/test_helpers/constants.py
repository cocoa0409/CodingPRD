"""Domain thresholds — numeric constants from the PRD calculations (PRD §3).

Only constants that the PRD prose states verbatim are captured here.
"""

# Layaway restocking-fee settlement (PRD §3.7).
FORFEIT_PCT_BPS = 1500          # fifteen percent of price_cents
FORFEIT_FLOOR_CENTS = 2000      # flat floor of 2000 cents

# Trade-in grade haircut (PRD §3.11).
GRADE_A_BPS = 8500
GRADE_B_BPS = 7000
GRADE_C_BPS = 5000
HANDLING_DEDUCTION_CENTS = 1500  # flat handling deduction

# Build assembly fee, marginally tiered (PRD §3.9).
BUILD_BASE_FEE_CENTS = 5000
BUILD_TIER1_PER_PART_CENTS = 1200   # parts 1..5
BUILD_TIER2_PER_PART_CENTS = 900    # parts 6..10
BUILD_TIER3_PER_PART_CENTS = 600    # parts 11+

# Special-order deposit (PRD §3.8).
DEPOSIT_PCT_BPS = 3000          # thirty percent of line value
DEPOSIT_MIN_CENTS = 5000        # flat minimum

# Tune-up rush surcharge default (PRD §3.2).
DEFAULT_RUSH_MULTIPLIER_BPS = 5000   # +50%

# Pagination bounds (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
