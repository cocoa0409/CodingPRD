"""Domain thresholds — numeric constants from PRD calculations (§2.7, §3.5, §3.9, §3.11)."""

# Animal-unit conversion (PRD §2.7): one AU == 454 kg of live weight.
AU_KG = 454

# Weight-ticket pricing tiers (PRD §3.9), per-head net weight class.
TIER_LIGHT_MAX = 250        # net < 250 -> LIGHT
TIER_MEDIUM_MAX = 400       # 250 <= net < 400 -> MEDIUM; net >= 400 -> HEAVY
PRICE_LIGHT_PER_100KG = 520.00
PRICE_MEDIUM_PER_100KG = 480.00
PRICE_HEAVY_PER_100KG = 440.00

# Species gestation lengths in whole days (PRD §3.5).
GESTATION_DAYS = {
    "CATTLE": 283,
    "SHEEP": 147,
    "GOAT": 150,
}

# Rolling mortality window (PRD §3.11).
MORTALITY_WINDOW_DAYS = 365

# Pagination bounds (PRD §2.3).
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_LIMIT_DEFAULT = 10
