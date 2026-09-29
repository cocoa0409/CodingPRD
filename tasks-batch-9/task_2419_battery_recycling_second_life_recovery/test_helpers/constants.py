"""Domain thresholds and pinned test values quoted from the PRD narratives."""

# ---------------------------------------------------------------- the clock
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00.000Z"
# Pinned instants used by the composite scenarios below.
CLOCK_INTAKE = "2026-07-10T00:00:00.000Z"
CLOCK_PROCESS = "2026-08-20T00:00:00.000Z"

# ------------------------------------------------------- custody / packaging
SOC_PACKAGING_LIMIT_PCT = 30.0

# ----------------------------------------------------------- triage scoring
CYCLES_PER_POINT = 200
CYCLE_PENALTY_CAP_POINTS = 20.0
IMBALANCE_WEIGHT = 0.80
GRADE_A_FLOOR = 80.0
GRADE_B_FLOOR = 70.0
GRADE_C_FLOOR = 60.0

GRADE_TO_DERIVED_DISPOSITION = {
    "A": "REFURBISH",
    "B": "SECOND_LIFE",
    "C": "SECOND_LIFE",
    "D": "MATERIAL_RECOVERY",
}
DISPOSITION_TO_MODULE_STATUS = {
    "REFURBISH": "REFURB_QUEUE",
    "SECOND_LIFE": "SECOND_LIFE_QUEUE",
    "MATERIAL_RECOVERY": "RECOVERY_QUEUE",
}

# --------------------------------------------------------- quality deduction
MISLABEL_PENALTY_PCT = 0.04
MOISTURE_FREE_PP = 2.0
MOISTURE_RATE_PER_PP = 0.01
MOISTURE_COMPONENT_CAP = 0.06
FOREIGN_FREE_PP = 1.5
FOREIGN_RATE_PER_PP = 0.02
FOREIGN_COMPONENT_CAP = 0.05
STRIKE_ESCALATION_THRESHOLD = 3
REPEAT_OFFENDER_MULTIPLIER = 1.5
TOTAL_DEDUCTION_CAP = 0.20

# ------------------------------------------------------------ feedstock price
PAYABLE_METALS = ["NI", "CO", "LI", "CU"]
NON_PAYABLE_METALS = ["MN", "GRAPHITE"]
RECOVERABLE_METALS = ["NI", "CO", "LI", "CU", "MN", "GRAPHITE"]
HYDROMET_ONLY_METALS = ["NI", "CO", "LI"]

PAYABLE_SHARE = {"NI": 0.70, "CO": 0.70, "LI": 0.55, "CU": 0.40}
NOMINAL_RECOVERY = {
    "NMC622": {"NI": 0.95, "CO": 0.95, "LI": 0.80, "CU": 0.90},
    "NCA": {"NI": 0.95, "CO": 0.90, "LI": 0.80, "CU": 0.90},
    "LMO": {"NI": 0.0, "CO": 0.0, "LI": 0.75, "CU": 0.90},
    "LFP": {"NI": 0.0, "CO": 0.0, "LI": 0.75, "CU": 0.90},
}

CHEMISTRY_FAMILY_MAP = {
    "NMC622": "NICKEL_RICH",
    "NCA": "NICKEL_RICH",
    "LMO": "NICKEL_RICH",
    "LFP": "IRON_PHOSPHATE",
}

# ------------------------------------------------------------- the waterfall
PROCESSING_FEE_TIERS = [
    {"upper_exclusive_cents": 500_000, "pct": 0.12},
    {"upper_exclusive_cents": 2_000_000, "pct": 0.09},
    {"upper_exclusive_cents": None, "pct": 0.06},
]
HAZMAT_FLAT_CENTS = 2_500
HAZMAT_PER_KG_CENTS = 6
HAZMAT_CAP_PCT = 0.05

# ------------------------------------------------- lot balance / certification
MASS_BALANCE_FLOOR_PCT = 97.00
PASSPORT_MIN_CONTENT_PCT = 35.00

# ---------------------------------------------------------- assay variance
DISPUTE_TOLERANCE_PP = 0.50
SEVERE_VARIANCE_PP = 2.00
DISPUTE_ROUND_LIMIT = 3

# ------------------------------------------------------ campaign occupation
DEFAULT_CHANGEOVER_BUFFER_HOURS = 6

# ----------------------------------------------------- capacity projection
LOOKBACK_DAYS = 30
GROWTH_RATE_PER_DAY = 0.004

# ------------------------------------------------------------- pagination
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ------------------------------------------------- pinned test-world values
TEST_DEFAULTS = {
    "FACILITY_NAME": "Reno Campus",
    "STATE_CODE": "NV",
    "MECH_CAPACITY_KG_PER_DAY": 3000.0,
    "HYDRO_CAPACITY_KG_PER_DAY": 2000.0,
    "SUPPLIER_LEGAL_NAME": "Northstar Automotive",
    "SUPPLIER_CHANNEL": "AUTOMAKER",
    "CREDIT_LIMIT_CENTS": 200_000,
    "DECLARED_CHEMISTRY": "NMC622",
    "IDENTIFIED_CHEMISTRY": "NMC622",
    "GROSS_MASS_KG": 110.0,
    "PACKAGING_TARE_KG": 10.0,
    "DECLARED_NI_PCT": 12.0,
    "SOC_PCT": 12.0,
    "PACKAGING_TYPE": "UN4G-STEEL-DRUM",
    "UN_NUMBER": "UN3480",
    "PACKING_GROUP": "II",
    "TRANSPORTER_NAME": "Sierra Hazmat Lines",
    "LINE_CODE": "HYD-1",
    "LINE_TYPE": "HYDROMET",
    "CHEMISTRY_FAMILY": "NICKEL_RICH",
    "THROUGHPUT_KG_PER_HOUR": 60.0,
    "CAMPAIGN_WINDOW_START": "2026-08-01T00:00:00.000Z",
    "CAMPAIGN_WINDOW_END": "2026-09-30T00:00:00.000Z",
    "PLANNED_INPUT_KG": 5000.0,
    "LOT_CODE": "L-1",
    "MODULE_MASS_KG": 100.0,
    "MODULE_MIN_CELL_CAPACITY_PCT": 58.0,
    "MODULE_MEAN_CELL_CAPACITY_PCT": 62.0,
    "MODULE_CYCLE_COUNT": 1200,
    "PERMIT_MEDIUM": "WATER",
    "PERMIT_NO": "NV-W-118",
    "PERMIT_VALID_FROM": "2026-08-01T00:00:00.000Z",
    "PERMIT_VALID_TO": "2026-08-31T23:59:59.999Z",
    "DAILY_CAP_KG": 500.0,
    "ANALYTE": "FLUORIDE",
}

# Published quotes used as the default price feed: a nickel series with an
# older quote effective before the shipment's received_at and a newer one
# effective before the lot's finalized_at.
DEFAULT_QUOTES = [
    {"metal": "NI", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 1600},
    {"metal": "NI", "effective_date": "2026-08-15T00:00:00.000Z", "price_cents_per_kg": 1750},
]

# Four-metal feed for shipments declaring all four payable assays.
FOUR_METAL_QUOTES = [
    {"metal": "NI", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 1600},
    {"metal": "CO", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 3200},
    {"metal": "LI", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 8000},
    {"metal": "CU", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 850},
]

# Both curves of the four payable metals: a July series effective before the
# shipment's received_at and an August series effective before the lot's
# finalized_at, so the provisional and final variants read different prices.
EIGHT_METAL_QUOTES = [
    {"metal": "NI", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 1600},
    {"metal": "CO", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 3200},
    {"metal": "LI", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 8000},
    {"metal": "CU", "effective_date": "2026-07-01T00:00:00.000Z", "price_cents_per_kg": 850},
    {"metal": "NI", "effective_date": "2026-08-15T00:00:00.000Z", "price_cents_per_kg": 1750},
    {"metal": "CO", "effective_date": "2026-08-15T00:00:00.000Z", "price_cents_per_kg": 3000},
    {"metal": "LI", "effective_date": "2026-08-15T00:00:00.000Z", "price_cents_per_kg": 9000},
    {"metal": "CU", "effective_date": "2026-08-15T00:00:00.000Z", "price_cents_per_kg": 900},
]

# Opaque operator identifiers used where the PRD compares X-User-ID values.
CO_SUBMITTER_USER_ID = "co-submitter-1"
CO_CLOSER_USER_ID = "co-closer-2"
CO_THIRD_USER_ID = "co-closer-3"
CO_INSPECTOR_USER_ID = "co-inspector-3"
TRIAGE_ENGINEER_USER_ID = "te-1"
PLANT_OPERATOR_USER_ID = "po-1"
ASSAY_TECHNICIAN_USER_ID = "at-1"
SETTLEMENT_ACCOUNTANT_USER_ID = "sa-1"
