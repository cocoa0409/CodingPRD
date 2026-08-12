"""Domain thresholds and numeric constants from PRD §2.6, §3."""

# Dealer network price-level multipliers (PRD §3.2 / §3.8).
PRICE_LEVEL_MULTIPLIERS = {
    "L1": 0.60,
    "L2": 0.65,
    "L3": 0.70,
    "L4": 0.75,
    "L5": 0.80,
}

# Volume-discount tier thresholds in cents (PRD §3.2 / §3.9).
TIER1_MIN_CENTS = 5_000_000       # $50,000.00 -> 5%
TIER2_MIN_CENTS = 10_000_000      # $100,000.00 -> 8%
TIER1_RATE = 0.05
TIER2_RATE = 0.08

# Modification surcharge rule (PRD §3.3).
MOD_BASE_FEE_CENTS = {
    "REDUCED_DEPTH": 2500,
    "INCREASED_DEPTH": 4000,
    "REDUCED_WIDTH": 2500,
    "INCREASED_WIDTH": 4000,
    "TOE_KICK_NOTCH": 5500,
    "CUSTOM_BORE": 3000,
}
MOD_TIER_HIGH_DELTA_IN = 6        # >= 6in delta -> 15%
MOD_TIER_MID_DELTA_IN = 3         # >= 3in delta -> 10%; below -> 5%
MOD_MAX_PCT_OF_LINE_LIST = 0.40

# Nesting yield (PRD §3.5).
WASTE_PCT = 0.12

# Order cube (PRD §3.2).
CUBIC_IN_PER_CU_FT = 1728

# Freight consolidation (PRD §3.9).
FREIGHT_FLAT_MIN_CENTS = 8500
FREIGHT_RATE_PER_CU_FT_CENTS = 450
CONS_TIER1_COUNT = 3              # >= 3 orders -> 10% off
CONS_TIER2_COUNT = 5              # >= 5 orders -> 15% off
CONS_TIER1_PCT = 0.10
CONS_TIER2_PCT = 0.15

# Replacement-claim credit (PRD §3.8).
CLAIM_PROVISIONAL_PCT = 0.50
CLAIM_DEALER_ERROR_CHARGE_PCT = 0.60
FREIGHT_WINDOW_DAYS = 90
DEFECT_WINDOW_DAYS = 365

# Logical clock (PRD §2.6).
LOGICAL_CLOCK_DEFAULT = "2026-05-01T00:00:00Z"
DEFAULT_SCHEDULE_DATE = "2026-05-02"
DEFAULT_ROUTE_DATE = "2026-05-04"

# Common test defaults.
TEST_DEFAULTS = {
    "DEALER_CREDIT_CENTS": 100_000_000,
    "BOX_UNIT_PRICE_CENTS": 50_000,
    "DOOR_UNIT_PRICE_CENTS": 30_000,
    "SHEET_WIDTH_IN": 96,
    "SHEET_HEIGHT_IN": 48,
    "DEFAULT_TOLERANCE": 1.5,
    "BATCH_CAPACITY_DOORS": 10,
    "ROUTE_CAPACITY_CU_FT": 500.0,
    "LINE_CAPACITY_MINUTES": 2000,
    "MINUTES_PER_BOX": 30,
    "SETUP_MINUTES_PER_SUB_LOT": 20,
}
