"""Domain thresholds and numeric constants stated in the PRD's calculations."""

# --- Logical clock (PRD §2.6) -------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --- Household-adjusted income limit (PRD §3.1) ------------------------------
HOUSEHOLD_ADJUSTMENT = {
    1: 0.70,
    2: 0.80,
    3: 0.90,
    4: 1.00,
    5: 1.08,
    6: 1.16,
    7: 1.24,
    8: 1.32,
}
PASSBOOK_RATE = 0.004
ASSET_IMPUTATION_FLOOR_CENTS = 500_000
DEPENDENT_DEDUCTION_CENTS = 48_000
ELDERLY_DEDUCTION_CENTS = 40_000
EXTREMELY_LOW_CEILING_PCT = 30.0
VERY_LOW_CEILING_PCT = 50.0
LOW_CEILING_PCT = 80.0

# --- Compliance triggers (PRD §3.2) ------------------------------------------
LEAD_TARGET_HOUSING_YEAR = 1978
LEAD_ACTION_LEVEL_MG_CM2 = 1.00

# --- Write-up estimate roll-up (PRD §3.3) -----------------------------------
LEAD_SAFE_PRACTICE_PCT = 0.15
HISTORIC_PRACTICE_PCT = 0.12
CONTINGENCY_PCT = 0.10

# --- Bid responsiveness window (PRD §3.5) -----------------------------------
BID_CEILING_PCT = 0.10
BID_FLOOR_PCT = 0.25

# --- Crew capacity (PRD §3.5) -----------------------------------------------
CREW_TURNOVER_BUFFER_DAYS = 3
MAX_CONCURRENT_AWARDS = 1

# --- Tiered lien recording fee (PRD §3.6) -----------------------------------
FEE_TIER_1_CEILING_CENTS = 2_000_000
FEE_TIER_1_CENTS = 15_000
FEE_TIER_2_CEILING_CENTS = 5_000_000
FEE_TIER_2_CENTS = 25_000
FEE_TIER_3_CENTS = 40_000

# --- Draws, retainage and change orders (PRD §3.7) --------------------------
RETAINAGE_PCT = 0.10
CHANGE_ORDER_CUMULATIVE_LIMIT_PCT = 20.00

# --- Warranty and remedy windows (PRD §3.7, §3.9) --------------------------
WARRANTY_MONTHS = 12
REMEDY_WINDOW_DAYS = 30

# --- Contractor performance score (PRD §3.9) -------------------------------
PERFORMANCE_SCORE_BASE = 100
OPEN_COMPLAINT_WEIGHT = 20
SANCTION_WEIGHT = 15
COMPLETION_WEIGHT = 5
COMPLETION_CAP = 4
PROBATION_SCORE_THRESHOLD = 50
PERFORMANCE_SCORE_MIN = 0
PERFORMANCE_SCORE_MAX = 100

# --- Program year defaults shared across fixtures ---------------------------
TEST_DEFAULTS = {
    "FISCAL_YEAR": 2026,
    "AMI_MEDIAN_INCOME_CENTS": 9_000_000,
    "MAX_LOAN_AMOUNT_CENTS": 7_500_000,
    "ALLOCATION_BUDGET_CENTS": 50_000_000,
    "BID_DUE_AT": "2026-09-01T00:00:00Z",
    "PROPOSED_START_DATE": "2026-09-05",
    "PROPOSED_END_DATE": "2026-10-30",
}
