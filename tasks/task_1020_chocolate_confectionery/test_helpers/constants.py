"""Domain thresholds — numeric constants from the PRD calculations (PRD §2.6, §3.5, §3.7)."""

# Order totals (PRD §3.5 / §2.6)
TAX_RATE = 0.0725
GIFT_WRAP_FEE_CENTS = 500

# Wholesale volume-tier discounts (PRD §3.5) — inclusive lower boundaries.
WHOLESALE_TIERS = {
    "TIER1_MIN_UNITS": 50,
    "TIER1_DISCOUNT": 0.10,
    "TIER2_MIN_UNITS": 200,
    "TIER2_DISCOUNT": 0.18,
    "TIER3_MIN_UNITS": 500,
    "TIER3_DISCOUNT": 0.25,
}

# Custom-order pricing (PRD §3.7)
MOLD_SURCHARGE_PER_UNIT_CENTS = 300
MOLD_SETUP_FEE_CENTS = 25000

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Logical clock startup default (PRD §4)
CLOCK_STARTUP_DEFAULT = "2026-07-01T00:00:00Z"
