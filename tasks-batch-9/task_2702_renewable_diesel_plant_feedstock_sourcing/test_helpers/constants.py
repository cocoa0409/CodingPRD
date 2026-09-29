"""Numeric constants and rounding helpers taken from the specification.

Every literal here is quoted in the specification text; tests use them to make
expected values self-documenting rather than to re-derive the implementation.
"""

from decimal import ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00.000Z"
CLOCK_DEFAULT_SHORT = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Supplier due diligence
# ---------------------------------------------------------------------------
DD_MONTH_DAYS = 30
DD_MIN_DOC_TYPES_ORDINARY = 2
DD_MIN_DOC_TYPES_HIGH_RISK = 3
LEGAL_NAME_MAX = 120
DOC_HASH_MIN = 8
DOC_HASH_MAX = 128

# ---------------------------------------------------------------------------
# Feedstock lots and pretreatment
# ---------------------------------------------------------------------------
LOT_MASS_MAX_MT = 20000
LOT_CI_MAX = 120
LOT_PRICE_MAX = 5000

FFA_SUBTIER_2 = 5.00
FFA_SUBTIER_1 = 2.00
MOISTURE_SUBTIER_2 = 1.00
MOISTURE_SUBTIER_1 = 0.50
INSOLUBLES_SUBTIER_2 = 1500
INSOLUBLES_SUBTIER_1 = 500
PHOSPHORUS_SUBTIER_2 = 20
PHOSPHORUS_SUBTIER_1 = 10

FFA_REJECT_ABOVE = 15.00
MOISTURE_REJECT_ABOVE = 3.00
INSOLUBLES_REJECT_ABOVE = 5000
PHOSPHORUS_REJECT_ABOVE = 500

WASTE_PHOSPHORUS_ESCALATION_PPM = 10

BASE_FEE_PER_MT = {"NONE": 0.00, "LIGHT": 18.50, "HEAVY": 42.75}
TYPE_MULT = {
    "UCO": 1.20,
    "TALLOW": 1.35,
    "DCO": 1.10,
    "SOYBEAN_OIL": 1.00,
    "CANOLA_OIL": 1.00,
}
FEE_FLOOR_USD = 250.00
FEE_CAP_USD = 45000.00

PRETREAT_CI_ADDER = {"NONE": 0.00, "LIGHT": 1.50, "HEAVY": 4.00}

# ---------------------------------------------------------------------------
# Hydrotreating units, catalyst charges, turnarounds
# ---------------------------------------------------------------------------
UNIT_NAME_MAX = 40
NAMEPLATE_MAX_MT_PER_DAY = 6000
MAX_SAF_SHARE_CEILING_PCT = 60
DESIGN_THROUGHPUT_MAX_MT = 2000000
TURNAROUND_BUFFER_HOURS = 72

DECAY_PER_KMT = 0.0125
ACTIVITY_FLOOR = 0.6000

# ---------------------------------------------------------------------------
# Hydrogen
# ---------------------------------------------------------------------------
DAILY_CAPACITY_MAX_KG = 500000
H2_PRICE_MAX = 50
H2_CI_MAX = 200
H2_KG_PER_MT = {
    "UCO": 32.0,
    "TALLOW": 30.0,
    "DCO": 34.0,
    "SOYBEAN_OIL": 38.0,
    "CANOLA_OIL": 36.0,
}
SAF_SEVERITY_FACTOR = 0.12

# ---------------------------------------------------------------------------
# Campaigns / yields
# ---------------------------------------------------------------------------
MIN_CHARGE_MT = 100.0
YIELD_MASS_PCT = {
    "UCO": 82.0,
    "TALLOW": 80.0,
    "DCO": 83.0,
    "SOYBEAN_OIL": 85.0,
    "CANOLA_OIL": 84.0,
}
SAF_CONVERSION_PENALTY = 0.94
YIELD_VARIANCE_TOLERANCE_PCT = 2.000
FREIGHT_PCT = 0.035

# ---------------------------------------------------------------------------
# Product batches
# ---------------------------------------------------------------------------
GAL_PER_MT = {"RENEWABLE_DIESEL": 308.0, "SAF": 322.0}
SAF_FREEZE_POINT_MAX_C = -40.0
FREEZE_POINT_MIN_C = -80.0
FREEZE_POINT_MAX_C = 0.0

# ---------------------------------------------------------------------------
# Pathways and credits
# ---------------------------------------------------------------------------
MAX_REVISION_ROUNDS = 3
PATHWAY_SUSPENSION_STRIKES = 2
VERIFICATION_VARIANCE_TOLERANCE = 0.05
PROCESS_CI_ADDER = 8.75
VERIFICATION_DISCOUNT = 0.98
RIN_EQUIVALENCE = {"RENEWABLE_DIESEL": 1.7, "SAF": 1.6}
RIN_INVALID_RATE_CAP = 0.1000
LCFS_BENCHMARK_CI = {"RENEWABLE_DIESEL": 88.50, "SAF": 89.37}
ENERGY_DENSITY_MJ_PER_GAL = {"RENEWABLE_DIESEL": 129.65, "SAF": 126.60}
EER = {"RENEWABLE_DIESEL": 1.00, "SAF": 1.00}

# ---------------------------------------------------------------------------
# Hedges
# ---------------------------------------------------------------------------
NOTIONAL_MAX_UNITS = 1000000
STRIKE_MAX_USD = 10000
BASE_MARGIN_PCT = {"FEEDSTOCK_SWAP": 0.08, "RIN_FORWARD": 0.12, "LCFS_FORWARD": 0.15}
VOL_ADDER_PCT = {"T1": 0.010, "T2": 0.025, "T3": 0.040}
TIER_T3_FLOOR_USD = 250000.00
TIER_T2_FLOOR_USD = 50000.00

# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def round_half_up(value, places: int) -> float:
    """Round half up to `places` decimal places, matching the pinned metrology."""
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))
