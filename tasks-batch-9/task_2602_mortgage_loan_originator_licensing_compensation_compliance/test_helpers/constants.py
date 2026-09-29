"""Domain thresholds and pinned numeric constants from the PRD's arithmetic.

Every value here is stated in PRD.md prose; nothing is invented by the tests.
"""

# --- The logical compliance clock (PRD 2.4) -------------------------------
CLOCK_STARTUP_INSTANT = "2026-08-01T00:00:00Z"

# --- Money / basis points (PRD 2.6) --------------------------------------
BPS_DENOMINATOR = 10_000
SECONDS_PER_DAY = 86_400

# --- Continuing education (PRD 3.2) -------------------------------------
CE = {
    "DEFAULT_REQUIRED_HOURS": 8,
    "MIN_REQUIRED_HOURS": 8,
    "MAX_REQUIRED_HOURS": 20,
    "REQUIRED_FEDERAL_LAW_HOURS": 3,
    "REQUIRED_ETHICS_HOURS": 2,
    "REQUIRED_NONTRADITIONAL_HOURS": 2,
    "MIN_CREDIT_HOURS": 1,
    "MAX_CREDIT_HOURS": 12,
    "MIN_REPORTING_YEAR": 2020,
    "MAX_REPORTING_YEAR": 2100,
}

# --- Renewal / reinstatement roll-forward (PRD 3.2) ---------------------
RENEWAL = {
    "EXPIRATION_ROLL_FORWARD_DAYS": 365,
    "WINDOW_ROLL_FORWARD_DAYS": 365,
    "REINSTATEMENT_EXPIRATION_DAYS": 365,
    "REINSTATEMENT_WINDOW_DAYS": 305,
    "REINSTATEMENT_ALLOWANCE": 2,
}

# --- Volume tier basis-point adder (PRD 3.5) ----------------------------
VOLUME_TIER = {
    "TIER1_MAX_UNITS": 4,
    "TIER2_MAX_UNITS": 9,
    "TIER1_BPS": 0,
    "TIER2_BPS": 15,
    "TIER3_BPS": 30,
    "QUALITY_FULL_MIN": 90,
    "QUALITY_PARTIAL_MIN": 70,
    "QUALITY_PARTIAL_PENALTY_BPS": 10,
    "QUALITY_FAIL_PENALTY_BPS": 25,
    "CLAMP_MAX_BPS": 30,
    "HOURS_MIN_PCT": 50,
    "HOURS_CAP_BPS": 15,
}

# --- Concession absorption (PRD 3.6) ------------------------------------
CONCESSION = {
    "BRACKET_CENTS": 300_000,
    "ABSORB_HIGH_PCT": 50,
    "ABSORB_LOW_PCT": 25,
    "CAP_NUMERATOR": 2,
    "CAP_DENOMINATOR": 100,
    "PRICING_ERROR_MIN_JUSTIFICATION_CHARS": 120,
    "MIN_JUSTIFICATION_CHARS": 40,
    "MAX_JUSTIFICATION_CHARS": 2_000,
    "MIN_CONCESSION_CENTS": 1,
    "MAX_CONCESSION_CENTS": 2_000_000,
}


def concession_cap_cents(locked_amount_cents: int) -> int:
    """Two percent of the locked amount, floored to a whole cent (PRD 3.6)."""
    return (locked_amount_cents * CONCESSION["CAP_NUMERATOR"]) // CONCESSION["CAP_DENOMINATOR"]


# --- Early payoff clawback (PRD 3.7) ------------------------------------
CLAWBACK = {
    "INNER_DAYS": 90,
    "OUTER_DAYS": 180,
    "INNER_RECAPTURE_PCT": 100,
    "OUTER_RECAPTURE_PCT": 50,
    "NO_RECAPTURE_PCT": 0,
}

# --- Steering / dual-compensation exposure score (PRD 3.7) --------------
EXPOSURE = {
    "DUAL_WEIGHT": 0.35,
    "SPREAD_WEIGHT": 0.25,
    "EXCEPTION_WEIGHT": 0.15,
    "CLAWBACK_WEIGHT": 0.25,
    "SPREAD_CAP_BPS": 100,
    "ELEVATED_THRESHOLD": 60,
    "SCORE_MIN": 0,
    "SCORE_MAX": 100,
}

# --- Advertising disclosure inspection (PRD 3.8) ------------------------
ADVERTISING = {
    "RADIO_SCRIPT_MAX_CHARS": 300,
    "TRIGGER_PHRASE": "no closing cost",
    "APR_TOKEN": "APR",
    "MIN_CONTENT_CHARS": 10,
    "MAX_CONTENT_CHARS": 4_000,
    "MIN_TARGET_STATES": 1,
    "MAX_TARGET_STATES": 10,
}

# --- Examinations (PRD 3.9) --------------------------------------------
EXAMINATION = {
    "ROUND_LIMIT": 3,
    "INFO_REQUEST_EXTENSION_DAYS": 14,
}

# --- Pagination (PRD 2.3) ---------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "DEFAULT_OFFSET": 0,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
}

# --- Input range bounds declared in PRD 3.1 - 3.9 ---------------------
RANGES = {
    "NMLS_MIN_DIGITS": 6,
    "NMLS_MAX_DIGITS": 8,
    "LEGAL_NAME_MIN": 1,
    "LEGAL_NAME_MAX": 120,
    "LICENSE_NUMBER_MIN": 4,
    "LICENSE_NUMBER_MAX": 32,
    "INSTITUTION_CODE_MIN": 4,
    "INSTITUTION_CODE_MAX": 12,
    "COURSE_CODE_MIN": 4,
    "COURSE_CODE_MAX": 24,
    "PLAN_NAME_MIN": 1,
    "PLAN_NAME_MAX": 80,
    "BASE_BPS_MIN": 0,
    "BASE_BPS_MAX": 275,
    "WEIGHT_PCT_MIN": 0,
    "WEIGHT_PCT_MAX": 100,
    "VARIABLE_JUSTIFICATION_MIN": 20,
    "VARIABLE_JUSTIFICATION_MAX": 1_000,
    "BORROWER_REFERENCE_MIN": 1,
    "BORROWER_REFERENCE_MAX": 40,
    "REQUESTED_AMOUNT_MIN_CENTS": 1_000_000,
    "REQUESTED_AMOUNT_MAX_CENTS": 500_000_000,
    "RATE_BPS_MIN": 100,
    "RATE_BPS_MAX": 2_000,
    "SCORE_MIN": 0,
    "SCORE_MAX": 100,
    "EXAM_REFERENCE_MIN": 4,
    "EXAM_REFERENCE_MAX": 32,
    "PLAN_WEIGHT_TOTAL": 100,
}

# --- Convenient test defaults ----------------------------------------
TEST_DEFAULTS = {
    "STATE_CODE": "CA",
    "SECOND_STATE_CODE": "NV",
    "INSTITUTION_CODE": "INST-ALPHA",
    "SECOND_INSTITUTION_CODE": "INST-BETA",
    "PRODUCT_TYPE": "FIXED_30",
    "PAR_RATE_BPS": 650,
    "REQUESTED_AMOUNT_CENTS": 20_000_000,
    "LOCKED_AMOUNT_CENTS": 20_000_000,
    "FUNDED_AMOUNT_CENTS": 20_000_000,
    "BASE_BASIS_POINTS": 200,
    "MIN_FEE_CENTS": 100_000,
    "MAX_FEE_CENTS": 900_000,
    "FILE_QUALITY_SCORE": 95,
    "HOURS_WORKED_PCT": 80,
    "CE_REPORTING_YEAR": 2026,
    "REQUIRED_CE_HOURS": 8,
}

PERMISSIBLE_VARIABLE_TYPES = [
    "LOAN_VOLUME_UNITS",
    "LOAN_VOLUME_DOLLARS",
    "PERCENTAGE_OF_LOAN_AMOUNT",
    "HOURS_WORKED",
    "FILE_QUALITY_SCORE",
    "EXISTING_BORROWER_FLAG",
]

PROHIBITED_VARIABLE_TYPES = [
    "INTEREST_RATE",
    "APR",
    "LOAN_TERM_MONTHS",
    "LTV_RATIO",
    "CREDIT_SCORE",
    "PRODUCT_TYPE",
    "PREPAYMENT_PENALTY_FLAG",
    "LOAN_PROFITABILITY",
]
