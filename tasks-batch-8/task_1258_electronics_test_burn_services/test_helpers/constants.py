"""Domain thresholds — numeric constants named in PRD §2 and §3."""

# Logical clock (PRD §2.5)
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
CLOCK_BASE = "2026-06-01T00:00:00Z"

# Burn-in profile computation (PRD §3.3)
AMBIENT_C = 25

# Disposition suggestion thresholds (PRD §3.6)
SHIP_FPY_THRESHOLD = 0.75
RETEST_RATE_MAX = 0.25
SCRAP_FPY_THRESHOLD = 0.50
ESCAPE_SCRAP_THRESHOLD = 1

# Reservation discipline (PRD §2.9)
PROFILE_PURGE_BUFFER_MINUTES = 30

# Retest authorization validity (PRD §3.5)
AUTHORIZATION_TTL_HOURS = 48

# Ratio serialization (PRD §2.7)
RATIO_DECIMAL_PLACES = 4

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100

TEST_DEFAULTS = {
    "PART_NUMBER": "PN-1000",
    "MAX_RETESTS_PER_UNIT": 2,
    "QUANTITY": 1,
}
