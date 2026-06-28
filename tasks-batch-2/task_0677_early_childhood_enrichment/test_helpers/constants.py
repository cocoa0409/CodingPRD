"""Domain thresholds — numeric constants from the PRD calculations and clock.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Monthly base fee in cents resolved from membership tier at activation (PRD §2.9).
MEMBERSHIP_BASE_FEE_CENTS = {
    "CORE": 3000,
    "PLUS": 5000,
    "UNLIMITED": 9000,
}

# Fixed billing cycle length in days for proration (PRD §3.6).
CYCLE_DAYS = 30

# Makeup credit time-to-live in days; expires_at = issuance + this (PRD §2.9).
CREDIT_TTL_DAYS = 60

# Sibling-discount tiered rates by billable child count (PRD §3.6).
SIBLING_RATE_2 = 0.10
SIBLING_RATE_3 = 0.15
SIBLING_RATE_4_PLUS = 0.20

# Server startup default for the logical clock (PRD §2.4).
DEFAULT_CLOCK = "2026-04-01T00:00:00Z"

# Default instructor buffer minutes when omitted (PRD §3.9).
DEFAULT_BUFFER_MINUTES = 15
