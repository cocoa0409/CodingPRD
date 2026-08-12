"""Domain thresholds — numeric constants named in the PRD's business rules."""

# Logical clock
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"  # server default before any clock-set

# Press batches
PRESS_WINDOW_MIN_MINUTES = 30
PRESS_WINDOW_MAX_MINUTES = 480
LITERS_PER_LB_THEORETICAL = 0.5   # half a liter of juice per pound of fruit
YIELD_LOW = 0.55                  # below this flags YIELD_ANOMALY
YIELD_HIGH = 0.85                 # above this flags YIELD_ANOMALY

# Fermentation / packaging
ABV_PER_BRIX_DROP = 0.55          # abv_pct = gravity drop * 0.55
AGING_MIN_DAYS = 14               # AGING -> READY minimum
CIDER_TAX_CLASS_MAX_ABV = 8.5     # products cannot activate above this
CIDER_TAX_CLASS_MIN_ABV = 0.5     # strictly greater than this
DEFAULT_ABV_TOLERANCE_PCT = 0.3

# Excise
FEDERAL_CIDER_RATE_CENTS_PER_LITER = 22.6

# Container sizes in liters (fixed by PRD section 3.5)
UNIT_LITERS = {
    "CAN_12OZ": 0.355,
    "CAN_16OZ": 0.473,
    "BOTTLE_500ML": 0.500,
    "BOTTLE_750ML": 0.750,
    "KEG_5GAL": 18.927,
    "KEG_15_5GAL": 58.674,
}

# Shortfall penalty tiers (PRD section 3.1)
FREE_ALLOWANCE_PCT = 0.10
TIER1_PCT = 0.20
TIER2_MULTIPLIER = 2

# Sales
RETURN_WINDOW_DAYS = 30

TEST_DEFAULTS = {
    "SEASON_YEAR": 2026,
    "REGION_CODE": "NY",
    "PRICE_PER_LB_CENTS": 85,
}
