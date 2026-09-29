"""Numeric constants and thresholds stated verbatim in the PRD."""

# --- Logical clock (PRD §2.4) ------------------------------------------------
# "Before any client sets it, the logical clock reads exactly
# 2026-08-01T00:00:00Z - a fixed server startup default".
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# --- Pagination (PRD §2.3) ---------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Financial minimums at acceptance (PRD §3.1) -----------------------------
MIN_EO_LIMIT_CENTS = 25_000_000
MIN_NET_WORTH_CENTS = 5_000_000

# --- Oversight posture thresholds (PRD §2.6) ---------------------------------
UNREPORTED_POLICY_RESTRICT_THRESHOLD = 3
UNREMITTED_TOLERANCE_CENTS = 50_000_000

# --- Closing protection coverage caps (PRD §3.3) ----------------------------
SCOPE_FACTORS = {
    "FULL_SETTLEMENT": 1.00,
    "LENDER_ONLY": 0.80,
    "SELLER_PROCEEDS": 0.60,
}
RESTRICTED_POSTURE_CAP_FACTOR = 0.50
EO_SUBLIMIT_FACTOR = 0.50

# --- Remittance penalties (PRD §3.5) ----------------------------------------
REMITTANCE_GRACE_DAYS = 15
LATE_FILING_FEE_CENTS = 25_000
UNREPORTED_PENALTY_PCT = 0.10

# --- Audit finding severity bands (PRD §3.7) --------------------------------
THREE_WAY_VARIANCE_LOW_CEILING_CENTS = 100_000
THREE_WAY_VARIANCE_MEDIUM_CEILING_CENTS = 1_000_000
THREE_WAY_VARIANCE_HIGH_CEILING_CENTS = 5_000_000
UNIDENTIFIED_FUNDS_MEDIUM_CEILING_CENTS = 500_000
SEVERITY_LADDER = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

# --- Defalcation score weights and bands (PRD §3.7) -------------------------
CRITICAL_FINDING_WEIGHT = 25
HIGH_FINDING_WEIGHT = 12
ADVERSE_CLOSURE_WEIGHT = 8
DEFALCATION_CLAIM_WEIGHT = 15
DEFALCATION_SCORE_CAP = 100
DEFALCATION_RISK_THRESHOLD = 60
WATCH_THRESHOLD = 30
ROLLING_WINDOW_DAYS = 365

# --- Escrow audit spacing (PRD §3.6) ---------------------------------------
AUDIT_SPACING_DAYS = 90

# --- Claim recourse waterfall (PRD §3.8) ------------------------------------
TIER_1_RATIO_CEILING = 0.25
TIER_2_RATIO_CEILING = 0.60
PARTICIPATION_SHARES = {"TIER_1": 0.50, "TIER_2": 0.75, "TIER_3": 1.00}
CAUSE_FACTORS = {
    "AGENCY_ERROR": 0.60,
    "SEARCH_DEFECT": 0.40,
    "UNDERWRITING_BREACH": 0.80,
    "ESCROW_DEFALCATION": 1.00,
}

# --- Cascade actor sentinel (PRD §3.3, §3.7) --------------------------------
SYSTEM_ACTOR = "SYSTEM"

# --- Shared fixture defaults ------------------------------------------------
# The reference state program: letters permitted, all three scopes allowed, an
# agency retention fraction of 0.800, a thirty-day issuance deadline, a
# reconciliation tolerance of 100,000 cents and a counsel referral threshold of
# 60,000,000 cents.
TEST_DEFAULTS = {
    "CPL_COVERAGE_CAP_CENTS": 100_000_000,
    "PREMIUM_SPLIT_AGENCY_PCT": 0.80,
    "POLICY_ISSUANCE_DEADLINE_DAYS": 30,
    "THREE_WAY_TOLERANCE_CENTS": 100_000,
    "COUNSEL_REFERRAL_THRESHOLD_CENTS": 60_000_000,
    "UNDERWRITING_AUTHORITY_LIMIT_CENTS": 50_000_000,
    "SUBMITTED_EO_POLICY_LIMIT_CENTS": 200_000_000,
    "SUBMITTED_EO_EXPIRES_ON": "2027-06-30",
    "SUBMITTED_NET_WORTH_CENTS": 20_000_000,
    "SUBMITTED_FIDELITY_BOND_CENTS": 10_000_000,
    "LICENSE_EXPIRES_ON": "2027-12-31",
    "VERIFIED_EXPIRES_ON": "2027-12-31",
}
