"""Domain thresholds and numeric constants stated in the PRD.

Every value here is quoted verbatim from PRD prose (§2.x global rules and §3.x
workflows). Generic helpers such as NON_EXISTENT_UUID come from the framework.
"""

API_PREFIX = "/nature-center"

# --- §2.5 The logical program clock -------------------------------------------------
# "Before any call to POST /_clock/set_current_utc, the logical clock reads exactly
# 2026-08-01T00:00:00Z"
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# The instant the canonical scenarios pin the clock to: a Monday 07:00 UTC, so the
# ISO program week runs [2026-09-28T00:00:00Z, 2026-10-05T00:00:00Z).
DEFAULT_CLOCK = "2026-09-28T07:00:00Z"

# --- §2.3 Pagination ----------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- §3.2 Equity tiers --------------------------------------------------------------
EQUITY_TIER_1_MIN_TITLE_I_PCT = 0.75
EQUITY_TIER_2_MIN_TITLE_I_PCT = 0.50
EQUITY_TIER_3_MIN_TITLE_I_PCT = 0.25

# --- §3.2 Partnership standing ------------------------------------------------------
SCHOOL_PROBATION_STRIKES = 1
SCHOOL_SUSPENSION_STRIKES = 2

# --- §3.3 Staffing ------------------------------------------------------------------
TRAINING_VALIDITY_DAYS = 365
MIN_PASSING_SCORE = 70
MAX_TRAINING_ATTEMPTS = 3
EDUCATOR_WEEKLY_CAP_MINUTES = {
    "SEASONAL_EDUCATOR": 360,
    "STAFF_NATURALIST": 600,
}

# --- §3.4 Animal welfare ------------------------------------------------------------
WELFARE_RESTRICTED_PCT = 0.60

# --- §3.5 Trails --------------------------------------------------------------------
DEFAULT_RECOVERY_BUFFER_MINUTES = 30
HIGH_SENSITIVITY_MAX_PERSONS = 25

# --- §3.6 Educator travel buffers ---------------------------------------------------
EDUCATOR_TRAVEL_BUFFER_MINUTES = {
    "ONSITE_FIELD_TRIP": 45,
    "VIRTUAL": 45,
    "OUTREACH_AT_SCHOOL": 60,
}

# --- §3.8 Fee assessment ------------------------------------------------------------
MIN_BILLABLE_STUDENTS = 10
VOLUME_DISCOUNT_BANDS = (
    (1, 14, 0.00),
    (15, 29, 0.05),
    (30, 59, 0.10),
    (60, None, 0.15),
)
TRAVEL_BASE_CENTS = 4000
TRAVEL_PER_MILE_CENTS = 175
BOX_TRUCK_TRAVEL_MULTIPLIER = 2.0
VAN_TRAVEL_MULTIPLIER = 1.0
RAIN_DIVERT_CREDIT_PCT = 0.20

# --- §3.8 Award waterfall -----------------------------------------------------------
TIER_CAP_PCT = {
    "TIER_1": 1.00,
    "TIER_2": 0.70,
    "TIER_3": 0.40,
    "NONE": 0.00,
}
MIN_SCHOOL_CONTRIBUTION_CENTS_PER_STUDENT = 150
TRANSPORT_PER_MILE_CENTS = 260
DEFAULT_TRANSPORT_SUBLIMIT_PCT = 0.25

# --- §3.7 No-show -------------------------------------------------------------------
NO_SHOW_FEE_CENTS = 7500

# --- §3.9 Equipment manifests -------------------------------------------------------
VEHICLE_CLASS_WEIGHT_THRESHOLD_KG = 250

# --- §3.9 Learning gain index -------------------------------------------------------
MAX_ASSESSMENT_SCORE = 20
TEACHER_WEIGHT_STANDARDS_ALIGNMENT = 0.50
TEACHER_WEIGHT_ENGAGEMENT = 0.30
TEACHER_WEIGHT_LOGISTICS = 0.20
TEACHER_SCALE_MAX = 5
GAIN_WEIGHT = 0.60
TEACHER_WEIGHT = 0.40
FIDELITY_DELIVERED = 1.00
FIDELITY_RAIN_DIVERTED = 0.80
FIDELITY_NOT_DELIVERED = 0.00
THIN_ALIGNMENT_PENALTY = 0.90
THIN_ALIGNMENT_THRESHOLD = 3

# --- Canonical test payload values shared across scenarios --------------------------
TEST_DEFAULTS = {
    "OFFERING_TITLE": "Pond Ecology Field Study",
    "GRADE_BAND": "G3_5",
    "DELIVERY_MODE": "ONSITE_FIELD_TRIP",
    "DURATION_MINUTES": 120,
    "MAX_GROUP_SIZE": 60,
    "MIN_CHAPERONE_RATIO": 10,
    "BASE_FEE_CENTS_PER_STUDENT": 1233,
    "SCHOOL_NAME": "Cedar Grove Elementary",
    "DISTRICT_CODE": "LEA-77",
    "TITLE_I_PCT": 0.82,
    "DISTANCE_MILES": 12.5,
    "EDUCATOR_NAME": "Rae Alder",
    "PERMIT_AGENCY": "USFWS",
    "PERMIT_NUMBER": "MB-2026-118",
    "PERMIT_VALID_FROM": "2026-01-01T00:00:00Z",
    "PERMIT_VALID_TO": "2027-12-31T00:00:00Z",
    "ANIMAL_COMMON_NAME": "Eastern Screech Owl",
    "ANIMAL_SPECIES_CODE": "MEAS",
    "ANIMAL_CAP_MINUTES": 240,
    "TRAIL_NAME": "Oxbow Loop",
    "TRAIL_CAPACITY_PERSONS": 40,
    "TRAIL_WEEKLY_BUDGET_PERSONS": 200,
    "FUNDER_NAME": "Riverbend Foundation",
    "FISCAL_YEAR": 2027,
    "FUND_TOTAL_CENTS": 5000000,
    "BOOKING_START_UTC": "2026-09-29T14:00:00Z",
    "BOOKING_END_UTC": "2026-09-29T16:00:00Z",
    "STUDENT_COUNT": 30,
    "CHAPERONE_COUNT": 3,
}
