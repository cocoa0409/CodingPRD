"""Domain thresholds — numeric constants from PRD formulas."""

# K-12 annual qualified-tuition cap, in cents ($10,000).
K12_ANNUAL_CAP_CENTS = 1_000_000

# Federal excess-withdrawal penalty rate.
FEDERAL_PENALTY_RATE = 0.10

# California state-tax-incentive: tier-cap-then-rate.
CA_CAP_CENTS = 600_000  # $6,000
CA_RATE = 0.10  # 10%

# New York state-tax-incentive: tiered marginal.
NY_TIER1_CENTS = 500_000  # $5,000 first-tier ceiling
NY_TIER1_RATE = 0.05  # 5%
NY_TIER2_CENTS = 1_000_000  # $10,000 absolute upper bound
NY_TIER2_RATE = 0.02  # 2%

# Contribution reverse window (72 hours).
REVERSE_WINDOW_HOURS = 72

# Withdrawal revision cycle limit.
MAX_REVISION_COUNT = 3

# Max scheduled contribution amount per period (cents).
MAX_SCHEDULED_AMOUNT_CENTS = 5_000_000

# Supported donor state codes.
SUPPORTED_STATE_CODES = {"CA", "NY", "IL", "TX", "FL", "OH"}

# Pagination defaults.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
