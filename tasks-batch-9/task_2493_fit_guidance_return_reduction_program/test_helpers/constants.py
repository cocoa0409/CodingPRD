"""Domain thresholds and rate tables stated in the PRD's calculations.

Money is whole cents, lengths whole millimetres, and every rate, weight, share
and tolerance percentage is an integer basis point where 10,000 basis points is
one whole.
"""

# ---------------------------------------------------------------------------
# The logical program clock (PRD 2.5)
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Specification verification (PRD 3.2)
# ---------------------------------------------------------------------------

MEASUREMENT_POINT_ORDER = ["CHEST", "WAIST", "HIP", "INSEAM"]

TOLERANCE_CEILING_MM = {
    "CHEST": 25,
    "WAIST": 25,
    "HIP": 25,
    "INSEAM": 20,
}

STRETCH_MULTIPLIER_PCT = {
    "RIGID": 100,
    "STRETCH": 150,
    "HIGH_STRETCH": 200,
}

MAX_CORRECTION_ROUNDS = 3
CORRECTION_COST_CENTS = 2500

# ---------------------------------------------------------------------------
# Mapping coverage (PRD 3.3, 3.4)
# ---------------------------------------------------------------------------

MIN_COVERAGE_BP = 8000
MIN_DETAIL_IMAGE_COUNT = 3

# ---------------------------------------------------------------------------
# Restocking fee tiers (PRD 3.8)
# ---------------------------------------------------------------------------

RESTOCK_TIER_1_CENTS = 5000
RESTOCK_TIER_2_CENTS = 20000
RESTOCK_TIER_0_BP = 0
RESTOCK_TIER_1_BP = 1000
RESTOCK_TIER_2_BP = 1500
ABUSE_FEE_MULTIPLIER_BP = 15000
NEUTRAL_FEE_MULTIPLIER_BP = 10000

# ---------------------------------------------------------------------------
# Return cost ledger components (PRD 3.8)
# ---------------------------------------------------------------------------

FREIGHT_INBOUND_CENTS = {
    "TOPS": 795,
    "BOTTOMS": 895,
    "DRESSES": 995,
    "OUTERWEAR": 1495,
    "FOOTWEAR": 1295,
}

LABOR_RATE_CENTS_PER_MIN = 62

HANDLING_MINUTES = {
    "FIT": 9,
    "QUALITY": 17,
    "EXPECTATION": 11,
    "CHANGE_OF_MIND": 7,
}

REFURB_PCT_BP = {
    "RESELLABLE_A": 150,
    "RESELLABLE_B": 400,
    "SALVAGE": 0,
}

MARKDOWN_PCT_BP = {
    "RESELLABLE_A": 0,
    "RESELLABLE_B": 1200,
    "SALVAGE": 6500,
}

PAYMENT_FEE_BP = 290
VENDOR_CHARGEBACK_PCT_BP = 4000

COST_COMPONENT_ORDER = [
    "FREIGHT_INBOUND",
    "PROCESSING_LABOR",
    "REFURB_REPACK",
    "MARKDOWN_LOSS",
    "PAYMENT_FEE_UNRECOVERED",
    "VENDOR_CHARGEBACK_CREDIT",
]

DENIED_COST_COMPONENT_ORDER = ["FREIGHT_INBOUND", "PROCESSING_LABOR"]

# ---------------------------------------------------------------------------
# The chronic-return score (PRD 3.8)
# ---------------------------------------------------------------------------

FIT_WEIGHT_BP = 7500
EXPECTATION_WEIGHT_BP = 2500
WATCH_THRESHOLD_BP = 1500
CHRONIC_THRESHOLD_BP = 2500
MIN_FIT_RETURNS_WATCH = 1
MIN_FIT_RETURNS_CHRONIC = 2

# ---------------------------------------------------------------------------
# Fit recommendation (PRD 3.5, 3.6)
# ---------------------------------------------------------------------------

PERSONAL_SAMPLE_FLOOR = 3
CONFIDENCE_FLOOR_BP = 6000

VERDICT_OFFSET_CENTI = {
    "TOO_SMALL": 100,
    "SLIGHTLY_SMALL": 50,
    "TRUE_TO_SIZE": 0,
    "SLIGHTLY_LARGE": -50,
    "TOO_LARGE": -100,
}

FIT_RETURN_OFFSET_CENTI = {
    "FIT_TOO_SMALL": 100,
    "FIT_TOO_LARGE": -100,
}

FIT_RETURN_SIGNAL_WEIGHT = 200
PURCHASER_SIGNAL_WEIGHT = 200
NON_PURCHASER_SIGNAL_WEIGHT = 100

HISTORY_CONFIDENCE_CAP = 9500
HISTORY_CONFIDENCE_BASE = 4500
HISTORY_CONFIDENCE_STEP = 1000
POPULATION_CONFIDENCE_CAP = 8000
POPULATION_CONFIDENCE_BASE = 2000
POPULATION_CONFIDENCE_STEP = 500

# ---------------------------------------------------------------------------
# Shopper standing (PRD 3.7, 3.8)
# ---------------------------------------------------------------------------

ABUSE_WINDOW_DAYS = 180
ABUSE_WATCH_STRIKES = 1
ABUSE_RESTRICTED_STRIKES = 2
ABUSE_BLOCKED_STRIKES = 3
ABUSE_RATE_BLOCK_BP = 7000
ABUSE_RATE_MIN_LINES = 4

POLICY_CLASS_DELTA_DAYS = {
    "STANDARD_WINDOW": 0,
    "EXTENDED_WINDOW": 30,
    "RESTRICTED_WINDOW": -15,
}

MIN_EFFECTIVE_WINDOW_DAYS = 7

# ---------------------------------------------------------------------------
# Deployment measurement and savings (PRD 3.9)
# ---------------------------------------------------------------------------

SAVED_COST_PER_AVOIDED_RETURN_CENTS = {
    "TOPS": 3200,
    "BOTTOMS": 3600,
    "DRESSES": 4200,
    "OUTERWEAR": 5200,
    "FOOTWEAR": 4400,
}

FUNDING_TOLERANCE_CENTS = 5000

# ---------------------------------------------------------------------------
# Vendor standing (PRD 2.11)
# ---------------------------------------------------------------------------

INITIAL_RELIABILITY_BP = 10000
QUALITY_CHARGEBACK_PENALTY_BP = 500
CORRECTION_ROUND_PENALTY_BP = 300
VENDOR_PROBATION_BP = 7000
VENDOR_SUSPEND_BP = 5000

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
MIN_OFFSET = 0

# ---------------------------------------------------------------------------
# Convenient defaults for building test scenarios
# ---------------------------------------------------------------------------

TEST_DEFAULTS = {
    "VENDOR_NAME": "Northwind Apparel",
    "BRAND_CODE": "NRTH",
    "CORRECTION_BUDGET_CENTS": 250000,
    "SKU": "NRTH-TEE-01",
    "CATEGORY_CODE": "TOPS",
    "SIZE_SYSTEM": "US_ALPHA",
    "UNIT_PRICE_CENTS": 2295,
    "CHART_CODE": "STD-TOPS-X1",
    "WINDOW_DAYS": 30,
    "POLICY_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "DELIVERED_AT": "2026-05-20T00:00:00Z",
    "CLOCK": "2026-06-01T00:00:00Z",
}
