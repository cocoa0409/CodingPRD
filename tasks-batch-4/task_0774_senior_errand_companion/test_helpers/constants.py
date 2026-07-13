"""Domain thresholds and defaults — numeric constants from PRD calculations
and billing configuration.
"""

# Time conversion used throughout labor pricing.
MINUTES_PER_HOUR = 60

# Server-side defaults for optional client billing parameters (PRD §3.1/§3.5).
DEFAULT_OT_THRESHOLD_HOURS = 8
DEFAULT_OT_MULTIPLIER = 1.5
DEFAULT_MIN_VISIT_MINUTES = 60
DEFAULT_TIMEZONE = "UTC"

# Logical clock startup default (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"

# Convenience far-future instants used to keep credentials in force.
FAR_FUTURE = "2027-01-01T00:00:00Z"
BOND_EFFECTIVE_DEFAULT = "2026-01-01T00:00:00Z"
BOND_EXPIRY_DEFAULT = "2027-01-01T00:00:00Z"

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
