"""Domain thresholds — numeric constants from PRD pricing, engineering, and lead-time rules."""

# Engineering requirement thresholds (PRD §3.1)
SNOW_THRESHOLD_PSF = 30          # strict > 30 triggers engineering
WIND_THRESHOLD_MPH = 130         # >= 130 triggers engineering

# Quote base-price rate tables (PRD §3.2)
BASE_RATE_CENTS = {
    "SCREEN_ROOM": 4500,
    "THREE_SEASON": 9000,
    "FOUR_SEASON": 16000,
}
MATERIAL_MULT_MILLI = {
    "ALUMINUM": 1000,
    "VINYL": 1150,
    "THERMAL_BREAK_ALUMINUM": 1300,
}

# Quote add-on line items (PRD §3.2)
SLAB_POUR_CENTS = 320150
ENGINEERING_STAMP_CENTS = 95075
HOA_FILING_CENTS = 25033

# Sales tax (PRD §3.2)
TAX_RATE_MILLI = 75              # 7.5% expressed in thousandths

# Financing APR tiers (PRD §3.3)
TIER_EXCELLENT_MIN = 760
TIER_GOOD_MIN = 700
TIER_FAIR_MIN = 650
APR_EXCELLENT_BPS = 599
APR_GOOD_BPS = 999
APR_FAIR_BPS = 1499
MIN_APPROVAL_SCORE = 650
MAX_PRINCIPAL_CENTS = 7500000

# Manufacture lead time (PRD §3.5)
MATERIAL_BASE_DAYS = {
    "ALUMINUM": 21,
    "VINYL": 28,
    "THERMAL_BREAK_ALUMINUM": 35,
}
LARGE_FOOTPRINT_SQFT = 200       # strict > 200 surcharges
LARGE_SURCHARGE_DAYS = 14
FOUR_SEASON_SURCHARGE_DAYS = 10

# Permit / install / warranty (PRD §3.4, §3.6, §3.7)
PERMIT_VALIDITY_DAYS = 180
MAX_RESUBMISSIONS = 3
SITE_REST_BUFFER_HOURS = 24
WARRANTY_YEARS = {
    "SCREEN_ROOM": 1,
    "THREE_SEASON": 5,
    "FOUR_SEASON": 10,
}

# Logical clock default (PRD §2.9)
CLOCK_DEFAULT_ISO = "2026-04-01T00:00:00Z"
