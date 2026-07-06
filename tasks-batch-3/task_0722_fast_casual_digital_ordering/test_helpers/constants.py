"""Domain thresholds — numeric constants from PRD calculations and §2."""

# Delivery fee (PRD §3.5)
DELIVERY_BASE_CENTS = 399
LOCKER_FEE_CENTS = 99
DEFAULT_SURCHARGE_BPS = 0
SURCHARGE_BPS_BY_STATE = {"CA": 800, "NY": 875, "TX": 0}

# Points redemption (PRD §3.5)
MIN_REDEEM_BLOCK = 100
BLOCK_VALUE_CENTS = 100

# Points earn (PRD §3.6)
CENTS_PER_POINT = 10

# Queue posture (PRD §2.7)
BUSY_THRESHOLD = 0.70
SURGE_THRESHOLD = 1.0

# Loyalty tiers (PRD §2.10)
GOLD_FLOOR = 5000
PLATINUM_FLOOR = 15000

# Subscription multiplier base (PRD §3.9)
MULTIPLIER_BASE_BPS = 10000

# Logical clock default (PRD §2.11)
CLOCK_DEFAULT_UTC = "2026-03-01T00:00:00Z"

# A window that is active under the default clock and far in the future.
DEFAULT_WINDOW_START = "2026-03-01T00:00:00Z"
DEFAULT_WINDOW_END = "2026-12-31T00:00:00Z"
