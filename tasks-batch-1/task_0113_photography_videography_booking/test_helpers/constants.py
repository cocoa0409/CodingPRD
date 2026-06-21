"""Domain thresholds and constants from the PRD's pricing and limit rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Deposit floor (PRD §3.2): the retainer is at least 5000 cents unless the total
# is below it.
MIN_DEPOSIT_CENTS = 5000

# Cancellation lead-time tiers (PRD §3.8).
CANCEL_TIER_EARLY_DAYS = 14   # >= 14 whole days -> 25%
CANCEL_TIER_MID_DAYS = 7      # >= 7 and < 14 -> 50%; < 7 -> 100%

# Add-on PRINT volume-discount tier rates (PRD §3.8).
PRINT_TIER1_RATE = 1.00       # units 1..10
PRINT_TIER2_RATE = 0.90       # units 11..50
PRINT_TIER3_RATE = 0.80       # units 51+

# ALBUM flat binding surcharge (PRD §3.8).
ALBUM_BINDING_SURCHARGE_CENTS = 3500

# License fee base and multipliers (PRD §3.8).
LICENSE_BASE_CENTS = 20000
PERPETUAL_EFFECTIVE_MONTHS = 60   # term_months == 0 priced as a 60-month term
SCOPE_MULTIPLIERS = {
    "PERSONAL": 1.0,
    "COMMERCIAL": 2.5,
    "EDITORIAL": 1.8,
    "EXCLUSIVE": 4.0,
}
TERRITORY_MULTIPLIERS = {
    "LOCAL": 1.0,
    "NATIONAL": 1.5,
    "WORLDWIDE": 2.2,
}

# Second-shooter travel buffer (PRD §3.5): 60 minutes extended on each side.
TRAVEL_BUFFER_MINUTES = 60

# Limits (PRD §3.4, §3.7).
MAX_RESCHEDULES = 3
MAX_REVISION_ROUNDS = 2

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
