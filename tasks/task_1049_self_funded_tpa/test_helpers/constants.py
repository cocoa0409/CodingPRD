"""Domain thresholds — numeric constants from the PRD."""

# The 1099 reporting threshold: 60,000 cents == 600.00 USD, reportable at >=.
REPORTABLE_THRESHOLD_CENTS = 60000

# Pagination defaults (PRD Section 2.3).
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "default_offset": 0}

# Server-startup logical clock default (PRD Section 2.8).
CLOCK_DEFAULT = "2026-07-01T00:00:00Z"
