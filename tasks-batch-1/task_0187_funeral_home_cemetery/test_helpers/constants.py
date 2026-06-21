"""Domain thresholds and test defaults — numeric constants from PRD §2.6, §3."""

# Projection rate applied to the trust principal corpus for PRENEED_TRUST
# contracts (PRD §3.4: "a projection rate of three percent").
PROJECTION_RATE = 0.03

# Pagination bounds (PRD §2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "MIN_OFFSET": 0,
}

# Default funeral-home configuration used across fixtures.
TEST_DEFAULTS = {
    "SALES_TAX_PCT": 0.08,
    "STATE_TRUST_PCT": 0.90,
    "CHAPEL_BUFFER_MINUTES": 30,   # PRD §3.1 default when omitted
    "TRUST_ADMIN_RETENTION_CENTS": 0,  # PRD §3.1 default when omitted
}
