"""Domain constants (scaffold section 1.3) — all money/mass values are Decimal."""
from decimal import Decimal as _D


def D(x):
    """Decimal from anything without binary-float contamination."""
    if isinstance(x, _D):
        return x
    return _D(str(x))


ROLES = [
    "PlantOperator",
    "FeedstockTrader",
    "QualityAnalyst",
    "ComplianceOfficer",
    "IndependentVerifier",
    "Supplier",
]

FEEDSTOCK_TYPES = ["UCO", "TALLOW", "DCO", "SOYBEAN_OIL", "CANOLA_OIL"]
WASTE_TYPES = {"UCO", "TALLOW", "DCO"}
DOC_TYPES = ["ORIGIN_ATTESTATION", "CHAIN_OF_CUSTODY", "MASS_BALANCE_STATEMENT", "THIRD_PARTY_AUDIT"]
TURNAROUND_SCOPES = ["CATALYST_CHANGE", "INSPECTION", "MAJOR"]
PROGRAMS = ["RFS", "LCFS"]
PRODUCT_TYPES = ["RENEWABLE_DIESEL", "SAF"]
ASTM_ANNEXES = ["A2_HEFA", "A5_HC_HEFA"]
INSTRUMENTS = ["FEEDSTOCK_SWAP", "RIN_FORWARD", "LCFS_FORWARD"]
VOL_TIERS = ["T1", "T2", "T3"]

# ---- pretreatment_tier_and_fee -------------------------------------------
BASE_FEE_PER_MT = {"NONE": D("0.00"), "LIGHT": D("18.50"), "HEAVY": D("42.75")}
TYPE_MULT = {
    "UCO": D("1.20"),
    "TALLOW": D("1.35"),
    "DCO": D("1.10"),
    "SOYBEAN_OIL": D("1.00"),
    "CANOLA_OIL": D("1.00"),
}
FEE_FLOOR_USD = D("250.00")
FEE_CAP_USD = D("45000.00")

# ---- blend_carbon_intensity ----------------------------------------------
PRETREAT_CI_ADDER = {"NONE": D("0.00"), "LIGHT": D("1.50"), "HEAVY": D("4.00")}

# ---- hydrogen_requirement -------------------------------------------------
H2_KG_PER_MT = {
    "UCO": D("32.0"),
    "TALLOW": D("30.0"),
    "DCO": D("34.0"),
    "SOYBEAN_OIL": D("38.0"),
    "CANOLA_OIL": D("36.0"),
}
SAF_SEVERITY_FACTOR = D("0.12")

# ---- catalyst_activity_decay ---------------------------------------------
DECAY_PER_KMT = D("0.0125")
ACTIVITY_FLOOR = D("0.6000")

# ---- run_yield_split ------------------------------------------------------
YIELD_MASS_PCT = {
    "UCO": D("82.0"),
    "TALLOW": D("80.0"),
    "DCO": D("83.0"),
    "SOYBEAN_OIL": D("85.0"),
    "CANOLA_OIL": D("84.0"),
}
SAF_CONVERSION_PENALTY = D("0.94")
YIELD_VARIANCE_TOLERANCE_PCT = D("2.000")
MIN_CHARGE_MT = D("100.0")

# ---- feedstock_settlement_cost -------------------------------------------
FREIGHT_PCT = D("0.035")

# ---- hedge_margin_requirement --------------------------------------------
BASE_MARGIN_PCT = {
    "FEEDSTOCK_SWAP": D("0.08"),
    "RIN_FORWARD": D("0.12"),
    "LCFS_FORWARD": D("0.15"),
}
VOL_ADDER_PCT = {"T1": D("0.010"), "T2": D("0.025"), "T3": D("0.040")}
TIER_T2_FLOOR_USD = D("50000.00")
TIER_T3_FLOOR_USD = D("250000.00")

# ---- product / credits ----------------------------------------------------
GAL_PER_MT = {"RENEWABLE_DIESEL": D("308.0"), "SAF": D("322.0")}
RIN_EQUIVALENCE = {"RENEWABLE_DIESEL": D("1.7"), "SAF": D("1.6")}
RIN_INVALID_RATE_CAP = D("0.1000")
LCFS_BENCHMARK_CI = {"RENEWABLE_DIESEL": D("88.50"), "SAF": D("89.37")}
ENERGY_DENSITY_MJ_PER_GAL = {"RENEWABLE_DIESEL": D("129.65"), "SAF": D("126.60")}
EER = {"RENEWABLE_DIESEL": D("1.00"), "SAF": D("1.00")}
PROCESS_CI_ADDER = D("8.75")
VERIFICATION_DISCOUNT = D("0.98")
VERIFICATION_VARIANCE_TOLERANCE = D("0.05")
PATHWAY_SUSPENSION_STRIKES = 2
MAX_REVISION_ROUNDS = 3

# ---- misc thresholds ------------------------------------------------------
SAF_MAX_FREEZE_POINT_C = D("-40.0")
TURNAROUND_BUFFER_HOURS = 72
DD_MONTH_DAYS = 30
