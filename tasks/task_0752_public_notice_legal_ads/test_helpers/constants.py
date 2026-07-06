"""Domain thresholds — numeric constants from the PRD's pricing and billing rules."""

# PRD §3.6: the affidavit fee is waived when subtotal_cents >= 3,000 cents.
AFFIDAVIT_WAIVER_THRESHOLD_CENTS = 3000

# PRD §3.4: consecutive-weekly run spacing — insertions are 7 days apart.
WEEK_DAYS = 7

# The server's logical clock startup default (PRD §2.7).
CLOCK_START_DEFAULT = "2026-03-01T00:00:00Z"

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
