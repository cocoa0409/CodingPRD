"""Domain thresholds, rates and canonical fixture payload values from PRD.md.

Every value here is quoted from a rule-bearing sentence of the PRD so that tests
never hard-code a magic number whose provenance is unclear.
"""

# ─── PRD §2.5 Logical clock ────────────────────────────────────────────────
CLOCK_START_UTC = "2026-08-01T00:00:00Z"

# ─── PRD §3.2 Station-hour roll-up ─────────────────────────────────────────
# "the complexity factor is 1.00 for four or fewer selected options, 1.05 for
#  five to nine, 1.12 for ten to fourteen, and 1.20 for fifteen or more"
COMPLEXITY_FACTOR_TIERS = ((4, "1.00"), (9, "1.05"), (14, "1.12"), (None, "1.20"))
# "the class factor is 1.00 for TOWABLE, 1.10 for CLASS_C and 1.15 for CLASS_A"
CLASS_FACTOR = {"TOWABLE": "1.00", "CLASS_C": "1.10", "CLASS_A": "1.15"}
# "a unit whose total amp draw exceeds 40 amps adds a flat 4 hours"
AMP_SURCHARGE_THRESHOLD_AMPS = 40
AMP_SURCHARGE_HOURS = "4.00"
# "A configuration whose required_station_hours exceeds 96.00"
MAX_UNIT_STATION_HOURS = "96.00"
# "5000 basis points of the floor plan's fresh_water_capacity_gal"
WATER_CEILING_BP = 5000
# "gvwr_lbs minus config_weight_lbs" -> payload_remaining_lbs
CHASSIS_GVWR_MARGIN_LBS = 500

# ─── PRD §3.7 Invoice discounts and freight ────────────────────────────────
BASE_DISCOUNT_BP = {"STOCK": 2200, "SOLD": 2050, "DEMO": 2600}
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
REGION_FREIGHT_CENTS = {"WEST": 95000, "CENTRAL": 0, "EAST": 60000, "SOUTH": 35000}
OVERTIME_RATE_CENTS_PER_HOUR = 8500
REWORK_SURCHARGE_CENTS = 45000
QUALITY_CREDIT_PER_POINT_CENTS = 1500
QUALITY_CREDIT_CAP_CENTS = 90000

# ─── PRD §3.7 Floor-plan financing ─────────────────────────────────────────
FLOOR_PLAN_ADVANCE_BP = 9000
CREDIT_HOLD_BP = 9500
CREDIT_WATCH_BP = 8000
# "At 365 days or more ... 5000 basis points ... 270 ... 2500 ... 180 ... 1000"
CURTAILMENT_STAGES = ((365, 5000), (270, 2500), (180, 1000))

# ─── PRD §3.3 Capacity and allocation ──────────────────────────────────────
SLOT_RESERVATION_TTL_HOURS = 72
WORKING_DAYS_PER_MONTH = 20
ALLOCATION_TOLERANCE_BP = 10500

# ─── PRD §3.6 Booths, windows and grading ──────────────────────────────────
MIN_INSPECTION_WINDOW_MINUTES = 30
MAX_INSPECTION_WINDOW_MINUTES = 240
GRADE_THRESHOLDS = {
    # inspection_type -> (fail_above, conditional_from)
    "WATER_TEST": (12, 6),
    "FUNCTIONAL": (12, 6),
    "PDI": (8, 4),
}
MAX_REWORK_COUNT = 2

# ─── PRD §3.8 Warranty reimbursement waterfall ─────────────────────────────
LABOR_HOUR_CAP = "8.0"
LABOR_RATE_CENTS_PER_HOUR = {
    "APPLIANCE": 7800,
    "PLUMBING": 8600,
    "ELECTRICAL": 9200,
    "STRUCTURAL": 10400,
    "WATER_INTRUSION": 11000,
}
PARTS_MARKUP_BP = 11500
TIER_A_MAX_SUBTOTAL_CENTS = 150000
TIER_B_MAX_SUBTOTAL_CENTS = 750000
TIER_GOODWILL_CAP_CENTS = {"TIER_A": 75000, "TIER_B": 150000, "TIER_C": 0}
GOODWILL_SUBTOTAL_BP = 2000
OUT_OF_WARRANTY_GOODWILL_CAP_CENTS = 50000
CHARGEBACK_BP = {"ACTIVE": 6000, "PROBATION": 8000, "SUSPENDED": 10000}
WARRANTY_DAYS = 365
MAX_INFO_REQUESTS = 2

# ─── PRD §3.9 Supplier trust score ─────────────────────────────────────────
SCORE_BASE = "100.00"
ROLLING_WINDOW_DAYS = 90
SEVERITY_WEIGHT = {"SAFETY": "15.0", "COMPLIANCE": "10.0", "ADVISORY": "4.0"}
CHARGEBACK_CLAIM_WEIGHT = "2.0"
SUPPLIER_ACTIVE_MIN_SCORE = "70.00"
SUPPLIER_PROBATION_MIN_SCORE = "50.00"

# ─── PRD §3.5 Station path ─────────────────────────────────────────────────
STATION_SEQUENCE = [
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

# ─── Canonical towable fixture kit (see fixtures.build_tow_kit) ────────────
TOW = {
    "FP_MODEL_CODE": "FP-TOW",
    "FP_LENGTH_FT": 28,
    "FP_BASE_MSRP_CENTS": 8000000,
    "FP_BASE_STATION_HOURS": 40.00,
    "FP_BASE_DRY_WEIGHT_LBS": 6000,
    "FP_GVWR_LBS": 9000,
    "FP_WHEELBASE_IN": 180,
    "FP_AMPS": 50,
    "FP_WATER_GAL": 60,
    "OPT_CODE": "OPT-E1",
    "OPT_PRICE_CENTS": 100000,
    "OPT_STATION_HOURS": 1.00,
    "OPT_AMPS": 20,
    "DEALER_CODE": "D-TOW",
    "DEALER_REGION": "CENTRAL",
    "DEALER_SHARE_BP": 1500,
    "DEALER_CREDIT_LIMIT_CENTS": 100000000,
    "DEALER_GOODWILL_CENTS": 500000,
    "LINE_CODE": "LINE-T",
    "LINE_HOURS": 240.00,
    "LINE_UNITS": 4,
    "CHASSIS_SERIAL": "CH-T1",
    "BOOTH_CODE": "BOOTH-W",
    # Expected figures for a STOCK order on [OPT-E1]
    "REQUIRED_STATION_HOURS": 41.00,
    "CONFIG_WEIGHT_LBS": 6000,
    "PAYLOAD_REMAINING_LBS": 3000,
    "PROVISIONAL_INVOICE_CENTS": 6620350,
    "FINANCED_PRINCIPAL_CENTS": 5958315,
}

# ─── Canonical Class A fixture kit (see fixtures.build_canon_kit) ──────────
CANON = {
    "FP_MODEL_CODE": "FP-3410",
    "FP_LENGTH_FT": 34,
    "FP_BASE_MSRP_CENTS": 18500000,
    "FP_BASE_STATION_HOURS": 46.00,
    "FP_BASE_DRY_WEIGHT_LBS": 22400,
    "FP_GVWR_LBS": 26000,
    "FP_WHEELBASE_IN": 242,
    "FP_AMPS": 50,
    "FP_WATER_GAL": 90,
    "DEALER_CODE": "D-WEST",
    "DEALER_REGION": "WEST",
    "DEALER_SHARE_BP": 1500,
    "DEALER_CREDIT_LIMIT_CENTS": 15274000,
    "DEALER_GOODWILL_CENTS": 500000,
    "LINE_CODE": "LINE-A",
    "LINE_HOURS": 240.00,
    "LINE_UNITS": 4,
    "CHASSIS_SERIAL": "CH-0001",
    "BOOTH_CODE": "BOOTH-1",
    "LOT_PART_NUMBER": "WH-6G-2026",
    "LOT_CODE": "L-2211",
    "LOT_QUANTITY": 20,
    # Expected figures for a STOCK order on the five canonical options
    "REQUIRED_STATION_HOURS": 71.24,
    "CONFIG_WEIGHT_LBS": 22920,
    "OPTION_PRICE_TOTAL_CENTS": 1535500,
    "PROVISIONAL_INVOICE_CENTS": 16122725,
    "FINANCED_PRINCIPAL_CENTS": 14510453,
}
