"""Domain thresholds and pinned constants from the PRD business rules."""

# Pricing compliance (PRD section 3.3 / 3.4)
MAX_DISCOUNT_PCT = 55

# Order total rollup (PRD section 3.4): fee band selected by total_list_cents
VOLUME_FEE_BAND_CENTS = 5_000_000      # fifty thousand dollars
FEE_PCT_HIGH_VOLUME = 8
FEE_PCT_DEFAULT = 12

# Dealership creation defaults (PRD section 3.1)
DEFAULT_AFTER_HOURS_START_MINUTE = 1080   # 18:00
DEFAULT_AFTER_HOURS_MULTIPLIER_BP = 15000  # 1.5x
DEFAULT_TURNOVER_BUFFER_MINUTES = 30
DEFAULT_CREDIT_CAP_PCT = 25

# Restocking fee on cancel from ACKNOWLEDGED (PRD section 3.6)
RESTOCK_PCT = 20
MIN_RESTOCK_FEE_CENTS = 25_000           # two hundred fifty dollars

# Liquidation valuation (PRD section 3.9)
EST_VALUE_PER_ITEM_CENTS = {"A": 120_000, "B": 75_000, "C": 30_000}
ESTIMATION_ASSUMED_GRADE = "B"
ESTIMATION_HAIRCUT_PCT = 20
LIQUIDATION_FEE_PCT = 15
REFURB_FEE_PER_ITEM_CENTS = {"A": 5_000, "B": 15_000, "C": 25_000}
APPRAISAL_VALIDITY_DAYS = 30

# Logical clock (PRD section 2.7)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Common fixture defaults
TEST_DEFAULTS = {
    "STAGING_CAPACITY_UNITS": 100,
    "STANDARD_LABOR_RATE_CENTS_PER_HOUR": 10_000,
    "DEFAULT_DISCOUNT_PCT": 30,
    "EFFECTIVE_FROM": "2026-08-01",
    "EFFECTIVE_TO": "2026-12-31",
    "BASE_LIST_PRICE_CENTS": 100_000,
    "BASE_LEAD_TIME_DAYS": 30,
    "TYPICAL_QUANTITY": 10,
    "TYPICAL_BUDGET_CENTS": 500_000,
}
