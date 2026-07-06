"""Domain thresholds — numeric constants from PRD calculations and temporal rules."""

# SMS segmentation (PRD §3.3 / §3.5)
SMS_SEGMENT_SIZE = 160

# Retry loop (PRD §3.6)
RETRY_BASE_DELAY_SEC = 60
RETRY_MAX_BACKOFF_SEC = 3600
RETRY_MAX_ATTEMPTS = 3

# Severity factor used by the retry back-off formula (PRD §3.6)
SEVERITY_FACTORS = {"INFO": 1, "ADVISORY": 1, "WARNING": 2, "CRITICAL": 4}

# Throttle windows (PRD §2.10)
THROTTLE_WINDOW_MINUTES = 60

# Geospatial matching (PRD §2.7)
DEG_TO_M = 111320

# Drill scheduling buffer (PRD §3.8)
DRILL_BUFFER_MINUTES = 30

# Logical clock default (PRD §2.5)
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

# A clock value inside the default alert effective window used across setups.
DEFAULT_TEST_CLOCK = "2026-03-10T14:00:00Z"
DEFAULT_EFFECTIVE_FROM = "2026-03-10T00:00:00Z"
DEFAULT_EFFECTIVE_UNTIL = "2026-03-11T00:00:00Z"
