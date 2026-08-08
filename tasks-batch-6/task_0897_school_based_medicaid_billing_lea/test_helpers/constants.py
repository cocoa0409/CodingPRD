"""Domain thresholds and defaults for the School-Based Medicaid Billing API."""

# Numeric thresholds stated in the PRD workflows.
THRESHOLDS = {
    "TIMELY_FILING_DAYS": 365,      # timely filing: <=365 days passes, 366 fails
    "MIN_RESPONDED_MOMENTS": 4,     # quarter close: >=4 responded moments required
}

# The server logical clock's startup default.
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Conventional test-defaults for an IEP authorization (unit_minutes=15, rate 3000c).
TEST_DEFAULTS = {
    "UNIT_MINUTES": 15,
    "UNIT_RATE_CENTS": 3000,
    "AUTHORIZED_MINUTES_PER_SESSION": 30,
    "SESSIONS_PER_WEEK": 2,
}
