"""Domain thresholds and default logical-clock anchors for the Board Governance API."""

# The logical governance clock starts here before any call to the clock endpoint.
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

# Seconds per day used by notice deadline and consent window arithmetic.
SECONDS_PER_DAY = 86400

# Default scheduled start used by fixture-built meetings (always strictly after
# the default logical clock so creation succeeds without advancing time).
DEFAULT_MEETING_START = "2026-06-20T10:00:00Z"

# Common director terms used across fixtures.
DEFAULT_TERM_START = "2026-01-01T00:00:00Z"
DEFAULT_TERM_END = "2029-01-01T00:00:00Z"
