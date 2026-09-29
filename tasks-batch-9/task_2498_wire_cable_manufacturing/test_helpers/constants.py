"""Domain thresholds and pinned numeric constants from the PRD calculations.

Every value here is stated verbatim in PRD.md (§2.5 precision, §2.8 mass
conservation, §2.9 credit exposure, §3.1-§3.9 domain rules). The generic
``NON_EXISTENT_UUID`` helper comes from the framework; this module also defines
the v4-shaped sentinel id the PRD's reference-resolution rules are probed with.
"""

# --------------------------------------------------------------------------
# Logical clock (PRD §2.4 — the platform reads a settable logical UTC clock)
# --------------------------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"
CLOCK_EPOCH_DATE = "2026-08-01"

# A syntactically valid UUID v4 that matches no row of any type.
SENTINEL_UUID = "00000000-0000-4000-8000-000000000000"

# --------------------------------------------------------------------------
# Voltage / metal reference maps
# --------------------------------------------------------------------------
VOLTAGE_MAP = {
    "LV_600": 600,
    "MV_5KV": 5000,
    "MV_15KV": 15000,
    "MV_35KV": 35000,
}

BASE_METAL_PRICE = {
    "COPPER": 3.00,
    "ALUMINUM": 1.00,
}

# --------------------------------------------------------------------------
# Pricing (PRD §3.6 order quote, §3.9 invoicing)
# --------------------------------------------------------------------------
CUT_FEE_USD_PER_CUT = 12.50

SURCHARGE_TIER_1_CEILING = 5000
SURCHARGE_TIER_2_CEILING = 25000
SURCHARGE_RATE_TIER_1 = 0.020
SURCHARGE_RATE_TIER_2 = 0.015
SURCHARGE_RATE_TIER_3 = 0.010

FLOAT_WINDOW_DAYS = 5
FLOAT_MIN_QUOTES = 3

# --------------------------------------------------------------------------
# Reel deposit refund schedules (PRD §3.9)
# --------------------------------------------------------------------------
FLAT_FULL_DAYS = 90
FLAT_HALF_DAYS = 180
DECAY_PER_DAY = 0.004
DECAY_FLOOR_PCT = 0.30
REEL_CYCLE_LIMIT = 10

# --------------------------------------------------------------------------
# Electrical test limits (PRD §3.7)
# --------------------------------------------------------------------------
SPARK_MAX_FAULTS = 0

HIPOT_REQUIRED_KV = {
    "LV_600": 2.5,
    "MV_5KV": 15.0,
    "MV_15KV": 35.0,
    "MV_35KV": 70.0,
}

# The PRD states partial-discharge limits only for the three medium-voltage
# classes; LV_600 never requires the off-line test.
PD_LIMIT_PC = {
    "MV_5KV": 5.0,
    "MV_15KV": 5.0,
    "MV_35KV": 3.0,
}

# --------------------------------------------------------------------------
# Rod metal ledger (PRD §2.8, §3.2)
# --------------------------------------------------------------------------
SCRAP_ALERT_PCT = 10.0

# --------------------------------------------------------------------------
# Inventory repositioning (PRD §3.5) and metal volatility (PRD §3.1)
# --------------------------------------------------------------------------
VOLATILITY_WINDOW_QUOTES = 10
VOLATILITY_MIN_QUOTES = 3

DEMAND_LOW_THRESHOLD = 0.80
DEMAND_HIGH_THRESHOLD = 1.20
DEMAND_MULTIPLIER_LOW = 0.30
DEMAND_MULTIPLIER_MID = 1.00
DEMAND_MULTIPLIER_HIGH = 1.80

VOLATILITY_WEIGHT = 0.80
VOLATILITY_DAMPER_CAP = 0.40
FLOOR_FACTOR = 0.25
CEILING_FACTOR = 1.50

# --------------------------------------------------------------------------
# Compliance cadence and production limits
# --------------------------------------------------------------------------
INSPECTION_MIN_GAP_DAYS = 60
CAP_DAYS = 30
REWORK_LIMIT = 2
CHANGEOVER_BUFFER_MINUTES = 30

# --------------------------------------------------------------------------
# Pagination contract (PRD §2.3)
# --------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# --------------------------------------------------------------------------
# Canonical test-data defaults reused across fixtures
# --------------------------------------------------------------------------
TEST_DEFAULTS = {
    "COPPER_QUOTE_DATE": "2026-07-30",
    "COPPER_QUOTE_PRICE": 4.10,
    "CONVERSION_PRICE_USD_PER_KFT": 85.00,
    "ROD_WEIGHT_LBS": 20000.00,
    "ROD_PRICE_USD_PER_LB": 4.05,
    "ROD_HEAT_NUMBER": "H-77Q",
    "CREDIT_LIMIT_USD": 100000.00,
    "REEL_DEPOSIT_USD": 450.00,
    "REEL_CAPACITY_FT": 6000,
    "THHN_LBS_PER_KFT": 19.8,
    "CERT_FILE_NUMBER": "E12345",
}

# The marking string a released LV_600 THHN 12 AWG SKU composes (PRD §3.5).
THHN_12_CU_MARKING = "UL E12345 12AWG THHN 90C 600V"
