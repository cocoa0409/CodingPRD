"""Numeric constants declared by the PRD's engineering and commercial models.

Every value here is quoted from PRD §2 or §3; nothing is derived.
"""

# ─── Logical clock (PRD §2.4) ───────────────────────────────────────────
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# ─── Pagination (PRD §2.3) ──────────────────────────────────────────────
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
    "MIN_OFFSET": 0,
}

# ─── Airflow load model (PRD §3.2) ──────────────────────────────────────
INFILTRATION_COEFFICIENT = {"HT": 0.62, "MT": 0.78, "LT": 1.05}
CURTAIN_FACTOR_STEP = 0.12
CURTAIN_FACTOR_FLOOR = 0.55
REFERENCE_DISCHARGE_VELOCITY_MPS = 0.45
VELOCITY_FACTOR_SLOPE = 0.20
DEFROST_WATTS_PER_CYCLE_PER_SQFT = 3.5
HOURS_PER_DAY = 24
ANTI_SWEAT_W_PER_DOOR = {"HT": 0, "MT": 18, "LT": 42}
SELF_CONTAINED_REJECTION_FRACTION = 0.08

# ─── Refrigerant charge basis (PRD §3.2) ────────────────────────────────
GRAMS_PER_LINE_SET_FOOT = 26
GRAMS_PER_KILOGRAM = 1000

# ─── Energy test (PRD §3.3) ─────────────────────────────────────────────
AMBIENT_UPLIFT_PER_DEGREE_C = 0.035
MISSED_DEFROST_KWH = 0.28

# ─── Store plan pricing (PRD §3.6) ─────────────────────────────────────
BASE_RATE_CENTS_PER_FT = {"HT": 78000, "MT": 96000, "LT": 124000}
LENGTH_TIER_FACTOR = {4: 1.15, 6: 1.06, 8: 1.00, 12: 0.94}
OFFERED_LENGTHS_FT = [4, 6, 8, 12]
OPTION_ADDER_CENTS = {
    "LED_CANOPY": 42000,
    "NIGHT_CURTAIN": 28500,
    "GLASS_DOOR_UPGRADE": 165000,
    "SHELF_LIGHTING": 51500,
    "DIGITAL_PRICE_RAIL": 73500,
}
END_CAP_ADDER_CENTS_PER_SIDE = 87000
END_CAP_SIDES = {"NONE": 0, "LEFT": 1, "RIGHT": 1, "BOTH": 2}
SYSTEM_ADDER_CENTS = {"REMOTE": 118000, "SELF_CONTAINED": 320000}

# Volume discount tiers: (strict upper bound on subtotal_cents, basis points).
VOLUME_DISCOUNT_TIERS = [
    (5000000, 0),
    (10000000, 300),
    (20000000, 550),
]
VOLUME_DISCOUNT_TOP_BPS = 800
BPS_DIVISOR = 10000

FREIGHT_CENTS_PER_LINEAR_FOOT = 9500
FREIGHT_CAP_FRACTION_OF_NET = 0.04
INSTALL_ALLOWANCE_FRACTION_OF_NET = 0.025

# ─── Production (PRD §3.7) ──────────────────────────────────────────────
REWORK_LIMIT = 2
WARRANTY_ACCRUAL_BPS = 275

# ─── Warranty (PRD §3.9) ────────────────────────────────────────────────
WARRANTY_TERM_MONTHS = {
    "COMPRESSOR_FAILURE": 60,
    "DOOR_GASKET": 12,
    "CONTROLLER": 12,
    "GLASS_FOG": 12,
}
INCURRED_ESTIMATE_FRACTION = 0.60

# ─── Values reused across test setups ──────────────────────────────────
TEST_DEFAULTS = {
    "REFRIGERANT_CODE": "R-448A",
    "REFRIGERANT_TRADE_NAME": "Solstice N40",
    "REFRIGERANT_GWP": 1387,
    "LOW_GWP_REFRIGERANT_CODE": "R-454C",
    "LOW_GWP_TRADE_NAME": "Opteon XL20",
    "LOW_GWP": 146,
    "STANDARD_CODE": "DOE-2027-RSC-MT",
    "STANDARD_EFFECTIVE_DATE": "2026-01-01T00:00:00Z",
    "STANDARD_MAX_GWP": 1500,
    "STANDARD_COEFFICIENT_A": 0.62,
    "STANDARD_CONSTANT_B": 1.20,
    "CHAMBER_CODE": "CH-1",
    "CHAMBER_TURNAROUND_HOURS": 12,
    "CHAMBER_MAX_TDA_SQFT": 80.0,
    "MODEL_CODE": "MDL-MT-8",
    "MODEL_TDA_SQFT": 26.4,
    "MODEL_CHARGE_GRAMS": 4200,
    "MODEL_LINE_SET_LENGTH_FT": 120,
    "WINDOW_START": "2026-08-03T08:00:00Z",
    "WINDOW_END": "2026-08-04T08:00:00Z",
    "TEST_AMBIENT_C": 24.0,
    "STORE_AMBIENT_C": 27.0,
    "MEASURED_KWH_24H": 15.0,
    "MEASURED_DEFROST_CYCLES": 4,
    "LABEL_CODE": "LBL-MT-8-A",
    "BANNER_NAME": "FreshMart",
    "STORE_NUMBER": "0412",
    "REGION_CODE": "OH",
    "REMODEL_WINDOW_START": "2026-09-14",
    "REMODEL_WINDOW_END": "2026-09-27",
    "CREDIT_LIMIT_CENTS": 20000000,
    "CARRIER_CODE": "RLC",
    "SHIP_DATE": "2026-09-15",
    "DELIVERY_DATE": "2026-09-17",
    "CREW_CODE": "CRW-OH-1",
    "CONTRACTOR_NAME": "Buckeye Refrigeration",
    "DAILY_CASE_CAPACITY": 6,
    "BOOKING_START_DATE": "2026-09-17",
    "BOOKING_END_DATE": "2026-09-19",
    "HANDOFF_INSTANT": "2026-09-17T14:00:00Z",
}
