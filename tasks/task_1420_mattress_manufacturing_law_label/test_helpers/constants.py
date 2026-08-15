"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD §2.5): the server never uses wall-clock time.
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

# Cure eligibility (PRD §3.5)
BASE_CURE_HOURS = {"STANDARD": 24, "HIGH_DENSITY": 48, "MEMORY": 72}
COOL_TIER_MAX_C = 18          # ambient_temp_c below this adds COOL_ADJUST_HOURS
WARM_TIER_MIN_C = 27          # ambient_temp_c above this subtracts 6h (27 itself is NORMAL)
COOL_ADJUST_HOURS = 12
WARM_ADJUST_HOURS = -6
RECURE_PENALTY_HOURS = 12
CHAMBER_CAPACITY = 3          # max concurrent CURING batches per chamber

# Order compliance fee tiers (PRD §3.7), keyed on subtotal before the fee is added
FEE_TIER1_MAX_CENTS = 100000   # subtotal < 100000 -> 500
FEE_TIER2_MAX_CENTS = 500000   # 100000 <= subtotal < 500000 -> 1500; else 3000
FEE_TIER1_CENTS = 500
FEE_TIER2_CENTS = 1500
FEE_TIER3_CENTS = 3000

# Warranty credit (PRD §3.9)
FULL_REPLACEMENT_MONTHS = 12   # age_months <= 12 -> FULL_REPLACEMENT
WARRANTY_TERM_MONTHS = 120
MIN_CREDIT_PCT = 0.10
SAG_THRESHOLD_INCHES = 1.5     # SAG_DEFECT boundary, inclusive

# Returns (PRD §3.9)
COMFORT_WINDOW_DAYS = 100

# Recycling credit (PRD §3.9)
PROVISIONAL_RATE_CENTS_PER_KG = 20
RATE_STEEL_CENTS_PER_KG = 25
RATE_FOAM_CENTS_PER_KG = 40
RATE_FIBER_CENTS_PER_KG = 15
RATE_WOOD_CENTS_PER_KG = 5

# Common test defaults
TEST_DEFAULTS = {
    "CREDIT_LIMIT_CENTS": 100000000,
    "UNIT_PRICE_CENTS": 200000,
    "FOAM_POURED_KG": 1000.0,
    "CERT_ISSUED_ON": "2026-01-01T00:00:00Z",
    "CERT_EXPIRES_ON": "2030-01-01T00:00:00Z",
    "CURE_CERTIFY_CLOCK": "2026-08-02T00:00:00Z",
    "STATUTORY_PHRASE": "UNDER PENALTY OF LAW THIS TAG NOT TO BE REMOVED",
    "FILLING_CODE": "PU_FOAM_62",
}
