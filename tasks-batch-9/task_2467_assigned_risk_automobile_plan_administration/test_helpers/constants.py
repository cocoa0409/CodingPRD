"""Domain thresholds and pre-computed rating figures stated by the PRD."""

# --- Surcharge points -----------------------------------------------------
VIOLATION_POINTS = {
    "SPEEDING_MINOR": 1,
    "SPEEDING_MAJOR": 3,
    "AT_FAULT_ACCIDENT": 3,
    "LICENSE_SUSPENSION": 4,
    "RECKLESS_DRIVING": 5,
    "DUI": 8,
}
DRIVER_CLASS_POINT_ADDER = {"ADULT": 0, "SENIOR": 1, "YOUTHFUL_OPERATOR": 3}
POINTS_CAP = 15
EXPERIENCE_WINDOW_DAYS = 1095

# --- Annual premium -------------------------------------------------------
TERRITORY_BASE_ANNUAL_CENTS = {"T01": 96475, "T02": 148337, "T03": 231909}
LINE_SHARES = {"BI": 0.55, "PD": 0.30, "UM": 0.15}
CLASS_FACTORS = {"PLEASURE": 1.00, "WORK_LT10": 1.10, "WORK_GE10": 1.25, "BUSINESS": 1.45}
SURCHARGE_FACTOR = {"0": 1.00, "1-3": 1.15, "4-5": 1.35, "6-9": 1.60, "10+": 1.90}

# --- Plan expense charge --------------------------------------------------
EXPENSE_TIER_1_CEILING_CENTS = 75000
EXPENSE_TIER_2_CEILING_CENTS = 150000
EXPENSE_RATE_TIER_1 = 0.06
EXPENSE_RATE_TIER_2 = 0.05
EXPENSE_RATE_TIER_3 = 0.04

# --- Deposit --------------------------------------------------------------
DEPOSIT_PERCENT = 0.25
DEPOSIT_FLOOR_CENTS = 15000

# --- Cancellation settlement ---------------------------------------------
DAYS_PER_YEAR = 365
SHORT_RATE_PENALTY_MULTIPLIER = 1.1
SHORT_RATE_MINIMUM_CENTS = 5000

# --- Selector and acceptance window --------------------------------------
ACCEPTANCE_WINDOW_DAYS = 10

# --- Clean years ----------------------------------------------------------
CLEAN_YEARS_CAP = 5
VOLUNTARY_EXIT_MIN_CLEAN_YEARS = 3

# --- Exposure -------------------------------------------------------------
CAR_YEAR_DECIMALS = 4

# --- Reconciliation -------------------------------------------------------
DEFICIENCY_PENALTY_CENTS_PER_UNIT = 25000

# --- Performance score and posture ladder --------------------------------
SCORE_START = 100
SCORE_FLOOR = 0
SCORE_CEILING = 100
ACK_BREACH_DEDUCTION = 5
UPHELD_COMPLAINT_DEDUCTION = 20
MISSED_ISSUANCE_DEDUCTION = 5
PERIOD_CLOSURE_RECOVERY = 10
SUSPENSION_SCORE_CEILING = 70
RESTRICTION_SCORE_CEILING = 85
BREACH_RESTRICTION_THRESHOLD = 3

# --- Voluntary writing credit --------------------------------------------
STANDARD_CREDIT_UNITS = 1.0
UNDERSERVED_CREDIT_MULTIPLIER = 1.5

# --- Market rejections ----------------------------------------------------
VOLUNTARY_REJECTION_LOOKBACK_DAYS = 90
MIN_DISTINCT_REJECTIONS = 2

# --- Claim handling and notice windows -----------------------------------
CLAIM_ACKNOWLEDGEMENT_WINDOW_DAYS = 10
NON_RENEWAL_NOTICE_DAYS = 45
EXIT_NOTICE_DAYS = 90
CURE_ROUND_LIMIT = 2
REVIEW_ROUND_LIMIT = 3
RESTRICTED_CANCEL_REASON_WINDOW_DAYS = 60

# --- Pagination -----------------------------------------------------------
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100

# --- Clock ----------------------------------------------------------------
INITIAL_CLOCK = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Pre-computed rating figures for the standard scenarios used by the suite.
# Each figure follows from the PRD's rating chain for the stated risk profile.
# --------------------------------------------------------------------------
# ADULT / PLEASURE / T02, zero surcharge points
T02_ADULT_CLEAN = {
    "premium_lines": {"BI": 81585, "PD": 44501, "UM": 22251},
    "final_premium_cents": 148337,
    "plan_expense_charge_cents": 7417,
    "total_annual_charge_cents": 155754,
    "required_deposit_cents": 38939,
    "surcharge_points": 0,
    "surcharge_factor": 1.00,
}

# YOUTHFUL_OPERATOR / PLEASURE / T02 with one SPEEDING_MAJOR: 6 points
T02_YOUTHFUL_SIX_POINTS = {
    "premium_lines": {"BI": 130537, "PD": 71202, "UM": 35601},
    "final_premium_cents": 237340,
    "plan_expense_charge_cents": 9494,
    "total_annual_charge_cents": 246834,
    "required_deposit_cents": 61709,
    "surcharge_points": 6,
    "surcharge_factor": 1.60,
}

# SENIOR / PLEASURE / T02 with SPEEDING_MINOR + SPEEDING_MAJOR: 5 points
T02_SENIOR_FIVE_POINTS = {
    "premium_lines": {"BI": 110140, "PD": 60076, "UM": 30038},
    "final_premium_cents": 200254,
    "plan_expense_charge_cents": 8010,
    "total_annual_charge_cents": 208264,
    "required_deposit_cents": 52066,
    "surcharge_points": 5,
    "surcharge_factor": 1.35,
}

# Conviction records reused across the suite. Both fall inside the three-year
# experience window for every rating date the suite uses.
SPEEDING_MAJOR_CONVICTION = {"code": "SPEEDING_MAJOR", "conviction_date": "2025-03-10T00:00:00Z"}
SPEEDING_MINOR_CONVICTION = {"code": "SPEEDING_MINOR", "conviction_date": "2025-05-04T00:00:00Z"}

# One SPEEDING_MAJOR (3) plus the YOUTHFUL_OPERATOR adder (3) makes 6 points.
SIX_POINT_VIOLATIONS = [SPEEDING_MAJOR_CONVICTION]
# One SPEEDING_MINOR (1) plus one SPEEDING_MAJOR (3) plus the SENIOR adder (1) makes 5.
FIVE_POINT_VIOLATIONS = [SPEEDING_MINOR_CONVICTION, SPEEDING_MAJOR_CONVICTION]

# ADULT / PLEASURE / T03, zero surcharge points
T03_ADULT_CLEAN = {
    "final_premium_cents": 231909,
    "plan_expense_charge_cents": 9276,
    "total_annual_charge_cents": 241185,
    "required_deposit_cents": 60296,
    "surcharge_points": 0,
    "surcharge_factor": 1.00,
}
