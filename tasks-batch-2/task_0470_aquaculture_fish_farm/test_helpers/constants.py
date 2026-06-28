"""Domain thresholds — numeric constants from the PRD's calculation rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Growth model (§3.2) — biomass estimation tier and survival constants.
GROWTH_TIER1_DAYS = 90
GROWTH_TIER2_DAYS = 180
SURVIVAL_DECAY_PER_DAY = 0.0005
SURVIVAL_FLOOR = 0.80

# Feed-conversion-ratio gain floor (§3.3 / §3.8).
FCR_GAIN_FLOOR = 0.01

# Water-quality classification thresholds (§3.4).
DO_CRITICAL = 4.0
DO_WARNING = 6.0
NH3_CRITICAL = 1.0
NH3_WARNING = 0.5

# Volume discount tiers for sales order totals (§3.10).
DISCOUNT_TIERS = {
    "NONE": 0.00,
    "BRONZE": 0.05,
    "SILVER": 0.10,
    "GOLD": 0.15,
}

# Pagination bounds (§2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Logical clock default at server startup (§2.11).
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"
