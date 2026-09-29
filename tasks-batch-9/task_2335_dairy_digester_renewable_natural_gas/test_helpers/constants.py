"""Domain thresholds and numeric constants stated in the PRD.

Every value here is quoted from PRD prose (§2.5, §2.6, §2.8, §3.1 - §3.9).
"""

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.6)
# ---------------------------------------------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Facility design loading ceiling by thermal regime (PRD §3.1)
# ---------------------------------------------------------------------------
DESIGN_MAX_OLR_MESOPHILIC = 3.500
DESIGN_MAX_OLR_THERMOPHILIC = 4.500

# ---------------------------------------------------------------------------
# Feedstock delivery + loading rate (PRD §3.3)
# ---------------------------------------------------------------------------
OLR_KG_PER_TONNE = 1000  # volatile-solids tonnes -> kilograms

# ---------------------------------------------------------------------------
# Biological stability scoring (PRD §3.4)
# ---------------------------------------------------------------------------
THERMAL_CRITICAL_DEVIATION_C = 3.0
THERMAL_CRITICAL_MINUTES = 120
THERMAL_EXCURSION_DEVIATION_C = 1.0
THERMAL_EXCURSION_MINUTES = 30
VFA_ALKALINITY_SEVERE = 0.400
VFA_ALKALINITY_ELEVATED = 0.300
LOADING_SEVERE_MULTIPLIER = 1.10
STRESS_POINTS_INHIBITED = 4
STRESS_POINTS_STRESSED = 2

# ---------------------------------------------------------------------------
# Raw and pipeline gas energy (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------
METHANE_HHV_BTU_PER_SCF = 1010.0
CONDITIONING_SLIP_FRACTION = 0.020
BTU_PER_MMBTU = 1_000_000
MAX_CONDITIONING_ATTEMPTS = 2
OFFSPEC_SCREEN_ORDER = ("H2S", "MOISTURE", "CO2", "HHV")

# ---------------------------------------------------------------------------
# Injection nominations + curtailment (PRD §3.5, §3.6)
# ---------------------------------------------------------------------------
MINUTES_PER_HOUR = 60
CURTAILMENT_SUSPENSION_THRESHOLD = 3

# ---------------------------------------------------------------------------
# Digestate separation and nutrient management (PRD §3.7)
# ---------------------------------------------------------------------------
CAKE_DRY_MATTER_FRACTION = 0.30
SOLIDS_NITROGEN_KG_PER_TONNE = 5.20
PAN_FACTOR_LAB = 0.5500
PAN_FACTOR_AGRONOMIC = 0.5980
PAN_SOLIDS_AVAILABILITY = 0.35
LAND_UNIT_SETBACK_DAYS = 21

# ---------------------------------------------------------------------------
# Carbon intensity pathway maths (PRD §3.8)
# ---------------------------------------------------------------------------
MJ_PER_MMBTU = 1055.06
BMP_M3_CH4_PER_KG_VS = 0.21
MCF_LAGOON = 0.75
MCF_SOLID_STORAGE = 0.30
MCF_DAILY_SPREAD = 0.10
CH4_DENSITY_KG_PER_M3 = 0.6785
CH4_GWP = 25
G_PER_KG = 1000
TRANSPORT_CI_G_PER_MJ = 95.0
PROCESS_DESIGN_CONSTANT_G_PER_MJ = 15.40
AVOIDED_METHANE_CAP_MULTIPLIER = 20.0
CI_FLOOR_G_PER_MJ = -400.00

# LCFS credit maths (PRD §3.8)
LCFS_BENCHMARK_CI = 79.50
LCFS_EER = 0.90
LCFS_CREDIT_PRICE_CENTS = 7450

# RFS D3 RIN maths (PRD §3.8)
RFS_D3_RINS_PER_MMBTU = 11.727
RFS_D3_RIN_PRICE_CENTS = 285

# Verification audit (PRD §3.8)
MATERIAL_CI_TOLERANCE = 2.00
MAX_REMEDIATION_ROUNDS = 2

# ---------------------------------------------------------------------------
# Agreement negotiation (PRD §3.2)
# ---------------------------------------------------------------------------
MAX_NEGOTIATION_ROUNDS = 3

# ---------------------------------------------------------------------------
# Revenue waterfall (PRD §3.9)
# ---------------------------------------------------------------------------
MANAGEMENT_FEE_RATE_TIER_1 = 0.0800  # gross <= 1_000_000 cents
MANAGEMENT_FEE_RATE_TIER_2 = 0.0650  # gross <= 2_500_000 cents
MANAGEMENT_FEE_RATE_TIER_3 = 0.0500  # gross above 2_500_000 cents
FEE_TIER_1_CEILING_CENTS = 1_000_000
FEE_TIER_2_CEILING_CENTS = 2_500_000
RESERVE_SWEEP_RATE = 0.2500
DSCR_MONTHS_PER_YEAR = 12
DSCR_RESTRICTED_BAND = 0.150
RESTRICTED_PAYMENT_CAP_CENTS = 1_000_000

# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Test default master data
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "DAIRY_NAME": "Vista Verde Dairy",
    "DAIRY_COUNTY": "Tulare",
    "SECOND_DAIRY_NAME": "Rio Seco Dairy",
    "SECOND_DAIRY_COUNTY": "Kings",
    "FACILITY_NAME": "Tulare Digester 1",
    "SECOND_FACILITY_NAME": "Kings Digester 2",
    "INTERCONNECT_COUNTERPARTY": "Central Valley Gas Transmission",
    "DIGESTER_VOLUME_M3": 6000.000,
    "HYDRAULIC_CAPACITY_TONNES_PER_DAY": 500.000,
    "OPERATING_TEMPERATURE_C": 38.0,
    "RESERVE_TARGET_CENTS": 4_000_000,
    "ANNUAL_DEBT_SERVICE_CENTS": 18_000_000,
    "DSCR_MINIMUM": 1.250,
}

# Identifiers that resolve to nothing, for not-found probes (PRD §5).
UNKNOWN_IDS = {
    "dairy": "9f000000-0000-4000-8000-000000000001",
    "facility": "9f000000-0000-4000-8000-000000000002",
    "agreement": "9f000000-0000-4000-8000-000000000003",
    "delivery": "9f000000-0000-4000-8000-000000000004",
    "ops_day": "9f000000-0000-4000-8000-000000000005",
    "interconnect": "9f000000-0000-4000-8000-000000000006",
    "nomination": "9f000000-0000-4000-8000-000000000007",
    "pathway": "9f000000-0000-4000-8000-000000000008",
    "batch": "9f000000-0000-4000-8000-000000000009",
    "audit": "9f000000-0000-4000-8000-00000000000a",
    "application": "9f000000-0000-4000-8000-00000000000b",
    "statement": "9f000000-0000-4000-8000-00000000000c",
}
