"""Domain thresholds — numeric constants from the PRD calculations.

NON_EXISTENT_UUID comes from the framework.
"""

# Collections grace period in days (PRD §3.7): "the collections grace period of
# fifteen days".
COLLECTIONS_GRACE_DAYS = 15

# Billing increment in minutes (PRD §3.4): "six-minute increments".
INCREMENT_MINUTES = 6

# Logical clock default before any /_clock call (PRD §3.10).
CLOCK_DEFAULT_UTC = "2026-01-01T00:00:00Z"

# Standard test values reused across fixtures.
TEST_DEFAULTS = {
    "STANDARD_RATE_CENTS": 50000,
    "MATTER_RATE_CENTS": 50000,
    "ISSUE_DATE": "2026-06-01T00:00:00Z",
    "NET_TERMS_DAYS": 30,
    # issue 2026-06-01 + 30 days -> due 2026-07-01T00:00:00Z
    "DUE_DATE": "2026-07-01T00:00:00Z",
}
