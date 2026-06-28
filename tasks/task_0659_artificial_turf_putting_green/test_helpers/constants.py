"""Domain thresholds — numeric constants from the PRD's pricing and lifecycle rules.

Generic NON_EXISTENT_UUID comes from the framework. Default server clock is
2026-04-01T00:00:00Z (PRD §3.13).
"""

# Pricing constants (PRD §3.3, §3.4, §3.5)
MIN_JOB_CENTS = 150_000

VARIANT_SURCHARGE_PCT = {
    "STANDARD": 0.00,
    "PET": 0.12,
    "PLAYGROUND": 0.18,
    "PUTTING_GREEN": 0.25,
}

VOLUME_TIER1_SQFT = 1000
VOLUME_TIER1_PCT = 0.05
VOLUME_TIER2_SQFT = 2000
VOLUME_TIER2_PCT = 0.10

EXCAVATION_CENTS_PER_SQFT_INCH = 22
FRENCH_DRAIN_CENTS_PER_SQFT = 180
PANEL_CENTS_PER_SQFT = 320

# Waste-factor tiers (PRD §3.2)
WASTE_1RUN_PCT = 5.0
WASTE_2RUN_PCT = 8.0
WASTE_3_4RUN_PCT = 12.0
WASTE_5PLUS_PCT = 15.0

# Deposit clamp band (PRD §3.5)
DEPOSIT_MIN_PCT = 0.10
DEPOSIT_MAX_PCT = 0.50

# Drainage tier slope thresholds (PRD §3.4)
SLOPE_FLAT_MAX = 2.0
SLOPE_STEEP_MIN = 5.0

# Warranty terms by tier (PRD §3.10)
WARRANTY_COVERAGE_MONTHS = {"BASIC": 12, "PLUS": 36, "PREMIUM": 96}
WARRANTY_MAINT_VISITS = {"BASIC": 0, "PLUS": 1, "PREMIUM": 2}

# Callback billing (PRD §3.11)
CALLBACK_FLAT_CENTS = 12_500
REWORK_CENTS_PER_SQFT = 35

# Quote time-to-live (PRD §3.6)
QUOTE_TTL_DAYS = 30

# Logical clock default (PRD §3.13)
DEFAULT_CLOCK_UTC = "2026-04-01T00:00:00Z"

# Pagination bounds (PRD §2.3)
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_DEFAULT_LIMIT = 10
