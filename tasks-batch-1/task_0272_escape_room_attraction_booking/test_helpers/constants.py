"""Domain thresholds and defaults — numeric constants from the PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Basis-point denominator: 10000 bps == factor 1.0 (PRD Section 2.8).
BPS_DENOM = 10000

# Pagination bounds (PRD Section 2.3).
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Venue financial-policy defaults (PRD Section 3.1).
VENUE_DEFAULTS = {
    "NO_SHOW_FEE_PCT": 0.5,
    "NO_SHOW_STRIKE_LIMIT": 3,
}

# Room defaults (PRD Section 3.1).
ROOM_DEFAULTS = {
    "MIN_AGE": 0,
    "WAIVER_REQUIRED": True,
    "PRIVATE_SURCHARGE_CENTS": 0,
    "RESET_BUFFER_MINUTES": 0,
}

# PricingRule multiplier defaults (PRD Section 3.1): 10000 bps == 1.0x.
PRICING_DEFAULTS = {
    "PEAK_MULTIPLIER_BPS": 10000,
    "LARGE_GROUP_MULTIPLIER_BPS": 10000,
}

# A well-formed UUID v4 that is not minted by the server (for not-found probes).
NONEXISTENT_BOOKING_UUID = "00000000-0000-4000-8000-000000000000"
