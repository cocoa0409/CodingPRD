"""Domain thresholds — numeric constants from the PRD calculations and shipping rules."""

# Shipping ladder (PRD §3.6)
SHIPPING = {
    "DOMESTIC_BASE_CENTS": 500,
    "DOMESTIC_PER_KG_CENTS": 150,
    "INTL_BASE_CENTS": 1500,
    "INTL_PER_KG_CENTS": 400,
    "SHIPPING_CAP_CENTS": 5000,
}

# Platform fee (PRD §2.5, §4 settlement read)
FEE_RATE = 0.05

# Backer reliability base value (PRD §3.1, §3.7)
BASE_RELIABILITY_SCORE = 100.0

# Early-bird tier buffer gap (PRD §3.2)
TIER_GAP_SECONDS = 3600

# Pagination bounds (PRD §2.3)
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# Standard clock instants used across fixtures (ISO 8601 UTC, 3 fractional digits).
CLOCK_LAUNCH = "2026-06-01T00:00:00.000Z"
CLOCK_DEADLINE = "2026-07-01T00:00:00.000Z"


def expected_shipping_cents(total_weight_grams: int, destination_zone: str) -> int:
    """Compute the capped shipping component per PRD §3.6."""
    import math
    billable_kg = math.ceil(total_weight_grams / 1000)
    if destination_zone == "DOMESTIC":
        shipping = SHIPPING["DOMESTIC_BASE_CENTS"] + billable_kg * SHIPPING["DOMESTIC_PER_KG_CENTS"]
    else:  # INTL
        shipping = SHIPPING["INTL_BASE_CENTS"] + billable_kg * SHIPPING["INTL_PER_KG_CENTS"]
    return min(shipping, SHIPPING["SHIPPING_CAP_CENTS"])
