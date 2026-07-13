"""Domain thresholds — numeric constants from the PRD's pricing, lead-time, and
credit computations (§2.5, §3.2, §3.3, §3.4, §3.5, §3.7, §3.8)."""

# Line-item pricing (PRD §3.2)
MIN_BILLABLE_SQFT = 4.0
RATE_CENTS_PER_SQFT = {
    "ANNEALED": 800,
    "TEMPERED": 1400,
    "LAMINATED": 2000,
    "INSULATED": 2600,
}
THICKNESS_MULT = {6: 1.0, 10: 1.25, 12: 1.5}
EDGE_RATE_CENTS = {"NONE": 0, "POLISHED": 150, "BEVELED": 300}
PRODUCT_FEE_CENTS = {
    "SHOWER_ENCLOSURE": 5000,
    "STOREFRONT": 8000,
    "CUSTOM_MIRROR": 2000,
    "TABLETOP": 1500,
}

# Quote totals & validity (PRD §3.3)
TIER_DISCOUNT_PCT = {"WALK_IN": 0.0, "BRONZE": 0.05, "SILVER": 0.10, "GOLD": 0.15}
QUOTE_VALID_DAYS = 30
WARRANTY_DAYS = 365

# Lead-time estimation (PRD §3.3 / §3.4)
FAB_BASE_DAYS = 3
STD_THROUGHPUT_SQFT_PER_DAY = 50
INSTALL_DAYS = 2

# Credit / remake exposure (PRD §3.7 / §3.8)
REMAKE_SURCHARGE_CENTS = 2500

# Pagination (PRD §2.3)
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# Logical clock startup default (PRD §3.8)
CLOCK_STARTUP_UTC = "2026-05-01T00:00:00Z"
