"""Domain thresholds and numeric constants stated by the PRD."""

API_PREFIX = "/wbl"

# The logical clock's startup default.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# --- Wage settlement -------------------------------------------------------
MIN_WAGE_CENTS = 1500
LEARNER_WAGE_FLOOR_CENTS = 1275

# --- Academic credit -------------------------------------------------------
HOURS_PER_HALF_CREDIT = 45
CREDIT_BLOCK_VALUE = 0.50
MAX_RATING = 5.00
COMPETENCY_WEIGHTS = {
    "rating_technical": 0.30,
    "rating_communication": 0.20,
    "rating_reliability": 0.20,
    "rating_safety": 0.20,
    "rating_initiative": 0.10,
}

# --- Child-labor hour ledger ----------------------------------------------
CHILD_LABOR_BANDS = {
    "MINOR_14_15": {
        "earliest_start": "07:00",
        "night_cutoff": "19:00",
        "daily_school_day": 3.00,
        "daily_non_school_day": 8.00,
        "weekly_school_day": 18.00,
        "weekly_non_school_day": 40.00,
    },
    "MINOR_16_17": {
        "earliest_start": "06:00",
        "night_cutoff": "22:00",
        "daily_school_day": 4.00,
        "daily_non_school_day": 8.00,
        "weekly_school_day": 28.00,
        "weekly_non_school_day": 48.00,
    },
}
TRAVEL_BUFFER_MINUTES = 30

# --- Employer safety score / posture --------------------------------------
SAFETY_PENALTY_MINOR = 15
SAFETY_PENALTY_MODERATE = 30
SAFETY_PENALTY_CRITICAL = 50
SAFETY_PENALTY_CONDITIONAL_SITE = 10
SAFETY_SCORE_MIN = 0
SAFETY_SCORE_MAX = 100
POSTURE_SUSPEND_BELOW = 50
POSTURE_PROBATION_BELOW = 70

# --- Reimbursement ---------------------------------------------------------
TRANSIT_PASS_BLOCK_CENTS = 4500
TRANSIT_PASS_BLOCK_DAYS = 30
MILEAGE_CENTS_PER_MILE = 50
GUARDIAN_FACTOR = 0.65
SUPERVISOR_STIPEND_PER_CLOSED_CYCLE_CENTS = 7500
TIER_1_MAX_CENTS = 20000
TIER_1_RATE = 0.10
TIER_2_MAX_CENTS = 50000
TIER_2_RATE = 0.075
TIER_3_RATE = 0.05

# --- Student eligibility ---------------------------------------------------
MIN_GRADE_LEVEL = 10
MIN_GPA = 2.00
MIN_ATTENDANCE = 0.90

# --- Plan / negotiation limits --------------------------------------------
MIN_OBJECTIVES = 3
MIN_ALIGNED_OBJECTIVES = 3
MAX_REVISION_ROUNDS = 3
MAX_REFLECTION_RETURNS = 2

# --- Validity windows ------------------------------------------------------
SAFETY_REVIEW_VALID_DAYS = 365
CONDITIONAL_CORRECTIVE_ACTION_DAYS = 30
SUPERVISOR_TRAINING_VALID_DAYS = 365
EVALUATION_CYCLE_LENGTH_DAYS = 28
EVALUATION_CYCLE_WINDOW_OFFSET_DAYS = 27
OUTCOME_REPORTING_WINDOW_DAYS = 180
OUTCOME_RATE_DECIMALS = 4

# --- Placement declaration ranges -----------------------------------------
DEFAULT_REQUIRED_EVALUATION_CYCLES = 2
MIN_REQUIRED_EVALUATION_CYCLES = 1
MAX_REQUIRED_EVALUATION_CYCLES = 4
MIN_CREDIT_TARGET_CREDITS = 0.50
MAX_CREDIT_TARGET_CREDITS = 2.00
CREDIT_TARGET_STEP = 0.50

# --- Pagination ------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Handy fake identifiers for 404 probes ---------------------------------
UNKNOWN_WORKSITE_ID = "11111111-2222-4333-8444-555555555555"
UNKNOWN_STUDENT_ID = "99999999-8888-4777-8666-555555555555"
UNKNOWN_PERMIT_ID = "44444444-3333-4222-8111-000000000000"
UNKNOWN_EMPLOYER_ID = "22222222-3333-4444-8555-666666666666"
UNKNOWN_SUPERVISOR_ID = "33333333-4444-4555-8666-777777777777"
UNKNOWN_AGREEMENT_ID = "55555555-6666-4777-8888-999999999999"
UNKNOWN_PLACEMENT_ID = "66666666-7777-4888-8999-000000000000"
