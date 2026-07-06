"""Domain thresholds — numeric constants from the PRD's money and rating rules."""

# Platform fee components (PRD §3.5): flat listing fee, transaction %, processing %,
# and processing flat surcharge, all in cents / fractions.
LISTING_FEE_CENTS = 20
TRANSACTION_FEE_PCT = 0.065
PAYMENT_PROCESSING_PCT = 0.03
PAYMENT_PROCESSING_FLAT_CENTS = 25

# Shop rating Bayesian prior (PRD §3.7).
PRIOR_COUNT = 5
PRIOR_MEAN = 4.0

# Logical clock startup default (PRD §2.10).
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
