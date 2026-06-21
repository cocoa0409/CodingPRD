"""Domain thresholds — numeric constants from the PRD calculation narratives (§2.6, §3.5, §3.7)."""

# PRD §3.5: total-loss threshold is a repair-to-value ratio of 0.75 (inclusive boundary).
TOTAL_LOSS_THRESHOLD = 0.75

# PRD §3.7: on a total loss the day cap is lowered to the smaller of rental_max_days and five days.
TOTAL_LOSS_RENTAL_MAX_DAYS = 5

# PRD §2.3: pagination defaults.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Convenience: a syntactically valid UUID that no created entity will own.
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
