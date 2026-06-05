"""Domain thresholds — numeric constants from PRD calculations and bands."""

# Retainage default and its permitted band (PRD §3.1).
DEFAULT_RETAINAGE_PCT = 0.10
RETAINAGE_PCT_MIN = 0.0
RETAINAGE_PCT_MAX = 0.20

# Inspection-window buffer default in minutes (PRD §3.7).
DEFAULT_BUFFER_MINUTES = 30

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
