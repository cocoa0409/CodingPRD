"""Domain thresholds — numeric constants from the PRD's pricing and refund rules.

Generic NON_EXISTENT_UUID comes from the framework barrel export.
"""

# Basis-point denominator: 10000 bps == factor 1.0 (PRD §2.6).
BPS_DENOM = 10000

# Default rate multiplier when no rate period governs a night (PRD §3.2: factor 1.0).
DEFAULT_MULTIPLIER_BPS = 10000

# DIRECT-channel deposit policy: 30% of total (PRD §3.3).
DIRECT_DEPOSIT_BPS = 3000

# Cancellation refund tiers keyed on days_before checkin (PRD §3.5).
TIER_FULL_DAYS = 14      # >= 14 days  -> 100%
TIER_HALF_DAYS = 7       # >= 7 days   ->  50%
TIER_TOKEN_DAYS = 1      # >= 1 day    ->  10%
FULL_BPS = 10000
HALF_BPS = 5000
TOKEN_BPS = 1000

# Inn config defaults (PRD §3.1).
DEFAULT_CHECKIN_TIME = "15:00"
DEFAULT_CHECKOUT_TIME = "11:00"
DEFAULT_GIFT_CERT_EXPIRY_DAYS = 365
DEFAULT_TURNOVER_MINUTES = 180

# Logical-clock startup default (PRD §2.4).
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# A syntactically valid UUID that resolves to no entity (for NOT_FOUND tests).
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

TEST_DEFAULTS = {
    "BASE_RATE_CENTS": 10000,
    "MAX_OCCUPANCY": 2,
}
