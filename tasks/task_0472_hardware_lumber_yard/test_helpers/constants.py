"""Domain thresholds — numeric constants drawn from the PRD's calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Loyalty tier thresholds (PRD 3.3) — keyed on the pre-discount subtotal in cents.
LOYALTY = {
    "TIER1_MIN_CENTS": 50000,    # >= 50000 earns 2%
    "TIER2_MIN_CENTS": 100000,   # >= 100000 earns 5%
    "TIER1_RATE": 0.02,
    "TIER2_RATE": 0.05,
    "POINTS_PER_DOLLAR": 1,      # floor(total_cents / 100)
}

# Service base fees (PRD 3.8), in cents, keyed on service_type.
SERVICE_BASE_CENTS = {
    "KEY_CUT": 300,
    "PAINT_MIX": 800,
    "PROPANE_EXCHANGE": 2499,
}

# Drop-ship special-order surcharge (PRD 3.9).
SPECIAL_ORDER = {
    "DROP_SHIP_SURCHARGE_CENTS": 1500,
    "DROP_SHIP_FREE_THRESHOLD_CENTS": 50000,   # goods >= 50000 ships free
}

# Co-op purchase-order rebate (PRD 3.10).
COOP = {
    "COOP_MIN_GROSS_CENTS": 200000,            # gross must be >= 200000 to qualify
    "MAX_REBATE_PCT": 0.25,
}

# Rental day billing (PRD 3.7).
RENTAL = {
    "MIN_BILLED_DAYS": 1,
}

# Server logical clock startup default (PRD 3.11).
CLOCK_DEFAULT_ISO = "2026-01-01T00:00:00Z"
