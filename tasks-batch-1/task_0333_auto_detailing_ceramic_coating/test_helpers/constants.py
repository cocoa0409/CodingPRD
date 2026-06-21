"""Domain thresholds — numeric constants from the PRD's pricing, scheduling,
membership, loyalty, and guarantee rules. Generic NON_EXISTENT_UUID comes from
the framework.
"""

# Pricing / payment basis-point and threshold constants.
THRESHOLDS = {
    "MEMBER_DISCOUNT_BPS": 1500,   # member discount on the raw package price
    "DEPOSIT_BPS": 2000,           # deposit = round_half_up(provisional * 2000 / 10000)
    "SILVER_THRESHOLD_CENTS": 50000,
    "GOLD_THRESHOLD_CENTS": 150000,
    "CYCLE_DAYS": 30,
    "CREDITS_PER_CYCLE": 1,
    "MONTHLY_FEE_CENTS": 4900,
}

# Reference vehicle-size multipliers (basis points).
SIZE_MULTIPLIER_BPS = {
    "SEDAN": 10000,
    "SUV": 13000,
    "TRUCK": 15000,
    "XL": 17500,
}

# Canonical catalog rows used across fixtures. These mirror the values the
# design indices seed and against which the literal expected totals are pinned.
PACKAGE_DEFAULTS = {
    "WASH":    {"base_price_cents": 4000,  "prep_minutes": 10, "service_minutes": 30,  "cure_minutes": 0,    "guarantee_days": 0},
    "FULL":    {"base_price_cents": 12000, "prep_minutes": 20, "service_minutes": 120, "cure_minutes": 0,    "guarantee_days": 7},
    "CERAMIC": {"base_price_cents": 50000, "prep_minutes": 45, "service_minutes": 240, "cure_minutes": 1440, "guarantee_days": 90},
}

ADDON_DEFAULTS = {
    "ENGINE_BAY": {"price_cents": 3500, "extra_minutes": 15},
    "PET_HAIR":   {"price_cents": 4500, "extra_minutes": 20},
    "HEADLIGHT":  {"price_cents": 6000, "extra_minutes": 25},
}
