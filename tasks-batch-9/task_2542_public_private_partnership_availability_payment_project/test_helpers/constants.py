"""Domain thresholds and numeric constants taken from the PRD's stated formulas."""

# --- Charge derivation -------------------------------------------------------
MONTHS_PER_YEAR = 12

# --- Performance points ------------------------------------------------------
UNAVAILABILITY_POINTS_PER_MINUTE = 2
CATEGORY_A_POINTS = 40
CATEGORY_B_POINTS = 10

# --- Self-report variance ----------------------------------------------------
SELF_REPORT_VARIANCE_TOLERANCE_PCT = 0.05
UNDERSTATEMENT_UPLIFT_PCT = 0.25

# --- Deduction money ---------------------------------------------------------
DEDUCTION_POINT_VALUE_CENTS = 1250
ANNUAL_DEDUCTION_CAP_PCT = 0.10
PERSISTENT_BREACH_POINTS_THRESHOLD = 500

# --- Drawdown / construction -------------------------------------------------
EQUITY_FIRST_PCT = 0.30
CONSTRUCTION_START_PCT = 0.30
CONSTRUCTION_SEED_PCT = 0.02

# --- Handback ----------------------------------------------------------------
HANDBACK_SHORTFALL_PENALTY_PCT = 0.15

# --- Refinancing gain share --------------------------------------------------
TIER1_MASP_MULTIPLE = 0.5
TIER2_MASP_MULTIPLE = 1.5
TIER1_AUTHORITY_PCT = 0.30
TIER2_AUTHORITY_PCT = 0.50
TIER3_AUTHORITY_PCT = 0.60
RESERVE_SWEEP_PCT = 0.25

# --- Termination compensation ------------------------------------------------
MONTH_BASIS_DAYS = 30
BPS_DIVISOR = 10000
AUTHORITY_DEFAULT_UPLIFT_PCT = 0.10

# --- Contractual time windows ------------------------------------------------
RELIEF_NOTIFICATION_WINDOW_DAYS = 20
RELIEF_CLAIM_BUFFER_DAYS = 3
RELIEF_DAYS_ANNUAL_CAP = 60
CURE_PERIOD_DAYS = 90
DISPUTE_MAX_ROUNDS = 3

# --- Logical clock -----------------------------------------------------------
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# --- Shared fixture literals used across the suite ---------------------------
# One reference project, sized so that every derived figure below is exact.
TEST_DEFAULTS = {
    "CONCESSIONAIRE_LEGAL_NAME": "Meridian Infrastructure Partners",
    "SPONSOR_EQUITY_COMMITMENT_CENTS": 100000000,
    "PROJECT_NAME": "A47 Availability Scheme",
    "MASP_CENTS": 100000000,
    "INDEXATION_PCT": 0.0325,
    "DEDUCTION_CAP_PCT": 0.20,
    "TOTAL_PROJECT_COST_CENTS": 400000000,
    "SENIOR_DEBT_COMMITTED_CENTS": 300000000,
    "EQUITY_COMMITTED_CENTS": 100000000,
    "BASE_CASE_EQUITY_IRR_BPS": 1200,
    "SCHEDULED_SERVICE_COMMENCEMENT": "2027-01-01",
    "LD_DAILY_RATE_CENTS": 250000,
    "LD_CAP_CENTS": 5000000,
    "LIFECYCLE_RESERVE_TARGET_CENTS": 20000000,
    # Derived from the figures above by the PRD's own formulas.
    "MONTHLY_UNITARY_CHARGE_CENTS": 8604167,
    "PERIOD_ONE_START": "2027-03-01",
    "PERIOD_ONE_END": "2027-04-01",
    "PERIOD_ONE_DAYS": 31,
    "PERIOD_ONE_DEDUCTION_CAP_CENTS": 1720833,
    "ANNUAL_DEDUCTION_CAP_CENTS": 10000000,
    "CONSTRUCTION_SEED_CENTS": 8000000,
}

# Clock instants the reference chain walks through.
CLOCK_DRAFTING = "2026-09-01T00:00:00Z"
CLOCK_COMMENCEMENT = "2027-01-21T00:00:00Z"
CLOCK_AFTER_PERIOD_ONE = "2027-04-02T00:00:00Z"

FINANCIAL_CLOSE_DATE = "2026-09-15"
ACTUAL_COMMENCEMENT_DATE = "2027-01-21"
