"""Domain thresholds — numeric constants from the PRD premium/reserve/escrow rules."""

# Owner / lender tiered premium rates (dollars per $1,000 of coverage).
RATE1_PER_1000 = 5.00   # first $100,000
RATE2_PER_1000 = 4.00   # $100,000.01 .. $500,000
RATE3_PER_1000 = 3.00   # above $500,000
TIER1_CEIL_DOLLARS = 100_000
TIER2_CEIL_DOLLARS = 500_000

# Owner reissue factor applied to the un-rounded base before the single final rounding.
REISSUE_FACTOR = 0.60

# Flat co-issue lender premium in cents.
CO_ISSUE_FLAT_CENTS = 2500

# Claim reserve loading factor (defense/curative loading).
LOSS_LOADING_FACTOR = 1.15

# Logical clock startup default.
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
