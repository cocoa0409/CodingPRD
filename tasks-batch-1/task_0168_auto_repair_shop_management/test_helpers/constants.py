"""Domain thresholds — numeric constants from PRD calculations (§3.8, §3.9)."""

# PRD §3.8: warranty period of 90 days (inclusive) and 4,000 miles (inclusive).
WARRANTY_DAYS = 90
WARRANTY_MILES = 4000

# PRD §3.9: ten-minute cleanup buffer after a technician's last clock-out.
CLEANUP_BUFFER_MINUTES = 10

# PRD §2.3: pagination defaults.
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
