"""Domain thresholds and constants named by the PRD's calculation prose."""

# ---- match probability score -------------------------------------------------
LOCUS_ORDER = ["A", "B", "C", "DRB1", "DQB1"]
LOCUS_WEIGHTS = {"A": 1.0, "B": 1.0, "C": 0.8, "DRB1": 1.4, "DQB1": 0.6}
LOCUS_WEIGHT_TOTAL = 9.6
AMBIGUITY_PENALTY_PER_LOCUS = 3.5
CMV_MATCH_BONUS = 1.5
DOMESTIC_BONUS = 1.0
MIN_ACCEPTABLE_ALLELE_MATCHES = 9

# ---- candidate ranking -------------------------------------------------------
RANK_W_SCORE = 0.55
RANK_W_AGE = 0.25
RANK_W_LOGISTICS = 0.20
AGE_FACTOR_IDEAL = 27
AGE_FACTOR_SLOPE = 2.5
PRIOR_DONATION_PENALTY = 15
INTL_BASE_FACTOR = 55
TIER_BONUS = 5

# ---- pool materialisation ----------------------------------------------------
DONOR_MIN_AGE = 18
DONOR_MAX_AGE = 60
MIN_PRELIM_SCORE_DEFAULT = 60.00
MAX_CANDIDATES_MATERIALIZED = 5
BACKUP_SLOTS = 2

# ---- confirmatory typing deadlines ------------------------------------------
INTERNATIONAL_GRACE_HOURS = 48
PRIORITY_DEADLINE_REDUCTION_HOURS = 24
MAX_CT_ATTEMPTS = 2

# ---- collection window / viability ------------------------------------------
CONDITIONING_TO_COLLECTION_MIN_DAYS = 6
CONDITIONING_TO_COLLECTION_MAX_DAYS = 8
METHOD_WINDOW_OFFSETS = {"PBSC": (4, 1), "MARROW": (1, 6)}
METHOD_WINDOW_DAYS = {"PBSC": 6, "MARROW": 8}
VIABILITY_HOURS = {"PBSC": 72, "MARROW": 48}
METHOD_DURATION_MINUTES = {"PBSC": 300, "MARROW": 240}
MIN_CD34_E6_PER_KG = 2.00

# ---- capacity / calendar -----------------------------------------------------
TURNAROUND_BUFFER_MINUTES = 90
DONOR_CALENDAR_CAPACITY = 1
CLEARANCE_FAIL_DEFERRAL_DAYS = 90
ADVERSE_EVENT_DEFERRAL_GRADE = 4
IDM_VALIDITY_DAYS = 30

# ---- reimbursement claim -----------------------------------------------------
CT_TYPING_FEE_CENTS = 34_500
WORKUP_PHYSICAL_FEE_CENTS = 78_000
IDM_PANEL_FEE_CENTS = 52_500
COLLECTION_FEE_CENTS = {"PBSC": 1_450_000, "MARROW": 1_980_000}
COURIER_BASE_CENTS = 265_000
COURIER_INTERNATIONAL_SURCHARGE_PCT = 0.35
DONOR_LOST_WAGE_PER_DAY_CENTS = 32_000
CANCELLATION_FEE_PCT = 0.40
INTL_COORDINATION_FEE_PCT = 0.08
DISCOUNT_TIER_1_CENTS = 2_500_000
DISCOUNT_TIER_1_PCT = 0.05
DISCOUNT_TIER_2_CENTS = 4_000_000
DISCOUNT_TIER_2_PCT = 0.09
PROVISIONAL_ASSUMED_METHOD = "PBSC"
PROVISIONAL_ASSUMED_WINDOW_DAYS = 6

CLAIM_LINE_ORDER = [
    "CT_TYPING",
    "WORKUP_PHYSICAL",
    "IDM_PANEL",
    "COLLECTION",
    "COURIER",
    "DONOR_LOST_WAGE",
    "CANCELLATION",
]

# ---- pagination --------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# ---- logical clock -----------------------------------------------------------
# The server-held logical UTC clock reads this instant before any call is made.
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# The canonical timeline used across the composite setup helpers.  Every value
# is chosen so that the happy path satisfies each temporal precondition:
#   * clearance is resulted on 2026-09-11, so the IDM panel expires 2026-10-11
#   * conditioning starts 2026-10-05, opening collection dates 10-11 .. 10-13
#   * the collection slot sits on 2026-10-11, the last valid IDM day
TIMELINE = {
    "CLEARANCE_AT": "2026-09-11T08:00:00Z",
    "IDM_EXPIRES_AT": "2026-10-11T08:00:00Z",
    "CONDITIONING_START_DATE": "2026-10-05",
    "WINDOW_OPEN_DATE": "2026-10-11",
    "WINDOW_MID_DATE": "2026-10-12",
    "WINDOW_CLOSE_DATE": "2026-10-13",
    "CONDITIONING_START_AT": "2026-10-05T06:00:00Z",
    "BOOKING_START_AT": "2026-10-11T08:00:00Z",
    "COLLECTED_AT": "2026-10-11T13:00:00Z",
    "PBSC_MUST_INFUSE_BY": "2026-10-14T13:00:00Z",
    "DELIVERY_AT": "2026-10-12T09:00:00Z",
}

# ---- test payload defaults ---------------------------------------------------
TEST_DEFAULTS = {
    "PATIENT_BUDGET_CENTS": 5_000_000,
    "DONOR_WEIGHT_KG": 68.0,
    "PATIENT_WEIGHT_KG": 70.0,
    "CT_DEADLINE_HOURS": 168,
    "ADEQUATE_CD34": 5.20,
    "COLLECTED_VOLUME_ML": 320.0,
}
