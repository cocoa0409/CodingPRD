"""Domain thresholds — numeric constants from PRD calculations."""

# Quote pricing (PRD 3.3)
MATERIAL_MULT = {
    "MELAMINE": 1.00,
    "LAMINATE": 1.15,
    "WOOD": 1.40,
    "PREMIUM_WOOD": 1.80,
}

# Volume discount tiers keyed on total_units (PRD 3.3)
VOLUME_DISCOUNT = {
    "tier1": 0.00,   # total_units 1-19
    "tier2": 0.05,   # total_units 20-49
    "tier3": 0.10,   # total_units 50+
}

PROMO_RATE = {
    "SPRING10": 0.10,
    "VIP15": 0.15,
}
PROMO_CAP_CENTS = 200000

TAX_RATE = {
    "NORTH": 0.0725,
    "SOUTH": 0.0650,
    "EAST": 0.0800,
    "WEST": 0.0925,
}

# Lead time (PRD 3.5)
BASE_LEAD_DAYS = {
    "tier1": 14,   # 1-19 units
    "tier2": 21,   # 20-49 units
    "tier3": 35,   # 50+ units
}
MATERIAL_LEAD_ADD = {
    "MELAMINE": 0,
    "LAMINATE": 3,
    "WOOD": 7,
    "PREMIUM_WOOD": 14,
}
REGION_LEAD_ADD = {
    "NORTH": 0,
    "SOUTH": 2,
    "EAST": 4,
    "WEST": 6,
}

# Deposit floor by room type (PRD 3.5)
DEPOSIT_PCT_BY_ROOM = {
    "REACH_IN_CLOSET": 0.30,
    "WALK_IN_CLOSET": 0.35,
    "GARAGE": 0.25,
    "PANTRY": 0.30,
    "HOME_OFFICE": 0.35,
}

# Financing (PRD 3.9)
MAX_FINANCE_LTV = 0.80
APR_BY_TERM = {
    12: 0.0000,
    24: 0.0599,
    36: 0.0899,
    48: 0.1199,
}

# Quote validity window (PRD 3.3 / 3.4)
QUOTE_VALIDITY_DAYS = 30

# Warranty (PRD 3.10)
WARRANTY_DAYS = 365
COVERED_DEFECTS = ["HARDWARE", "FINISH", "FIT", "STRUCTURAL"]

# Server logical-clock startup default (PRD Section 4 narrative)
CLOCK_DEFAULT = "2026-04-01T00:00:00Z"
