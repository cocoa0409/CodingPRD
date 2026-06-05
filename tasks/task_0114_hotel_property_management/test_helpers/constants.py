"""Domain thresholds — numeric constants from PRD calculations."""

# Nightly rate floor: the per-night figure is floored at 0 cents (PRD §3.4).
RATE_FLOOR_CENTS = 0

# Overbooking allowance bounds (PRD §3.1): 0.0 <= x <= 0.25.
OVERBOOKING_MIN = 0.0
OVERBOOKING_MAX = 0.25

# Pagination bounds (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
