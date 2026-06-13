"""Domain thresholds — numeric constants from the PRD's calculations and rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Basis-point denominator for the rush-retrieval multiplier (PRD Section 3.9).
BPS_DENOMINATOR = 10000

# Default rush multiplier in basis points: 15000 bps == 1.5x (PRD Section 3.2).
DEFAULT_RUSH_MULTIPLIER_BPS = 15000

# Minimum permitted rush multiplier: a rush is never cheaper than a standard
# retrieval (PRD Section 3.2).
MIN_RUSH_MULTIPLIER_BPS = 10000

# On-site buffer applied on each side of an on-site order window, in minutes
# (PRD Section 3.3).
ONSITE_BUFFER_MINUTES = 30

# Standard rate card values used across test fixtures (cents unless noted).
RATE_SCHEDULED_PER_KG = 5
RATE_ONETIME_PER_KG = 8
RATE_ONSITE_TRIP_FEE = 2500
RATE_CONSOLE_SWAP_FEE = 1000
RATE_STORAGE_PER_BOX_PER_PERIOD = 300
RATE_RETRIEVAL_FEE = 4000
RATE_RUSH_MULTIPLIER_BPS = 15000

TEST_DEFAULTS = {
    "BUSINESS_NAME": "Test Business",
    "BILLING_EMAIL": "b@x.com",
}
