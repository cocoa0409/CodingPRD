"""Pinned constants of the specification: the clock instants the suite drives
the logical clock to, the catalogue prices, the depth-of-stock floors, the
scoring weights and the statutory ceilings.
"""

# --------------------------------------------------------------------------
# The logical clock. Before any caller sets it, the clock reads exactly
# 2026-08-01T00:00:00Z.
# --------------------------------------------------------------------------

CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

MAR_01 = "2026-03-01T00:00:00Z"
APR_01 = "2026-04-01T00:00:00Z"
JUN_01 = "2026-06-01T00:00:00Z"
JUL_01 = "2026-07-01T00:00:00Z"
AUG_01 = "2026-08-01T00:00:00Z"
AUG_02 = "2026-08-02T00:00:00Z"
AUG_05 = "2026-08-05T00:00:00Z"
AUG_10 = "2026-08-10T00:00:00Z"
AUG_11 = "2026-08-11T00:00:00Z"
AUG_12 = "2026-08-12T00:00:00Z"
AUG_20 = "2026-08-20T00:00:00Z"
AUG_21 = "2026-08-21T00:00:00Z"
AUG_25 = "2026-08-25T00:00:00Z"
SEP_01 = "2026-09-01T00:00:00Z"
SEP_20 = "2026-09-20T00:00:00Z"
SEP_30 = "2026-09-30T00:00:00Z"
OCT_01 = "2026-10-01T00:00:00Z"

# --------------------------------------------------------------------------
# Deadline arithmetic (§2.4)
# --------------------------------------------------------------------------

REPLY_WINDOW_DAYS = 10
CMP_ELECTION_WINDOW_DAYS = 10
ADMIN_REVIEW_WINDOW_DAYS = 10
EFFECTIVE_DATE_DAYS = 30

# --------------------------------------------------------------------------
# Eligibility (§3.1, §3.2, §3.3)
# --------------------------------------------------------------------------

CRITERION_B_STRICT_BPS = 5000
DESK_MIN_VARIETIES = 3
DESK_MIN_AGGREGATE_UNITS = 9
ONSITE_MIN_DEEP_VARIETIES = 3
ONSITE_DEEP_VARIETY_UNIT_FLOOR = 3
REQUIRED_QUALIFYING_CATEGORIES = 4
REQUIRED_PERISHABLE_CATEGORIES = 2

DEPTH_OF_STOCK_FLOOR_FEET = {
    "SUPERMARKET": 120,
    "GROCERY": 60,
    "CONVENIENCE": 24,
    "SPECIALTY": 16,
    "FARMERS_MARKET": 0,
    "MEAL_SERVICE": 0,
}

SHELF_DISCREPANCY_STRICT_BPS = 2500

MAX_DEFICIENCY_CYCLES = 3
FNS_NUMBER_FIRST = "FNS-1000001"

# --------------------------------------------------------------------------
# Field visits (§2.10, §3.3)
# --------------------------------------------------------------------------

TRAVEL_BUFFER_MINUTES = 60

# --------------------------------------------------------------------------
# Monitoring and anomaly scoring (§3.7)
# --------------------------------------------------------------------------

RECONCILIATION_TOLERANCE_CENTS = 500
LARGE_TRANSACTION_FLOOR_CENTS = 10000
EVEN_DOLLAR_MULTIPLE_CENTS = 1000

FOOTPRINT_PER_LANE_CENTS = 400000
FOOTPRINT_PER_SHELF_FOOT_CENTS = 15000
SIZE_EXPECTATION_FLOOR_CENTS = 100000

ANOMALY_WEIGHTS = {
    "CONVENIENCE": (45, 35, 20),
    "SPECIALTY": (45, 35, 20),
    "FARMERS_MARKET": (20, 30, 50),
    "SUPERMARKET": (50, 30, 20),
    "GROCERY": (50, 30, 20),
    "MEAL_SERVICE": (50, 30, 20),
}

FLAG_L3_FLOOR = 70
FLAG_L2_FLOOR = 50
FLAG_L1_FLOOR = 25

# --------------------------------------------------------------------------
# Evidence decay (§3.8)
# --------------------------------------------------------------------------

EVIDENCE_BASE_WEIGHTS = {
    "UNDERCOVER_BUY": 40,
    "INVENTORY_PURCHASE_MISMATCH": 25,
    "EBT_ONLY_TRANSACTION_PATTERN": 20,
    "INFORMANT_STATEMENT": 15,
    "HOUSEHOLD_INTERVIEW": 10,
}

TRAFFICKING_SCORE_FLOOR = 60

# --------------------------------------------------------------------------
# Civil money penalty (§3.9)
# --------------------------------------------------------------------------

CMP_RATE_BPS = 1000
CMP_CAP_CENTS = 6900000
TRAFFICKING_CMP_MONTHS = 10
CMP_SEASONING_DAYS = 365
TRAILING_PERIOD_COUNT = 12
PEAK_PERIOD_COUNT = 3

# --------------------------------------------------------------------------
# Equipment catalogue (§3.5)
# --------------------------------------------------------------------------

ITEM_UNIT_PRICE_CENTS = {
    "EBT_ONLY_WIRELESS_TERMINAL": 42500,
    "EBT_ONLY_DIAL_TERMINAL": 31000,
    "COMMERCIAL_POS_INTEGRATION": 185000,
    "MANUAL_VOUCHER_KIT": 4500,
    "SIGNAGE_PACK": 2200,
    "RECEIPT_PAPER_CASE": 4000,
}

SUBSIDIZED_ITEM_CODES = (
    "EBT_ONLY_WIRELESS_TERMINAL",
    "EBT_ONLY_DIAL_TERMINAL",
    "MANUAL_VOUCHER_KIT",
    "SIGNAGE_PACK",
)

SUBSIDY_SALES_CEILING_CENTS = 500000000
FREE_HANDLING_NET_FLOOR_CENTS = 25000
HANDLING_FEE_CENTS = 1500

# --------------------------------------------------------------------------
# Owner rollup (§3.1)
# --------------------------------------------------------------------------

OWNER_BARRED_DISQUALIFICATION_COUNT = 2

# --------------------------------------------------------------------------
# Pagination (§2.3)
# --------------------------------------------------------------------------

DEFAULT_LIMIT = 10
MAX_LIMIT = 100
