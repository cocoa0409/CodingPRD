"""Every constant in the contract, taken verbatim from SCAFFOLD.yaml §1.3 and PRD §3."""
from decimal import Decimal

D = Decimal

# --- roles (PRD §2.1) -------------------------------------------------------
ROLES = [
    "PlantAdmin",
    "DealerPrincipal",
    "ProductionScheduler",
    "LineSupervisor",
    "QualityInspector",
    "WarrantyAdministrator",
    "RecallCoordinator",
]

# --- enumerated vocabularies (PRD §2.10) -----------------------------------
CHASSIS_CLASSES = ["CLASS_A", "CLASS_C", "TOWABLE"]
COMPONENT_CATEGORIES = ["CHASSIS", "APPLIANCE", "PLUMBING", "ELECTRICAL"]
OPTION_CATEGORIES = [
    "APPLIANCE",
    "PLUMBING",
    "ELECTRICAL",
    "EXTERIOR",
    "INTERIOR",
    "CHASSIS_UPGRADE",
]
INSTALL_STATIONS = [
    "SIDEWALL_LAM",
    "ROOF_SET",
    "ROUGH_IN",
    "APPLIANCE_INSTALL",
    "FINISH",
]
BUILD_STATIONS = [
    "CHASSIS_PREP",
    "SIDEWALL_LAM",
    "ROOF_SET",
    "ROUGH_IN",
    "APPLIANCE_INSTALL",
    "FINISH",
    "WATER_TEST",
    "PDI",
    "READY_TO_SHIP",
    "SHIPPED",
    "SCRAPPED",
]
# the fixed forward path (PRD §3.5)
FORWARD_PATH = [
    "CHASSIS_PREP",
    "SIDEWALL_LAM",
    "ROOF_SET",
    "ROUGH_IN",
    "APPLIANCE_INSTALL",
    "FINISH",
    "WATER_TEST",
    "PDI",
    "READY_TO_SHIP",
]
REGIONS = ["WEST", "CENTRAL", "EAST", "SOUTH"]
ORDER_TYPES = ["STOCK", "SOLD", "DEMO"]
INSPECTION_TYPES = ["WATER_TEST", "FUNCTIONAL", "PDI"]
BOOTH_TYPES = ["WATER_TEST", "FUNCTIONAL"]
INSPECTION_GRADES = ["PASS", "CONDITIONAL", "FAIL"]
CLAIM_TYPES = ["APPLIANCE", "PLUMBING", "ELECTRICAL", "STRUCTURAL", "WATER_INTRUSION"]
AUTHORITY_TIERS = ["TIER_A", "TIER_B", "TIER_C"]
SEVERITIES = ["SAFETY", "COMPLIANCE", "ADVISORY"]
SHIP_HOLDS = ["NONE", "RECALL_HOLD", "QUALITY_HOLD"]

# --- unit_order_configuration_totals ---------------------------------------
COMPLEXITY_FACTOR_TIER_1_MAX_OPTIONS = 4
COMPLEXITY_FACTOR_TIER_2_MAX_OPTIONS = 9
COMPLEXITY_FACTOR_TIER_3_MAX_OPTIONS = 14
COMPLEXITY_FACTOR_TIER_1 = D("1.00")
COMPLEXITY_FACTOR_TIER_2 = D("1.05")
COMPLEXITY_FACTOR_TIER_3 = D("1.12")
COMPLEXITY_FACTOR_TIER_4 = D("1.20")
CLASS_FACTOR = {
    "TOWABLE": D("1.00"),
    "CLASS_C": D("1.10"),
    "CLASS_A": D("1.15"),
}
ELECTRICAL_SURCHARGE_AMP_THRESHOLD = 40
ELECTRICAL_SURCHARGE_HOURS = D("4.00")
MAX_SINGLE_UNIT_HOURS = D("96.00")
WATER_DEMAND_RATIO_BP = 5000

# --- dealer_invoice_amount -------------------------------------------------
BASE_UNIT_DISCOUNT_BP = {"STOCK": 2200, "SOLD": 2050, "DEMO": 2600}
OPTION_DISCOUNT_BP = {
    "APPLIANCE": 1550,
    "PLUMBING": 1450,
    "ELECTRICAL": 1725,
    "EXTERIOR": 1600,
    "INTERIOR": 1350,
    "CHASSIS_UPGRADE": 1250,
}
FREIGHT_BASE_CENTS = 180000
FREIGHT_PER_FOOT_CENTS = 4200
REGION_SURCHARGE_CENTS = {"WEST": 95000, "CENTRAL": 0, "EAST": 60000, "SOUTH": 35000}
OT_RATE_CENTS_PER_HOUR = 8500
REWORK_SURCHARGE_CENTS = 45000
QUALITY_CREDIT_PER_POINT_CENTS = 1500
QUALITY_CREDIT_CAP_CENTS = 90000

# --- warranty_claim_reimbursement -----------------------------------------
LABOR_HOUR_CAP = D("8.0")
LABOR_RATE_CENTS = {
    "APPLIANCE": 7800,
    "PLUMBING": 8600,
    "ELECTRICAL": 9200,
    "STRUCTURAL": 10400,
    "WATER_INTRUSION": 11000,
}
PARTS_HANDLING_BP = 1500
TIER_A_MAX_CENTS = 150000
TIER_B_MAX_CENTS = 750000
GOODWILL_TIER_CAP_CENTS = {"TIER_A": 75000, "TIER_B": 150000, "TIER_C": 0}
GOODWILL_PCT_BP = 2000
OUT_OF_WARRANTY_GOODWILL_CAP_CENTS = 50000
CHARGEBACK_BP = {"ACTIVE": 6000, "PROBATION": 8000, "SUSPENDED": 10000}
WARRANTY_DAYS = 365
MAX_INFO_REQUESTS = 2

# --- supplier_quality_score ----------------------------------------------
SCORE_BASE = D("100.00")
ROLLING_WINDOW_DAYS = 90
LIFETIME_DECAY_FACTOR = D("0.5")
RECALL_PENALTY_WEIGHT = {
    "SAFETY": D("15.0"),
    "COMPLIANCE": D("10.0"),
    "ADVISORY": D("4.0"),
}
CHARGEBACK_CLAIM_PENALTY_WEIGHT = D("2.0")
SUPPLIER_ACTIVE_MIN_SCORE = D("70.00")
SUPPLIER_PROBATION_MIN_SCORE = D("50.00")

# --- dealer_credit_utilization -------------------------------------------
CREDIT_HOLD_BP = 9500
WATCH_BP = 8000
FLOOR_PLAN_ADVANCE_BP = 9000

# --- line_day_slot_capacity ----------------------------------------------
SLOT_RESERVATION_TTL_HOURS = 72

# --- booth_window_conflict -----------------------------------------------
MIN_TEST_MINUTES = 30
MAX_TEST_MINUTES = 240

# --- chassis_match_selection ---------------------------------------------
CHASSIS_GVWR_MARGIN_LBS = 500

# --- floor_plan_curtailment_due ------------------------------------------
CURTAIL_STAGE_1_DAYS = 180
CURTAIL_STAGE_2_DAYS = 270
CURTAIL_STAGE_3_DAYS = 365
CURTAIL_STAGE_1_BP = 1000
CURTAIL_STAGE_2_BP = 2500
CURTAIL_STAGE_3_BP = 5000

# --- dealer_slot_entitlement ---------------------------------------------
WORKING_DAYS_PER_MONTH = 20
OVERSUBSCRIPTION_TOLERANCE_BP = 500

# --- inspection_grade -----------------------------------------------------
WET_CONDITIONAL_MIN_POINTS = 6
WET_FAIL_MAX_POINTS = 12
PDI_CONDITIONAL_MIN_POINTS = 4
PDI_FAIL_MAX_POINTS = 8
MAX_REWORK = 2
