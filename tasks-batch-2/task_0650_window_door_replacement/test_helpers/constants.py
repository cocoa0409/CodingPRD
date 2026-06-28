"""Domain thresholds — numeric constants from the PRD calculations and rules."""

# Per-opening pricing: base rate cents per square foot by product type (PRD §3.2).
BASE_RATE_CENTS_PER_SQFT = {
    "DOUBLE_HUNG": 4200,
    "CASEMENT": 4800,
    "PICTURE": 3600,
    "SLIDING_PATIO_DOOR": 5200,
    "ENTRY_DOOR": 6000,
}

# Glass uplift cents per square foot by glass package (PRD §3.2).
GLASS_UPLIFT_CENTS_PER_SQFT = {
    "STANDARD": 0,
    "LOWE_DUAL": 900,
    "LOWE_TRIPLE": 1800,
}

# U-factor by glass package (PRD §3.2 / §2.10).
U_FACTOR_BY_GLASS = {
    "STANDARD": 0.40,
    "LOWE_DUAL": 0.27,
    "LOWE_TRIPLE": 0.20,
}

ENERGY_STAR_U_MAX = 0.30

# Quote estimate discount tiers (PRD §3.3).
TIER1_THRESHOLD_CENTS = 2_000_000
TIER2_THRESHOLD_CENTS = 4_000_000
TIER1_PCT = 0.05
TIER2_PCT = 0.10
INSTALL_FLAT_CENTS = 35_000
INSTALL_PER_OPENING_CENTS = 1_500

# 25C rebate (PRD §3.3).
CREDIT_RATE = 0.30
WINDOW_ANNUAL_CAP_CENTS = 60_000
DOOR_TOTAL_CAP_CENTS = 50_000

# Manufacturing lead time, logical days by product type (PRD §3.6).
BASE_LEAD_DAYS_BY_TYPE = {
    "DOUBLE_HUNG": 28,
    "CASEMENT": 35,
    "PICTURE": 21,
    "SLIDING_PATIO_DOOR": 49,
    "ENTRY_DOOR": 42,
}
TRIPLE_GLAZE_SURCHARGE_DAYS = 14

# Financing APR table, basis points keyed agi_band x term_months (PRD §3.5).
APR_TABLE = {
    "LOW": {12: 0, 24: 0, 36: 599, 60: 899},
    "STANDARD": {12: 0, 24: 499, 36: 899, 60: 1299},
    "HIGH": {12: 299, 24: 799, 36: 1199, 60: 1599},
}

# Service charge (PRD §3.9).
BASE_TRIP_CENTS = 9_500
OUT_OF_WARRANTY_SURCHARGE_CENTS = 5_000
WARRANTY_WINDOW_DAYS = 730

# Referral reward (PRD §3.10).
REWARD_RATE = 0.02
REWARD_CAP_CENTS = 50_000

# Quote expiry window (PRD §3.3).
QUOTE_EXPIRY_DAYS = 30

# Jurisdiction inspection window, logical days (PRD §2.10 / §3.8).
INSPECTION_WINDOW_DAYS = {
    "WEST_STRICT": 7,
    "NORTHEAST_STD": 14,
    "CENTRAL_LIGHT": 30,
}

# Logical-clock startup default (PRD §2.9).
CLOCK_DEFAULT = "2026-04-01T00:00:00Z"

# Pagination (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
