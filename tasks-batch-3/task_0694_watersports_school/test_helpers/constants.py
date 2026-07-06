"""Domain thresholds — numeric constants from the PRD calculations (§3.8).

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Group-discount schedule by party count (PRD §3.8).
GROUP_PCT = {
    "LE_1": 0.00,    # 1 or fewer
    "2_3": 0.10,     # 2 or 3
    "4_6": 0.20,     # 4, 5, or 6
    "7PLUS": 0.30,   # 7 or more
}

# Membership-discount schedule by tier (PRD §3.8).
MEMBER_PCT = {
    "NONE": 0.00,
    "BASIC": 0.05,
    "PREMIUM": 0.15,
}

# Rental-fee marginal tier breakpoints (PRD §3.8).
RENTAL_TIER1_HOURS = 2     # first 2h at full rate
RENTAL_TIER2_HOURS = 6     # next 6h (hours 3-8) at half rate
RENTAL_TIER2_RATE_PCT = 0.5
RENTAL_TIER3_RATE_PCT = 0.25  # beyond hour 8

# Refund lead-time waterfall boundaries in hours (PRD §3.8, inclusive).
FULL_REFUND_LEAD_HOURS = 48
HALF_REFUND_LEAD_HOURS = 24

# Equipment-rental overlap turnaround buffer (PRD §3.9).
RENTAL_TURNAROUND_BUFFER_HOURS = 1

# Logical-clock startup default (PRD §2.4).
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
