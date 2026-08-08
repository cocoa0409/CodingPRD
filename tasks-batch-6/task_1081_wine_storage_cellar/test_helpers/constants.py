"""Domain thresholds — numeric constants from the Wine-Storage Cellar PRD calculations."""

# Storage fee (PRD 3.2)
STORAGE_BASE_RATE_CENTS = {"SMALL": 2000, "MEDIUM": 3500, "LARGE": 6000}
CLIMATE_MULTIPLIER = {"RED": 1.00, "WHITE": 1.15, "SPARKLING": 1.30}
FULL_OCCUPANCY_SURCHARGE = 0.10
MIN_MONTHLY_FEE_CENTS = 2500
MAX_MONTHLY_FEE_CENTS = 9000

# Insurance premium (PRD 3.6)
INSURANCE_BASE_RATE = {"DOCUMENTED": 0.015, "UNVERIFIED": 0.025, "DISPUTED": 0.040}
COVERAGE_TIER_FACTOR = {"BASIC": 0.5, "FULL": 1.0}

# Appraisal valuation (PRD 3.5)
REPLACEMENT_UPLIFT = 1.20

# Consignment proceeds waterfall (PRD 3.7)
COMMISSION_TIER_1_CENTS = 5_000_000     # <= this -> 0.20
COMMISSION_TIER_2_CENTS = 20_000_000    # <= this -> 0.15 ; else 0.10
PLATFORM_FEE_PCT = 0.03

# Member wallet (PRD 3.6 / 2.8)
WALLET_FLOOR_CENTS = -100_000

# Courier / maintenance temporal (PRD 3.9)
MAINTENANCE_BUFFER_MINUTES = 120

# Climate band (PRD 3.9)
TEMP_MIN_C = 10.0
TEMP_MAX_C = 16.0
HUMID_MIN_PCT = 60.0
HUMID_MAX_PCT = 80.0

# Logical clock default (PRD 2.5)
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# Appraiser identities used to satisfy segregation-of-duties in fixtures/tests.
APPRAISER_ALPHA = "appraiser-alpha"
APPRAISER_BETA = "appraiser-beta"

TEST_DEFAULTS = {
    "MEMBER_TIER": "STANDARD",
    "LOCKER_CAPACITY": 3,
}
