"""Domain thresholds — numeric constants from the PRD pricing and scheduling rules."""

# Weight tier upper bounds in whole pounds (PRD §3.9, inclusive upper edge).
WEIGHT_TIER = {
    "SMALL_MAX": 25,    # <= 25 -> SMALL
    "MEDIUM_MAX": 75,   # 26..75 -> MEDIUM
    "LARGE_MAX": 150,   # 76..150 -> LARGE
    # > 150 -> XLARGE
}

# Private flat cremation rates per weight tier in cents (PRD §3.9).
PRIVATE_RATE_CENTS = {
    "SMALL": 12000,
    "MEDIUM": 18000,
    "LARGE": 26000,
    "XLARGE": 38000,
}

EXPEDITE_SURCHARGE_CENTS = 5000

# Fixed pooled firing cost allocated across communal members (PRD §3.9).
COMMUNAL_FIRING_TOTAL_CENTS = 30000

# Owner-billed handling fee tiers keyed on subtotal (PRD §3.10).
FEE_LOW_TIER_MAX_EXCLUSIVE = 20000   # subtotal < 20000 -> low
FEE_MID_TIER_MAX_INCLUSIVE = 50000   # 20000..50000 inclusive -> mid
FEE_LOW_CENTS = 2500
FEE_MID_CENTS = 1500
FEE_HIGH_CENTS = 0

# Keepsake catalog prices in cents (PRD §3.12).
KEEPSAKE_CATALOG_CENTS = {
    "PAW_PRINT": 4500,
    "CLAY_IMPRESSION": 5500,
    "FUR_CLIPPING": 2000,
    "URN": 8000,
    "PENDANT": 9500,
}

# Memorial add-on catalog prices in cents (PRD §3.12).
MEMORIAL_CATALOG_CENTS = {
    "ONLINE_MEMORIAL": 3000,
    "VIEWING_SESSION": 12000,
    "TRIBUTE_VIDEO": 7000,
}

# Viewing room buffer (PRD §3.12): fifteen minutes.
VIEWING_BUFFER_MINUTES = 15

# Clinic credit limit default (PRD §3.1).
DEFAULT_CREDIT_LIMIT_CENTS = 500000

# Logical clock startup default (PRD §2.9).
CLOCK_STARTUP_DEFAULT = "2026-01-01T00:00:00.000Z"

# Pagination defaults (PRD §2.3).
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "default_offset": 0}
