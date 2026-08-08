"""Domain thresholds and rates — numeric constants from the PRD workflows.

Generic ``NON_EXISTENT_UUID`` comes from the framework.
"""

# Resident standing / delinquency (PRD Section 3.1)
DELINQUENCY_THRESHOLD_CENTS = 25000

# Violation fine assessment (PRD Section 3.7)
REPEAT_WINDOW_DAYS = 180
DELINQUENT_SURCHARGE_CENTS = 5000
FINE_CAP_CENTS = 50000
TIER_MULTIPLIERS = {0: 1.0, 1: 1.5, 2: 2.0}  # repeat_index >= 3 -> 3.0
TIER_MULTIPLIER_MAX = 3.0

# Late fee on statement (PRD Section 3.8)
LATE_FEE_PCT = 0.015

# Pass fee rates (PRD Sections 3.3, 3.4)
GUEST_HOURLY_CENTS = 0
VENDOR_HOURLY_CENTS = 500
OVERSTAY_SURCHARGE_CENTS_PER_HOUR = 2000

# Amenity settlement (PRD Section 3.5)
OVERAGE_MULTIPLIER = 2

# Patrol scheduling buffer (PRD Section 3.6)
PATROL_BUFFER_MINUTES = 60

# Logical clock startup default (PRD Section 2.4)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Pagination (PRD Section 2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# A well-formed UUID that resolves to no resource.
NON_EXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
