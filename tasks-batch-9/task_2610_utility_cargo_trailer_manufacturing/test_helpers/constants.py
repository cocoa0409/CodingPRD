"""Domain thresholds, canonical literals and pre-computed expectations.

Every value here traces to the Utility & Cargo Trailer Manufacturing PRD:
the logical-clock default of PRD 2.4, the rounding discipline of PRD 2.9,
the GVWR capacities of PRD 3.1, the jig geometry of PRD 3.2, the frame
verdict criteria of PRD 3.3, the regulatory lamp and brake rules of
PRD 3.4, the lane geometry of PRD 3.6, the VIN assembly of PRD 3.7, the
seven-step invoice of PRD 3.8 and the warranty reimbursement of PRD 3.9.
"""

# --- PRD 2.4 the logical plant clock -------------------------------------
CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"
CLOCK_AUG_05 = "2026-08-05T00:00:00Z"
CLOCK_AUG_06 = "2026-08-06T08:00:00Z"
CLOCK_AUG_07 = "2026-08-07T09:00:00Z"
CLOCK_SEP_01 = "2026-09-01T00:00:00Z"
CLOCK_SEP_02 = "2026-09-02T00:00:00Z"

# --- PRD 2.3 pagination ---------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# --- PRD 3.1 GVWR capacities --------------------------------------------
TIRES_PER_AXLE = 2
UNBRAKED_DERATE_FACTOR = 0.90
CERTIFIED_GVWR_FLOOR_STEP_LBS = 10

# --- PRD 3.2 jig occupancy ----------------------------------------------
DEFAULT_CHANGEOVER_BUFFER_MIN = 45

# --- PRD 3.3 frame dimensional verdict ----------------------------------
MAX_DEVIATION_TOLERANCE_MM = 3.0
SQUARENESS_TOLERANCE_MM = 6.0
NON_CRITICAL_DEFECT_TOLERANCE = 2
FRAME_SCRAP_THRESHOLD = 3
FRAME_FAILURE_CRITICAL = "CRITICAL_WELD_DEFECT"
FRAME_FAILURE_MAX_DEVIATION = "MAX_DEVIATION"
FRAME_FAILURE_NON_CRITICAL = "NON_CRITICAL_WELD_DEFECT"
FRAME_FAILURE_SQUARENESS = "SQUARENESS"

# --- PRD 3.4 regulatory equipment ---------------------------------------
MIN_STOP_TAIL_TURN_LAMPS = 2
MIN_LICENSE_PLATE_LAMPS = 1
MIN_REFLEX_REFLECTORS = 4
WIDE_BODY_WIDTH_IN = 80.0
WIDE_BODY_MIN_CLEARANCE_LAMPS = 5
WIDE_BODY_MIN_SIDE_MARKER_LAMPS = 4
BRAKE_REQUIRED_GVWR_LBS = 3000
ALL_AXLES_BRAKED_GVWR_LBS = 10000

# --- PRD 3.5 option weight budget ---------------------------------------
MIN_PAYLOAD_CAPACITY_LBS = 0
OPTION_CODES = (
    "REAR_RAMP_GATE",
    "SIDE_CABINET_PKG",
    "SPECIALTY_FLOORING",
    "SPARE_TIRE_CARRIER",
    "E_TRACK_KIT",
)

# --- PRD 3.6 road test ---------------------------------------------------
DEFAULT_LANE_CAPACITY = 2
MAX_BRAKE_STOP_DISTANCE_FT = 40.0
PROTOCOL_CODES = ("STANDARD_20MI", "LOADED_50MI", "BRAKE_FADE")

# --- PRD 3.7 VIN assembly ------------------------------------------------
VIN_WMI = "5XY"
VIN_BODY_STYLE_CHAR = "A"
VIN_CHECK_PLACEHOLDER = "0"
VIN_PLANT_CHAR = "P"
VIN_LENGTH = 17
VIN_YEAR_CHARS = {2026: "T", 2027: "V", 2028: "W", 2029: "X", 2030: "Y"}
MCO_PREFIX = "MCO-"

# --- PRD 3.8 invoice, floor plan and allocation -------------------------
FREIGHT_CENTS = 89500
FLOOR_PLAN_DRAW_PCT = 0.90
VOLUME_TIER_0_PCT = 0.00
VOLUME_TIER_1_PCT = 0.03
VOLUME_TIER_2_PCT = 0.05
STOCKING_PROGRAMS = ("STOCK", "SOLD_ORDER", "DEMO")
FLOOR_PLAN_ADJUSTMENT_TYPES = (
    "LIMIT_INCREASE",
    "LIMIT_DECREASE",
    "PAYOFF",
    "CREDIT_HOLD",
    "CREDIT_RELEASE",
)

# --- PRD 3.9 warranty ----------------------------------------------------
WARRANTY_TERM_DAYS = 730
GOODWILL_TAIL_DAYS = 90
FLAT_RATE_HOURS = {
    "AXLE": 3.5,
    "BRAKE": 2.5,
    "LIGHTING": 1.5,
    "FRAME": 6.0,
    "FLOORING": 4.0,
    "COUPLER": 2.0,
}
FLAT_RATE_CEILING_MULTIPLIER = 1.25
PARTS_MARKUP_MULTIPLIER = 1.30
WARRANTY_FREIGHT_CENTS = 4500
FREIGHT_WAIVER_CENTS = 50000
COVERAGE_FACTOR_IN_WARRANTY = 1.00
COVERAGE_BAND_FACTORS = (0.75, 0.50, 0.25)
INFO_REQUEST_LIMIT = 2
DENIAL_INFO_REQUEST_LIMIT = "INFO_REQUEST_LIMIT_REACHED"
DENIAL_REVIEWER_DENIED = "REVIEWER_DENIED"
VOIDED_REASON_ROAD_TEST_FAILED = "ROAD_TEST_FAILED"

# --- Canonical trailer model TA-7X14 ------------------------------------
# axle capacity 2 x 3500 = 7000, tire capacity 2 x 2 x 1820 = 7280,
# frame 7200, coupler 7500. Provisional omits the tire limit and the
# derate; certified takes all four, derates by 0.90 for the unbraked axle
# and floors to 10 lb.
MODEL_TA = {
    "model_code": "TA-7X14",
    "description": "Tandem 7x14 cargo",
    "axle_count": 2,
    "axle_rating_lbs": 3500,
    "design_braked_axle_count": 1,
    "tire_load_rating_lbs": 1820,
    "frame_design_code": "TA",
    "frame_design_rated_lbs": 7200,
    "coupler_rating_lbs": 7500,
    "overall_width_in": 78.5,
    "nominal_length_mm": 4267,
    "nominal_width_mm": 2134,
    "base_curb_weight_lbs": 1980,
    "base_dealer_price_cents": 489900,
}
TA_PROVISIONAL_GVWR_LBS = 7000
TA_CERTIFIED_GVWR_LBS = 6300
TA_BASE_CURB_WEIGHT_LBS = 1980
TA_PAYLOAD_CAPACITY_LBS = 4320
TA_BASE_DEALER_PRICE_CENTS = 489900
# create + certification submission + certification decision
TA_MODEL_VERSION_AT_CERTIFICATION = 3

# --- Canonical assets and dealer ----------------------------------------
JIG_TA = {"jig_code": "JIG-TA-01", "frame_design_code": "TA", "changeover_buffer_min": 45}
LANE_01 = {"lane_code": "LANE-01", "surface_type": "ASPHALT", "max_concurrent_tests": 2}
DEALER_001 = {
    "dealer_code": "DLR-001",
    "name": "Prairie Trailer Sales",
    "labor_rate_cents_per_hour": 9500,
    "floor_plan_limit_cents": 200000000,
    "allocation_quota_per_month": 5,
}
DEALER_LABOR_RATE_CENTS_PER_HOUR = 9500
DEALER_FLOOR_PLAN_LIMIT_CENTS = 200000000

# --- Canonical weld and test windows ------------------------------------
JIG_WINDOW_1 = ("2026-08-03T09:00:00Z", "2026-08-03T11:00:00Z")   # 120 minutes
JIG_WINDOW_2 = ("2026-08-03T12:00:00Z", "2026-08-03T13:00:00Z")   # 60 minutes
JIG_WINDOW_3 = ("2026-08-03T14:00:00Z", "2026-08-03T15:00:00Z")   # 60 minutes
JIG_WINDOW_1_OCCUPANCY_END = "2026-08-03T11:45:00Z"
LANE_WINDOW_1 = ("2026-08-04T10:00:00Z", "2026-08-04T11:00:00Z")
LANE_WINDOW_2 = ("2026-08-04T12:00:00Z", "2026-08-04T13:00:00Z")
RETEST_WINDOW = ("2026-08-05T10:00:00Z", "2026-08-05T11:00:00Z")

# --- Pre-computed invoice expectations for a TA-7X14 stock order --------
# subtotal 489900, tier 0 so discount 0 and freight 89500,
# total 579400, draw 579400 x 0.90 = 521460 (round half up).
ORDER1_SUBTOTAL_CENTS = 489900
ORDER1_DISCOUNT_CENTS = 0
ORDER1_FREIGHT_CENTS = 89500
ORDER1_TOTAL_CENTS = 579400
ORDER1_DRAW_CENTS = 521460
# second allocation of the same calendar year: tier 0.03, freight waived.
ORDER2_DISCOUNT_PCT = 0.03
ORDER2_DISCOUNT_CENTS = 14697
ORDER2_FREIGHT_CENTS = 0
ORDER2_TOTAL_CENTS = 475203
ORDER2_DRAW_CENTS = 427683
TWO_ORDER_OUTSTANDING_CENTS = 949143

# --- Pre-computed warranty expectations ---------------------------------
# BRAKE claim, 2.4 h at 9500 c/h, part lines 5398 x 3 and 911 x 1.
# 5398 x 1.30 = 7017.4 -> 7017 -> x3 = 21051
#  911 x 1.30 = 1184.3 -> 1184 -> x1 =  1184
CLAIM_PART_LINES = [
    {"part_number": "BRK-5398", "unit_cost_cents": 5398, "quantity": 3},
    {"part_number": "BRK-0911", "unit_cost_cents": 911, "quantity": 1},
]
CLAIM_LABOR_HOURS = 2.4
CLAIM_LABOR_CENTS = 22800
CLAIM_PARTS_SUBTOTAL_CENTS = 22235
CLAIM_FREIGHT_CENTS = 4500
CLAIM_GROSS_CENTS = 49535
CLAIM_GOODWILL_75_CENTS = 37151
CLAIM_GOODWILL_50_CENTS = 24768

# --- Single-axle models straddling the 3000 lb brake threshold -----------
# Both derate by 0.90 because design_braked_axle_count 0 is strictly less
# than axle_count 1, and both are then floored to a multiple of 10 lb:
# 3340 -> 3006 -> 3000 requires brakes, 3330 -> 2997 -> 2990 does not.
MODEL_SA_HEAVY = {
    "model_code": "SA-5X8H",
    "description": "Single-axle 5x8 heavy frame",
    "axle_count": 1,
    "axle_rating_lbs": 3400,
    "design_braked_axle_count": 0,
    "tire_load_rating_lbs": 1750,
    "frame_design_code": "SA",
    "frame_design_rated_lbs": 3340,
    "coupler_rating_lbs": 3600,
    "overall_width_in": 70.0,
    "nominal_length_mm": 3048,
    "nominal_width_mm": 1524,
    "base_curb_weight_lbs": 980,
    "base_dealer_price_cents": 219900,
}
MODEL_SA_LIGHT = dict(
    MODEL_SA_HEAVY,
    model_code="SA-5X8L",
    description="Single-axle 5x8 light frame",
    frame_design_rated_lbs=3330,
)
SA_HEAVY_PROVISIONAL_GVWR_LBS = 3340
SA_HEAVY_CERTIFIED_GVWR_LBS = 3000
SA_HEAVY_PAYLOAD_CAPACITY_LBS = 2020
SA_LIGHT_CERTIFIED_GVWR_LBS = 2990
SA_LIGHT_PAYLOAD_CAPACITY_LBS = 2010
SA_NOMINAL_LENGTH_MM = 3048
SA_NOMINAL_WIDTH_MM = 1524
SA_DIAGONAL_MM = 3408

# --- A second frame family, used for tooling and model mismatches -------
MODEL_SC = {
    "model_code": "SC-6X12",
    "description": "Single-axle 6x12 cargo",
    "axle_count": 1,
    "axle_rating_lbs": 3500,
    "design_braked_axle_count": 1,
    "tire_load_rating_lbs": 1820,
    "frame_design_code": "SC",
    "frame_design_rated_lbs": 3600,
    "coupler_rating_lbs": 3500,
    "overall_width_in": 74.0,
    "nominal_length_mm": 3658,
    "nominal_width_mm": 1829,
    "base_curb_weight_lbs": 1180,
    "base_dealer_price_cents": 289900,
}

# --- Additional plant assets and a second dealer ------------------------
JIG_SA = {"jig_code": "JIG-SA-01", "frame_design_code": "SA", "changeover_buffer_min": 45}
JIG_SC = {"jig_code": "JIG-SC-01", "frame_design_code": "SC", "changeover_buffer_min": 45}
DEALER_002 = {
    "dealer_code": "DLR-002",
    "name": "Lakeside Trailer Center",
    "labor_rate_cents_per_hour": 8800,
    "floor_plan_limit_cents": 100000000,
    "allocation_quota_per_month": 3,
}

# --- Canonical frame readings for the TA-7X14 ----------------------------
TA_NOMINAL_LENGTH_MM = 4267
TA_NOMINAL_WIDTH_MM = 2134
TA_DIAGONAL_MM = 4770

# --- Canonical VIN and MCO for the first two labels ---------------------
VIN_FIRST = "5XYTA2EA0TP000001"
VIN_SECOND = "5XYTA2EA0TP000002"
MCO_FIRST = "MCO-000001"
MCO_SECOND = "MCO-000002"
TA_GAWR_PER_AXLE_LBS = 3500

# --- Canonical warranty claim identifiers -------------------------------
CLAIM_REF_1 = "WC-0001"
CLAIM_FAILURE_DATE_IN_WARRANTY = "2026-08-28T00:00:00Z"

# --- Warranty calendar: a trailer delivered 2026-08-05 expires 2028-08-04 -
WARRANTY_START_AUG_05 = "2026-08-05T00:00:00Z"
WARRANTY_EXPIRY_INSTANT = "2028-08-04T00:00:00Z"
CLOCK_2028_AUG_20 = "2028-08-20T00:00:00Z"
CLOCK_2028_OCT_15 = "2028-10-15T00:00:00Z"
FAILURE_ON_EXPIRY = "2028-08-04T00:00:00Z"          # 0 days past -> 1.00
FAILURE_10_DAYS_PAST_EXPIRY = "2028-08-14T00:00:00Z"  # band 1..30 -> 0.75
FAILURE_58_DAYS_PAST_EXPIRY = "2028-10-01T00:00:00Z"  # band 31..60 -> 0.50
# Wrong rounding orders the per-line discipline must not produce.
CLAIM_PARTS_SUM_THEN_ROUND_ONCE_CENTS = 22237
CLAIM_PARTS_QUANTITY_THEN_ROUND_CENTS = 22236
CLAIM_REF_IN_WARRANTY = "WC-IN-WARRANTY"
CLAIM_REF_GOODWILL = "WC-GOODWILL"
CLAIM_REF_ROUNDING = "WC-ROUNDING"
CLAIM_REF_LOOP = "WC-LOOP"
CLAIM_REF_EARLY = "WC-EARLY"
COVERAGE_DELTA_FULL_MINUS_GOODWILL_CENTS = 12384
FAILURE_BEFORE_DELIVERY = "2026-07-30T00:00:00Z"

# --- A FLOORING claim whose parts land exactly on the freight waiver ------
# 9615 x 1.30 = 12499.5 -> 12500, then x 4 = 50000 exactly.
CLAIM_FLOORING_PART_LINES = [
    {"part_number": "FLR-9615", "unit_cost_cents": 9615, "quantity": 4},
]
CLAIM_FLOORING_LABOR_HOURS = 2.0
CLAIM_FLOORING_LABOR_CENTS = 19000
CLAIM_FLOORING_PARTS_SUBTOTAL_CENTS = 50000
CLAIM_FLOORING_TOTAL_CENTS = 69000
TWO_ORDER_AVAILABLE_CENTS = 199050857

# --- A limit decrease that strands an outstanding 521460 draw -------------
SQUEEZED_LIMIT_CENTS = 500000
SQUEEZED_HEADROOM_CENTS = -21460

# --- Far past the 730-day expiry plus the 90-day goodwill tail ------------
CLOCK_2029_JAN_02 = "2029-01-02T00:00:00Z"
FAILURE_FAR_PAST_GOODWILL = "2029-01-01T00:00:00Z"

# --- The first refused labor figure for an AXLE claim ---------------------
# 3.5 x 1.25 = 4.375 is the inclusive ceiling, so 4.376 is the first refusal.
CLAIM_AXLE_HOURS_CEILING = 4.375
CLAIM_AXLE_HOURS_OVER_CEILING = 4.376

# --- Headroom left after a single 521460 draw on the 200000000 line -------
ORDER1_AVAILABLE_CENTS = 199478540

# --- The seven-role clock sweep of PRD 2.4 --------------------------------
CLOCK_ROLE_SWEEP = (
    "2026-08-02T01:00:00Z",
    "2026-08-02T02:00:00Z",
    "2026-08-02T03:00:00Z",
    "2026-08-02T04:00:00Z",
    "2026-08-02T05:00:00Z",
    "2026-08-02T06:00:00Z",
    "2026-08-02T07:00:00Z",
)
