"""Domain thresholds — numeric constants named in the PRD (§3 narratives)."""

# Pricing engine (§3.7)
MIN_LIST_PRICE_CENTS = 100          # minimum list price clamp of one dollar
HAZMAT_HANDLING_MULT = 1.15         # hazardous-handling factor
CONDITION_MULTIPLIERS = {"A": 1.00, "B": 0.75, "C": 0.50, "D": 0.25}

# Guidance valuation (§3.2)
THRIFT_VALUE_PCT = 0.30

# Receipt final valuation (§3.3)
APPRAISAL_THRESHOLD_CENTS = 500000  # $5,000, inclusive

# Donor recognition tiers (§3.1), inclusive >=
SUPPORTER_VALUE_CENTS = 50000       # $500
BUILDER_VALUE_CENTS = 250000        # $2,500
CORNERSTONE_VALUE_CENTS = 1000000   # $10,000

# Contractor discount tiers (§3.9), inclusive >=
SILVER_VOLUME_CENTS = 2500000       # $25,000
GOLD_VOLUME_CENTS = 10000000        # $100,000
SILVER_PCT = 0.05
GOLD_PCT = 0.10

# Sale totals (§3.9)
SALES_TAX_RATE = 0.07

# Fleet logistics (§3.5)
PICKUP_BUFFER_MINUTES = 60
PICKUP_FEE_CENTS = 5000             # flat $50

# Logical clock (§2.4)
CLOCK_START_ISO = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "CATEGORY_BASE_RATE_CENTS": 100,
    "ZONE_CAPACITY": 10,
    "VEHICLE_CAPACITY_LBS": 9000,
    "CREDIT_LIMIT_CENTS": 100000000,
}
