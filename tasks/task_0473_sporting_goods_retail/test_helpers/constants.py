"""Domain thresholds and numeric constants from PRD calculation rules.

Generic NON_EXISTENT_UUID comes from the framework, not here.
"""

# Loyalty tier thresholds (PRD §3.5): inclusive lower bounds.
LOYALTY_TIER_THRESHOLDS = {
    "SILVER_MIN": 500,
    "GOLD_MIN": 2000,
    "PLATINUM_MIN": 5000,
}

# Loyalty / service tier discount percentages (PRD §3.5, §3.9).
LOYALTY_DISCOUNT_PCT = {
    "BRONZE": 0,
    "SILVER": 5,
    "GOLD": 10,
    "PLATINUM": 15,
}

# Embroidery surcharge (PRD §3.6 / §3.11).
EMBROIDERY_SURCHARGE_CENTS = 500

# Team bulk-discount tiers (PRD §3.11).
TEAM_BULK_TIERS = {
    "TIER1_UNITS": 20,
    "TIER2_UNITS": 50,
    "TIER3_UNITS": 100,
    "TIER1_PCT": 6,
    "TIER2_PCT": 12,
    "TIER3_PCT": 20,
}

# Service base fees (PRD §3.9).
SERVICE_BASE_FEE_CENTS = {
    "SKATE_SHARPEN": 1000,
    "RACKET_STRING": 2500,
}

# License fees (PRD §3.4).
LICENSE_FEE_CENTS = {
    "RESIDENT": 2500,
    "NONRESIDENT": 6500,
}

# Price-match floor (PRD §3.7): floor is 50% of line unit price, rounded up.
PRICE_MATCH_FLOOR_PCT = 50

# Logical clock startup default (PRD §2.7).
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00Z"

# Pagination bounds (PRD §2.3).
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "MIN_OFFSET": 0}
