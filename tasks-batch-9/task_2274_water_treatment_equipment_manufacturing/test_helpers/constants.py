"""Pinned constants drawn from the Water Treatment Equipment Manufacturing PRD.

Every value here is quoted from the PRD text so tests never re-derive a
business number locally.
"""

# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

API_PREFIX = "/water-treatment"

# The PRD seeds the logical clock at this instant on server start.
CLOCK_SEED = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Pagination (PRD: limit defaults to 10, must be at least 1, may not exceed 100)
# ---------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Stage sizing
# ---------------------------------------------------------------------------

PEAK_ROLES = ("FILTRATION", "DISINFECTION")

STAGE_ORDER = ("BIOLOGICAL", "FILTRATION", "DESALINATION", "DISINFECTION")

OBJECTIVE_ROLE_MAP = {
    "TURBIDITY_NTU": "FILTRATION",
    "TOC_MG_L": "FILTRATION",
    "TDS_MG_L": "DESALINATION",
    "CHLORIDE_MG_L": "DESALINATION",
    "ECOLI_CFU_100ML": "DISINFECTION",
    "GIARDIA_LOG_REMOVAL": "DISINFECTION",
    "BOD5_MG_L": "BIOLOGICAL",
    "AMMONIA_N_MG_L": "BIOLOGICAL",
}

# ---------------------------------------------------------------------------
# Process train selection
# ---------------------------------------------------------------------------

LIFECYCLE_YEARS = 20
ENERGY_COST_CENTS_PER_KWH = 12
FOOTPRINT_PENALTY_CENTS_PER_SF = 45000

# ---------------------------------------------------------------------------
# Equipment package cost
# ---------------------------------------------------------------------------

MATERIAL_FACTOR_NOMINAL = 1.0
PRESSURE_UPLIFT_PCT_PER_100_PSIG = 0.03
ESCALATION_PCT_PER_MONTH = 0.0075
MAX_COST_VARIANCE_PCT = 0.15
CODE_STAMP_SURCHARGE_PCT = {
    "NONE": 0.0,
    "AWWA": 0.04,
    "NSF61": 0.06,
    "ASME_U": 0.115,
}

# ---------------------------------------------------------------------------
# Or-Equal compliance scoring
# ---------------------------------------------------------------------------

DEVIATION_WEIGHTS = {"MINOR": 2, "MODERATE": 6, "MAJOR": 15, "FUNDAMENTAL": 30}
DISPOSITION_MULTIPLIER = {
    "PENDING": 1.0,
    "REJECTED": 1.0,
    "ACCEPTED": 0.25,
    "WITHDRAWN": 0.0,
}
MIN_COMPLIANCE_SCORE = 70

# ---------------------------------------------------------------------------
# Bid evaluated price waterfall
# ---------------------------------------------------------------------------

OVERHEAD_PCT = 0.185
MIN_MARGIN_PCT = 0.08
BOND_RATE_TIERS = (
    (100000000, 0.0125),
    (500000000, 0.0100),
    (None, 0.0085),
)
CONTINGENCY_PCT_BY_POSTURE = {"ON_TRACK": 0.02, "AT_RISK": 0.05, "HELD": 0.09}

# ---------------------------------------------------------------------------
# Shop floor
# ---------------------------------------------------------------------------

MAX_PASS_PUNCHLIST_ITEMS = 3
DEFAULT_CHANGEOVER_BUFFER_MINUTES = 120

MECHANICAL_SEQUENCE = (
    "FRAME_SET",
    "PIPING_COMPLETE",
    "HYDROTEST_PASSED",
    "MECH_COMPLETE",
)
CONTROLS_SEQUENCE = (
    "PANEL_BUILD",
    "IO_CHECKED",
    "LOOP_TESTED",
    "CONTROLS_COMPLETE",
)

# ---------------------------------------------------------------------------
# Guarantee demonstration
# ---------------------------------------------------------------------------

GUARANTEE_MARGIN_PCT = 5.0
MAX_DEMO_ROUNDS = 2

# ---------------------------------------------------------------------------
# Liquidated damages
# ---------------------------------------------------------------------------

LD_RATE_PER_DAY = 0.0005
LD_CAP_PCT = 0.05

# ---------------------------------------------------------------------------
# Service reserve
# ---------------------------------------------------------------------------

CONSUMABLE_MARKUP_PCT = 0.22
FREIGHT_PCT = 0.065
MEMBRANE_WARRANTY_MONTHS = 60
WARRANTY_CREDIT_PCT_PER_MONTH_REMAINING = 0.01

# ---------------------------------------------------------------------------
# Deliverables gate
# ---------------------------------------------------------------------------

DELIVERABLE_TYPES = ("OM_MANUAL", "OPERATOR_TRAINING", "SPARE_PARTS_LIST")

# ---------------------------------------------------------------------------
# Reusable literals
# ---------------------------------------------------------------------------

UNKNOWN_ID = "00000000-0000-0000-0000-0000000000ff"
