"""Domain thresholds and weights taken from the PRD's calculations."""

# --- Composite credit score (PRD §3.3) ---------------------------------------
BUREAU_WEIGHT = {"EQUIFAX": 0.35, "EXPERIAN": 0.35, "TRANSUNION": 0.30}
CREDIT_SCORE_MIN = 300
CREDIT_SCORE_MAX = 850

# --- Identity risk score (PRD §3.5) ------------------------------------------
RISK_BASE = 10
TYPE_WEIGHT = {
    "SSN_TRACE": 25,
    "ACCOUNT_TAKEOVER": 20,
    "DARK_WEB": 15,
    "CREDIT_INQUIRY": 8,
}
ESCALATION_WEIGHT = 10
SCORE_DROP_WEIGHT = 12
SCORE_DROP_THRESHOLD = 40
FAMILY_CHILD_MULTIPLIER = 1.20
SCORE_CEILING = 100
SCORE_FLOOR = 0

# --- Escalation tiering (PRD §3.5) -------------------------------------------
TIER2_RISK_THRESHOLD = 40
TIER3_RISK_THRESHOLD = 70
SLA_HOURS = {"TIER1": 72, "TIER2": 24, "TIER3": 4}

# --- Specialist tier ranking (PRD §3.6) --------------------------------------
TIER_RANK = {"TIER1": 1, "TIER2": 2, "TIER3": 3}
ENGAGEMENT_BUFFER_MINUTES = 60

# --- Claim reimbursement (PRD §3.7) ------------------------------------------
COVERAGE_PCT = {
    "LEGAL_FEES": 1.00,
    "LOST_WAGES": 0.80,
    "TRAVEL": 0.50,
    "CHILDCARE": 0.50,
    "NOTARY": 1.00,
    "POSTAGE": 1.00,
}
CATEGORY_SUBLIMIT_CENTS = {"LOST_WAGES": 250_000, "TRAVEL": 100_000, "CHILDCARE": 100_000}
UNDOCUMENTED_FACTOR_PROVISIONAL = 0.50
UNDOCUMENTED_FACTOR_FINAL = 0.00
DEDUCTIBLE_CENTS = 2_500

# --- Insurance gating (PRD §3.7) ---------------------------------------------
UNDERWRITING_RISK_MAX = 75
EXHAUSTION_THRESHOLD_CENTS = 0

# --- Logical clock (PRD §2.4) ------------------------------------------------
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# --- Test defaults -----------------------------------------------------------
TEST_DEFAULTS = {
    "INSURANCE_LIMIT_CENTS": 500_000,
    "MONTHLY_FEE_CENTS": 3_499,
    "MAX_FAMILY_MEMBERS": 4,
    "MAX_CASELOAD": 3,
    "MAX_CONCURRENT_ENGAGEMENTS": 1,
}