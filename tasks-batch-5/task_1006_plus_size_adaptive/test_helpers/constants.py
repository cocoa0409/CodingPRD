"""Domain thresholds — numeric constants stated verbatim in the PRD.

Only constants the PRD gives a concrete value are listed here. The PRD leaves
several temporal / count thresholds unnamed (return window, try-on window,
late-cancel window and fee, no-show suspension threshold); those are deliberately
NOT declared here because no test may assert an outcome that depends on them.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Loyalty earning & tiers (PRD §3.1, §3.3, §3.6).
EARN_CENTS_PER_POINT = 100
TIER_INSIDER_MIN = 500
TIER_VIP_MIN = 2000
TIER_UP_BONUS_CENTS = {"INSIDER": 1000, "VIP": 2500}

# Checkout order-total calculation (PRD §3.3).
TIER_DISCOUNT_PCT = {"STANDARD": 0.00, "INSIDER": 0.05, "VIP": 0.10}
REDEEM_VALUE_CENTS_PER_POINT = 5
REDEEM_CAP_PCT = 0.30

# Subscription styling fees by plan tier (PRD §3.6).
STYLING_FEE_CENTS = {"ESSENTIALS": 0, "SIGNATURE": 2500, "LUXE": 5000}

# Default product restocking-fee fraction (PRD §3.2).
DEFAULT_RESTOCK_FEE_PCT = 0.15

# A well-formed UUID that resolves to no resource (for not-found probes).
MISSING_UUID = "00000000-0000-4000-8000-000000000000"

# Server logical-clock startup default (PRD §3.7).
CLOCK_DEFAULT = "2026-07-01T00:00:00Z"
