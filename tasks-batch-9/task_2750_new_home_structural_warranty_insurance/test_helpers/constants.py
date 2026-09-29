"""Domain thresholds and pinned numeric constants from the PRD calculations.

Every monetary constant is an integer number of cents (PRD Section 2.5).
"""

# --- Logical clock (PRD Section 2.4) -------------------------------------
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- Builder risk score (PRD Section 3.1) -------------------------------
RISK_SCORE_BASE = 50
HISTORY_PENALTY_MULTIPLIER = 0.50
VOLUME_BUCKET_SIZE = 25
VOLUME_POINTS_PER_BUCKET = 8
VOLUME_FACTOR_CAP = 40
VOLUME_FACTOR_WEIGHT = 0.25
TENURE_CREDIT_PER_YEAR = 2
TENURE_CREDIT_CAP = 20
TIER_BONUS = {"TIER_1": 15, "TIER_2": 8, "TIER_3": 0}
RISK_CLASS_FLOORS = {"A": 0.00, "B": 25.00, "C": 45.00, "D": 65.00}

# --- Loss monitoring (PRD Section 3.2) ----------------------------------
OBSERVED_LOSS_WEIGHT = 60
POSTURE_FLOORS = {"OPEN": 0.0000, "WATCH": 0.6500,
                  "RESTRICTED": 0.9000, "FROZEN": 1.2000}

# --- Premium rating (PRD Section 3.3) -----------------------------------
BASE_RATE_BP = {"A": 38, "B": 52, "C": 71, "D": 95}
STRUCTURAL_LOADING = {"A": 1.00, "B": 1.10, "C": 1.25, "D": 1.45}
COVERAGE_SHARES = {"WORKMANSHIP": 0.18, "SYSTEMS": 0.27, "STRUCTURAL": 0.55}
STATE_SURCHARGE_CENTS = {"TX": 4500, "FL": 9500, "CO": 2500, "AZ": 0, "NC": 1500}

TERM_LENGTH_YEARS = {"WORKMANSHIP": 1, "SYSTEMS": 2, "STRUCTURAL": 10}
OBLIGATION_PERIOD_YEARS = 2

TERM_LIMIT_SHARE = {"WORKMANSHIP": 0.10, "SYSTEMS": 0.25}
TERM_LIMIT_CAP_CENTS = {"WORKMANSHIP": 2_000_000, "SYSTEMS": 6_000_000}
TERM_DEDUCTIBLE_CENTS = {"WORKMANSHIP": 100_000, "SYSTEMS": 100_000,
                         "STRUCTURAL": 250_000}

PURCHASE_PRICE_MIN_CENTS = 5_000_000
PURCHASE_PRICE_MAX_CENTS = 500_000_000

# --- Transfers (PRD Section 3.5) ----------------------------------------
TRANSFER_BASE_FEE_CENTS = 7_500
TRANSFER_FEE_PER_PRIOR_TRANSFER_CENTS = 2_500

# --- Structural designation (PRD Section 3.6) ---------------------------
DEFLECTION_STRUCTURAL_THRESHOLD = 0.0033
MAX_AFFECTED_ELEMENTS = 8

# --- Settlement waterfall (PRD Section 3.7) -----------------------------
DEDUCTIBLE_STRUCTURAL_CENTS = 250_000
DEDUCTIBLE_NON_STRUCTURAL_CENTS = 100_000
BETTERMENT_TIER_1_FLOOR_CENTS = 500_000
BETTERMENT_TIER_1_RATE = 0.05
BETTERMENT_TIER_2_FLOOR_CENTS = 1_500_000
BETTERMENT_TIER_2_RATE = 0.08

# --- Escalation ladder (PRD Section 3.9) --------------------------------
MEDIATION_WINDOW_DAYS = 60
ARBITRATION_WINDOW_DAYS = 30
NEUTRAL_TURNAROUND_MINUTES = 120

# --- Pagination (PRD Section 2.3) ---------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Canonical test data ------------------------------------------------
# The class-C reference builder: 5 years, 25 homes, claims score 94, TIER_3
# scores 45.00 and therefore lands in risk class C.
CANONICAL_BUILDER_INPUTS = {
    "company_name": "Cedar Ridge Homes",
    "state_code": "TX",
    "years_in_business": 5,
    "homes_closed_last_year": 25,
    "claims_history_score": 94,
    "financial_strength_tier": "TIER_3",
}
CANONICAL_BUILDER_RISK_SCORE = 45.00
CANONICAL_BUILDER_RISK_CLASS = "C"

# The canonical home: 44,500,000 cents in TX closing 2026-08-15.
CANONICAL_PURCHASE_PRICE_CENTS = 44_500_000
CANONICAL_CLOSING_DATE = "2026-08-15"
CANONICAL_CLOSING_INSTANT = "2026-08-15T00:00:00Z"
CANONICAL_PREMIUM_CENTS = 363_894
CANONICAL_BUILDER_OBLIGATION_END_DATE = "2028-08-14"
CANONICAL_STRUCTURAL_TERM_END_DATE = "2036-08-14"
CANONICAL_SYSTEMS_TERM_END_DATE = "2028-08-14"
CANONICAL_WORKMANSHIP_TERM_END_DATE = "2027-08-14"

# Instants used to place a claim in the builder-obligation period and in the
# insurer-backed period respectively for the canonical home.
BUILDER_PERIOD_INSTANT = "2026-09-01T00:00:00Z"
INSURER_PERIOD_INSTANT = "2028-09-01T00:00:00Z"
