"""Numeric thresholds and shared literals used across the test suite.

Every value here is stated by the PRD; nothing is invented.
"""

# --- accountability representation score -------------------------------
ADVISORY_WEIGHT = 0.5
ADVISORY_CREDIT_CAP = 0.2000
ACCOUNTABILITY_SATISFACTION_THRESHOLD = 0.5000
SCORE_PRECISION = 4

# --- loan pricing and grading -----------------------------------------
TIER_A_MIN_SCORE, TIER_A_MAX_DTI, TIER_A_SPREAD_BPS = 720, 36.00, 0
TIER_B_MIN_SCORE, TIER_B_MAX_DTI, TIER_B_SPREAD_BPS = 660, 43.00, 75
TIER_C_MIN_SCORE, TIER_C_MAX_DTI, TIER_C_SPREAD_BPS = 600, 45.00, 150
TIER_D_MAX_DTI, TIER_D_SPREAD_BPS = 50.00, 275
TIER_E_MIN_TA_HOURS, TIER_E_MAX_DTI, TIER_E_SPREAD_BPS = 12.00, 45.00, 200
TA_DISCOUNT_BPS = 25
TA_DISCOUNT_HOURS_THRESHOLD = 8.00

# --- target-market lending measurement --------------------------------
TARGET_MARKET_THRESHOLD_PCT = 60.00
RECERTIFICATION_INTERVAL_DAYS = 1095
FINANCING_ACTIVITY_MINIMUM_PCT = 60.00

# --- portfolio loss reserve -------------------------------------------
ROLL_RATE_CURRENT = 0.0200
ROLL_RATE_DELINQUENT_30 = 0.1000
ROLL_RATE_DELINQUENT_60 = 0.3500
ROLL_RATE_DELINQUENT_90 = 0.7500
VINTAGE_RATE_CURRENT_YEAR = 0.0450
VINTAGE_RATE_PRIOR_YEAR = 0.0300

# --- reserve coverage and posture -------------------------------------
POSTURE_COMPLIANT_MIN_RATIO = 1.0000
POSTURE_WATCH_MIN_RATIO = 0.8000
EMPTY_PORTFOLIO_RATIO = 1.0000

# --- matching-fund eligibility factors --------------------------------
MATCH_FACTORS = {
    "CASH_PRIVATE": 1.00,
    "CASH_PUBLIC_NON_FEDERAL": 1.00,
    "IN_KIND": 0.50,
    "DEFERRED_PLEDGE": 0.75,
    "FEDERAL": 0.00,
}

# --- impact aggregation ----------------------------------------------
GOAL_DENOMINATOR_FLOOR = 1

# --- delinquency bucketing -------------------------------------------
BUCKET_30_DAYS = 30
BUCKET_60_DAYS = 60
BUCKET_90_DAYS = 90
PAYMENT_PERIOD_DAYS = 30

# --- certification docket --------------------------------------------
MAX_REVISION_ROUNDS = 2
CERTIFICATION_TEST_CODES = [
    "PRIMARY_MISSION",
    "FINANCING_ENTITY",
    "TARGET_MARKET",
    "DEVELOPMENT_SERVICES",
    "ACCOUNTABILITY",
    "NON_GOVERNMENT",
]
CERTIFICATION_TEST_STATE_FIELDS = [
    "test_primary_mission_state",
    "test_financing_entity_state",
    "test_target_market_state",
    "test_development_services_state",
    "test_accountability_state",
    "test_non_government_state",
]

# --- pagination -------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- logical clock ----------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --- shared literals used by setup helpers ----------------------------
TEST_DEFAULTS = {
    "MISSION_STATEMENT": (
        "Primary mission of community development finance for underserved "
        "households and small businesses."
    ),
    "DEVELOPMENT_SERVICES": (
        "Credit counseling, homebuyer education and business technical assistance."
    ),
    "CENSUS_TRACT": "36005010100",
    "POSTAL_CODE": "10451",
    "STREET_ADDRESS": "12 Grand Concourse",
    "ASSET_SIZE_CENTS": 500_000_000,
    "PRODUCT_CAP_CENTS": 100_000_000,
    "BASE_RATE_BPS": 900,
    "TERM_MONTHS": 60,
}
