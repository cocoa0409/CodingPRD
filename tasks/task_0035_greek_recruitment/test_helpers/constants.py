"""Domain thresholds and defaults (PRD §2.8, §3.1)."""

# Risk thresholds (PRD §2.8: "at least 15 -> SUSPENDED; at least 6 -> PROBATION")
PROBATION_THRESHOLD = 6
SUSPEND_THRESHOLD = 15

# Minimum GPA gate on PNM activation (PRD §3.1).
MIN_GPA = 2.50

# Pagination (PRD §2.3)
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# Useful test-default scenario constants
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
DEFAULT_BID_DAY_AT = "2026-09-15T12:00:00Z"
DEFAULT_PARTY_START = "2026-09-05T18:00:00Z"
DEFAULT_PARTY_DURATION_MINUTES = 60
DEFAULT_PARTY_CAPACITY = 10
