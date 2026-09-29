"""Domain thresholds and rates stated by the PRD's computation narratives."""

# --- Bond determination (PRD §3.2) ------------------------------------------
INDIRECT_COST_RATE = 0.185
INDIRECT_COST_MULTIPLIER = 1.185
ANNUAL_INFLATION_RATE = 0.03
INFLATION_MULTIPLIER = 1.03
DAYS_PER_ESCALATION_YEAR = 365
ADMIN_FEE_RATE = 0.015
ADMIN_FEE_MIN = 2500.00
ADMIN_FEE_MAX = 25000.00
STATUTORY_MINIMUM_BOND = 10000.00
ESTIMATE_MAX_AGE_DAYS = 1095

# --- Instrument credit (PRD §3.3) -------------------------------------------
SURETY_RATING_MULTIPLIER = {
    "A_PLUS_PLUS": 1.00,
    "A_PLUS": 1.00,
    "A": 0.90,
    "B_PLUS_PLUS": 0.75,
}
ACCEPTABLE_SURETY_RATINGS = ["A_PLUS_PLUS", "A_PLUS", "A", "B_PLUS_PLUS"]
COLLATERAL_HAIRCUT = {
    "US_TREASURY": 0.00,
    "MUNICIPAL_BOND": 0.05,
    "IRREVOCABLE_LOC": 0.00,
    "REAL_PROPERTY": 0.30,
}

# --- Self-bonding financial tests (PRD §3.1) --------------------------------
SELF_BOND_LEVERAGE_RATIO = 2.5
SELF_BOND_MIN_TNW = 10000000.00
NET_WORTH_CAPACITY_RATE = 0.25
SELF_BOND_MIN_FIXED_ASSETS = 20000000.00
FIXED_ASSET_CAPACITY_RATE = 0.10

# --- Phase bond release (PRD §3.5) -----------------------------------------
PHASE_RELEASE_PCT = {"PHASE_I": 0.60, "PHASE_II": 0.25, "PHASE_III": 0.15}
PHASE_RETENTION_RATE = {"PHASE_I": 0.40, "PHASE_II": 0.15, "PHASE_III": 0.00}
PUBLIC_NOTICE_DAYS = 30
NOTICE_GAP_DAYS = 15
RESCISSION_WINDOW_DAYS = 60

# --- Civil penalties (PRD §3.6) --------------------------------------------
DOLLARS_PER_POINT = 60.00
GOOD_FAITH_RATE = {"RAPID": 0.30, "PARTIAL": 0.10, "NONE": 0.00}
CREDIT_CAP_HIGH = 1500.00
CREDIT_CAP_HIGH_BASE_ABOVE = 3000.00
CREDIT_CAP_LOW = 750.00
CREDIT_CAP_LOW_BASE_ABOVE = 1500.00
IMMINENT_HARM_SURCHARGE_HIGH = 0.25
IMMINENT_HARM_SURCHARGE_HIGH_ABOVE = 5000.00
IMMINENT_HARM_SURCHARGE_LOW = 0.10
IMMINENT_HARM_SURCHARGE_LOW_ABOVE = 2000.00
MINIMUM_PENALTY = 750.00

# --- Violation points (PRD §3.6) -------------------------------------------
HISTORY_LOOKBACK_DAYS = 365
HISTORY_POINTS_PER_PRIOR = 2
HISTORY_POINTS_CAP = 10
TOTAL_POINTS_CAP = 100
CESSATION_POINTS_THRESHOLD = 70
SEVERITY_POINTS_MAX = 40
NEGLIGENCE_POINTS_MAX = 30
DURATION_POINTS_MAX = 25

# --- Permit revisions (PRD §3.4) -------------------------------------------
REVISION_ROUND_CAP = 2

# --- Forfeiture (PRD §3.7) -------------------------------------------------
CONTEST_WINDOW_DAYS = 30

# --- Legacy inventory (PRD §3.8) -------------------------------------------
HAZARD_WEIGHT = {"H1_EXTREME": 50, "H2_HIGH": 30, "H3_MODERATE": 15}
PUBLIC_SAFETY_WEIGHT = 0.30
WATER_QUALITY_WEIGHT = 0.20
ACRE_POINT_RATE = 0.05
ACRE_POINTS_CAP = 15
SCORE_CAP = 100.00
LEGACY_FUND_ANNUAL_CAP = 5000000.00

# --- Pagination (PRD §2.3) -------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --- Logical clock (PRD §2.4) ----------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --- Values shared by the fixture chains -----------------------------------
TEST_DEFAULTS = {
    "ESTIMATOR_FIRM": "Ridgeline Reclamation Engineers",
    "ESTIMATOR_LICENSE_NO": "RE-4417",
    "ALT_ESTIMATOR_FIRM": "Basin Closure Consultants",
    "ALT_ESTIMATOR_LICENSE_NO": "RE-5290",
    "ESTIMATE_EFFECTIVE_DATE": "2026-07-01",
    "DIRECT_COST_PER_ACRE": 6000.00,
    "MINING_PLAN_ACRES": 120.00,
    "CASH_FACE_AMOUNT": 900000.00,
    "PROPOSED_START_DATE": "2026-09-01",
}

# Bond figures the PRD's five-step determination yields for the canonical
# 120-acre plan priced at 6000.00 per acre effective 2026-07-01 with the clock
# at 2026-08-01 (zero whole escalation years).
CANONICAL_LOADED_PER_ACRE = 7110.00
CANONICAL_FULL_PLAN_REQUIRED = 865998.00
