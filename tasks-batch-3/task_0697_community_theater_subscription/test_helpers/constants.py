"""Domain thresholds — numeric constants from the PRD's pricing and donor rules.

All amounts are integer cents (PRD §2.6). The generic NON_EXISTENT_UUID comes
from the framework.
"""

# Single-ticket tier base prices, in cents (PRD §3.5).
TIER_BASE_CENTS = {
    "PREMIUM": 9000,
    "STANDARD": 6000,
    "VALUE": 3500,
}

# Donor discount fractions by donor level (PRD §3.5).
DONOR_DISCOUNT_PCT = {
    "NONE": 0.0,
    "FRIEND": 0.05,
    "PATRON": 0.10,
    "BENEFACTOR": 0.20,
}

# Subscription tier weights applied to base_subscription_fee_cents (PRD §3.3).
TIER_WEIGHT = {
    "PREMIUM": 1.5,
    "STANDARD": 1.0,
    "VALUE": 0.6,
}

# Exchange fee constants, in cents (PRD §3.7).
PAID_EXCHANGE_FEE_CENTS = 800
FLEX_PASS_NONSUB_FEE_CENTS = 500

# Donor-level lifetime thresholds, in cents; lower edge inclusive (PRD §3.6).
DONOR_FRIEND_MIN = 25000
DONOR_PATRON_MIN = 100000
DONOR_BENEFACTOR_MIN = 500000

# Logical-clock server startup default (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
