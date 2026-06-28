"""Domain thresholds — numeric constants from the PRD's calculations and §2.6.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Basis-point denominator (PRD §2.6): a value in basis points is divided by
# 10000 and added to one to form the premium multiplier.
BPS_DENOMINATOR = 10000

# Weeks per year used to annualize a frozen weekly premium (PRD §3.5).
WEEKS_PER_YEAR = 52

# Consecutive FAILED deductions that lapse a policy (PRD §3.7): the third
# consecutive FAILED lapses, the second does not.
LAPSE_THRESHOLD = 3

# Pagination bounds (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Canonical fixture values reused across setups.
PRODUCT_A_BASE_PREMIUM_CENTS = 1200
PRODUCT_A_EOI_SURCHARGE_BPS = 1500
PRODUCT_A_ANNUAL_CAP_CENTS = 500000
PRODUCT_A_PORTABILITY_LOADUP_BPS = 1000

# Default GI window for period "OE-2026".
GI_WINDOW_START = "2026-03-01T00:00:00Z"
GI_WINDOW_END = "2026-04-01T00:00:00Z"
BENEFIT_YEAR_START = "2026-01-01T00:00:00Z"

# A clock instant that falls strictly inside the GI window.
IN_WINDOW_INSTANT = "2026-03-15T00:00:00Z"

VALID_ROUTING_NUMBER = "123456789"
