"""Domain thresholds — numeric constants from the PRD's calculation narratives.

Sourced from PRD Sections 3.5-3.9 (the calculation prose). NON_EXISTENT_UUID
comes from the framework and is re-exported via the barrel __init__.
"""

# Cash discount fraction (PRD 3.8): ten percent (0.10).
CASH_DISCOUNT_PCT = 0.10

# Penalty calculation constants (PRD 3.7).
NO_SHOW_BASE_CENTS = 5000
LATE_CANCEL_BASE_CENTS = 2500
STRIKE_STEP = 0.5
STRIKE_CAP = 3

# Arrival grace allowance (PRD 3.5): ten minutes == 600 seconds, strict >.
GRACE_MINUTES = 10
GRACE_SECONDS = 600

# Pagination defaults (PRD 2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# Logical clock startup default (PRD 2.4).
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00Z"

# A syntactically-valid UUID that is never minted by the server.
BOGUS_UUID = "00000000-0000-4000-8000-000000000000"
