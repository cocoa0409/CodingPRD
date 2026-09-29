"""
Domain constants for the WIC vendor authorization and competitive price API.

Every value here is stated in the PRD; nothing is invented. Tests import these
names instead of repeating magic numbers so a reader can trace each literal back
to the sentence that fixes it.
"""

# --- Logical clock (PRD 2.5) -------------------------------------------------
# "Before any client sets it, the logical clock reads exactly 2026-08-01T00:00:00Z"
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_LOGICAL_CLOCK_ISO = "2026-08-01T00:00:00.000Z"

# --- Pagination (PRD 2.3) ---------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Peer group configuration bounds (PRD 3.1) ------------------------------
DEFAULT_MIN_SUBMISSIONS_FOR_CEILING = 3
MIN_COMPETITIVE_ALLOWANCE_PCT = 0.0
MAX_COMPETITIVE_ALLOWANCE_PCT = 0.25
MIN_STOCK_MULTIPLIER_FLOOR = 0.5
MIN_STOCK_MULTIPLIER_CEILING = 3.0
PEER_GROUP_CODE_MAX_LENGTH = 32

# --- Authorized food list (PRD 3.1) ----------------------------------------
UPC_MIN_DIGITS = 8
UPC_MAX_DIGITS = 14

# --- Peer group assignment (PRD 3.2) ---------------------------------------
# "a null upper bound is treated as the sentinel value of one trillion cents"
UNBOUNDED_BAND_SENTINEL_CENTS = 1_000_000_000_000

# --- Training currency (PRD 3.2) -------------------------------------------
TRAINING_VALID_MONTHS = 12

# --- Maximum allowable reimbursement derivation (PRD 3.4) ------------------
# "the statewide cap is computed second, as 1.25 times the smallest price"
STATEWIDE_CAP_MULTIPLE = 1.25

# --- Authorization and reauthorization (PRD 3.5) ---------------------------
REAUTH_CYCLE_MONTHS = 36
REAUTH_WINDOW_DAYS = 90
AVG_REDEMPTION_MONTHS = 6

# --- Monitoring visits (PRD 3.6) -------------------------------------------
MONITORING_BLACKOUT_DAYS = 7
CURE_PERIOD_DAYS = 30
HIGH_RISK_FINDING_THRESHOLD = 2
COMPLIANCE_BUY_LEAD_DAYS = 14

# --- Price submission revisions (PRD 3.3) ----------------------------------
MAX_SUBMISSION_REVISIONS = 2

# --- Risk score (PRD 3.9) --------------------------------------------------
RISK_WINDOW_DAYS = 180
W_EDIT = 0.40
W_PRICE = 0.25
W_VISIT = 0.20
POINT_WEIGHT = 15.0
POINT_CAP = 2
ELEVATED_TIER_MIN = 30.0
HIGH_TIER_MIN = 60.0
MAX_RISK_SCORE = 100.0

# --- Sanction schedule (PRD 3.9) -------------------------------------------
BASE_TIER_BY_VIOLATION = {
    "CLASS_A": 4,
    "CLASS_B": 3,
    "CLASS_C": 2,
    "CLASS_D": 1,
}
POINTS_BY_BASE_TIER = {1: 1, 2: 2, 3: 4, 4: 8}
ESCALATION_THRESHOLDS = [4, 8]
DISQ_MONTHS_BY_TIER = {1: 0, 2: 6, 3: 12, 4: 36}
CMP_MULTIPLIER_BY_TIER = {1: 0.05, 2: 0.10, 3: 0.25, 4: 0.50}
CMP_MONTHS_BY_TIER = {1: 1, 2: 3, 3: 6, 4: 12}
CMP_CAP_CENTS = 5_625_000
CMP_ELECTION_DAYS = 15
MAX_EFFECTIVE_TIER = 4
