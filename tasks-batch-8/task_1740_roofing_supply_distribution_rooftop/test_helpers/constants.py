"""Domain thresholds — numeric constants pinned by the PRD.

PRD §3.3 (takeoff estimate), §3.4 (order pricing), §3.5 (delivery fee),
§3.6 (surge allocation waterfall), §3.8 (return credit).
"""

# Takeoff estimate (PRD §3.3)
ACCESSORY_COVERAGE_FEET_PER_BUNDLE = 33
ACCESSORY_PRICE_CENTS = 4200

# Order pricing (PRD §3.4)
VOLUME_MIN_SUBTOTAL_CENTS = 250000
STANDARD_DISCOUNT_PCT = 0
PREFERRED_DISCOUNT_PCT = 5
VOLUME_DISCOUNT_PCT = 8

# Delivery fee (PRD §3.5)
GROUND_FEE_CENTS = 8500
ROOFTOP_FEE_CENTS = 22500
CRANE_FEE_CENTS = 60000
HEAVY_LOAD_BUNDLE_THRESHOLD = 40
PER_BUNDLE_SURCHARGE_CENTS = 350

# Return credit (PRD §3.8)
OPENED_CREDIT_PCT = 50
RESTOCKING_FEE_PER_BUNDLE_CENTS = 900

# Surge allocation waterfall tier caps (PRD §3.6)
TIER_CAP_PCT = {"VOLUME": 50, "PREFERRED": 35, "STANDARD": 25}

# Logical clock (PRD §2.4): server-startup default instant
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Takeoff aging (PRD §3.3)
DRAFT_EXPIRY_DAYS = 30
QUOTED_EXPIRY_DAYS = 14

# Lien cure period (PRD §3.7)
LIEN_CURE_PERIOD_DAYS = 10

TEST_DEFAULTS = {
    "BRANCH_CODE": "BR-T1",
    "BRANCH_NAME": "Test Branch",
    "ROOFTOP_CAPACITY_PER_DAY": 4,
    "CONVEYOR_FLEET_SIZE": 2,
    "SKU": "SH-T1",
    "MANUFACTURER": "Acme",
    "COLOR_CODE": "BLK",
    "BUNDLES_PER_SQUARE": 3.0,
    "BASE_PRICE_PER_BUNDLE_CENTS": 2000,
    "ON_HAND_BUNDLES": 500,
    "LOT_CODE": "LOT-1",
    "COMPANY_NAME": "Test Roofing Co",
    "CREDIT_LIMIT_CENTS": 10_000_000,
    "JOB_NAME": "Test Job",
    "SITE_ADDRESS": "1 Oak St",
    "SLOT_DATE": "2026-08-12",
    "SLOT_CAPACITY": 2,
}
