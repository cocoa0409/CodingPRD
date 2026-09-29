"""Every literal constant named by the PRD / scaffold.  Nothing business-facing
is hardcoded anywhere else."""
from decimal import Decimal as _D

# --- roles ------------------------------------------------------------------
ROLES = (
    "PlatformAdmin",
    "ProjectOperator",
    "DairyPartner",
    "PipelineScheduler",
    "CreditVerifier",
    "ProgramAdministrator",
    "FinanceController",
)

# --- logical clock ----------------------------------------------------------
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# --- pagination -------------------------------------------------------------
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# --- design_olr_limit -------------------------------------------------------
DESIGN_OLR = {"MESOPHILIC": _D("3.500"), "THERMOPHILIC": _D("4.500")}

# --- biological_stability_assessment ---------------------------------------
THERMAL_BAND_DELTA_C = _D("1.0")
THERMAL_CRITICAL_DELTA_C = _D("3.0")
THERMAL_BAND_MINUTES = 30
THERMAL_CRITICAL_MINUTES = 120
VFA_ALK_WARNING = _D("0.300")
VFA_ALK_SEVERE = _D("0.400")
OLR_SEVERE_MULTIPLE = _D("1.10")
STRESSED_POINTS = 2
INHIBITED_POINTS = 4

# --- gas_conditioning_yield ------------------------------------------------
CH4_HHV_BTU_PER_SCF = _D("1010.0")
CONDITIONING_CH4_SLIP = _D("0.020")

# --- pathway_ci_score -------------------------------------------------------
MJ_PER_MMBTU = _D("1055.06")
BMP_M3_CH4_PER_KG_VS = _D("0.21")
CH4_DENSITY_KG_PER_M3 = _D("0.6785")
GWP_CH4 = _D("25")
MCF = {
    "LAGOON": _D("0.75"),
    "SOLID_STORAGE": _D("0.30"),
    "DAILY_SPREAD": _D("0.10"),
}
TRANSPORT_G_PER_TONNE_KM = _D("95.0")
PROCESS_G_PER_MJ = _D("15.40")
AVOIDANCE_CREDIT_CAP_MULTIPLE = _D("20.0")
CI_FLOOR = _D("-400.00")

# --- credit_quantity --------------------------------------------------------
LCFS_BENCHMARK_CI = _D("79.50")
LCFS_EER = _D("0.90")
LCFS_CREDIT_PRICE_CENTS = _D("7450")
D3_RIN_PER_MMBTU = _D("11.727")
D3_RIN_PRICE_CENTS = _D("285")

# --- digestate_separation ---------------------------------------------------
CAKE_DRY_MATTER_FRACTION = _D("0.30")

# --- plant_available_nitrogen ----------------------------------------------
SOLIDS_N_KG_PER_TONNE = _D("5.20")
PAN_LAB_FACTOR = _D("0.55")
NH4_FRACTION = _D("0.62")
VOLATILIZATION_RETENTION = _D("0.75")
ORGANIC_MINERALIZATION = _D("0.35")

# --- net_distributable_waterfall -------------------------------------------
FEE_TIER_1_MAX_CENTS = 1000000
FEE_TIER_2_MAX_CENTS = 2500000
FEE_RATE_TIER_1 = _D("0.0800")
FEE_RATE_TIER_2 = _D("0.0650")
FEE_RATE_TIER_3 = _D("0.0500")
RESERVE_SWEEP_RATE = _D("0.2500")

# --- dscr_and_distribution_posture -----------------------------------------
MONTHS_PER_YEAR = _D("12")
DSCR_RESTRICTED_BAND = _D("0.150")
RESTRICTED_PAY_CAP_CENTS = 1000000

# --- interval rules ---------------------------------------------------------
REAPPLICATION_SETBACK_DAYS = 21

# --- audit_finding_severity ------------------------------------------------
MATERIAL_CI_TOLERANCE = _D("2.00")

# --- bounded loops ----------------------------------------------------------
MAX_NEGOTIATION_ROUNDS = 3
MAX_REMEDIATION_ROUNDS = 2
MAX_CONDITIONING_ATTEMPTS = 2
MAX_REOPENS = 1
CURTAILMENT_SUSPEND_THRESHOLD = 3
