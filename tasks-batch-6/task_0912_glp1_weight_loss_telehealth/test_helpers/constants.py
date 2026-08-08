"""Domain thresholds and money constants stated by the PRD."""

# --- Eligibility screening -------------------------------------------------
BMI_OBESITY_MIN = 30.0
BMI_COMORBID_MIN = 27.0
COMORBIDITY_MIN_COUNT = 1
EGFR_EXCLUSION_MIN = 30.0
LAB_VALIDITY_DAYS = 90

# --- Dose ladder -----------------------------------------------------------
DOSE_MG_BY_FAMILY_AND_LEVEL = {
    "SEMAGLUTIDE": {1: 0.25, 2: 0.5, 3: 1.0, 4: 1.7, 5: 2.4},
    "TIRZEPATIDE": {1: 2.5, 2: 5.0, 3: 7.5, 4: 12.5, 5: 15.0},
}
TITRATION_MAX_DOSE_LEVEL = 5
TITRATION_SECOND_SIGNER_MIN_LEVEL = 4
TITRATION_MIN_INTERVAL_DAYS = 28
TITRATION_EXTENDED_INTERVAL_DAYS = 42
TITRATION_TOLERABILITY_TRIGGER_INDEX = 4

# --- Side-effect scoring ---------------------------------------------------
NAUSEA_WEIGHT = 1
VOMITING_WEIGHT = 2
DEHYDRATION_WEIGHT = 4
CHECK_IN_ESCALATION_SCORE = 7
CHECK_IN_HOLD_SCORE = 9
SEVERITY_WINDOW_DAYS = 30

# --- Fulfilment ------------------------------------------------------------
MAX_UNITS_PER_ORDER = 4
LOT_MIN_SHELF_LIFE_DAYS = 30

# --- Payer coverage --------------------------------------------------------
MAX_PA_APPEALS = 2
PA_VALIDITY_DAYS = 180

# --- Pricing ---------------------------------------------------------------
UNIT_PRICE_COMPOUNDED_CENTS = 20000
UNIT_PRICE_BRANDED_CENTS = 25000
DOSE_MULTIPLIER = {1: 1.00, 2: 1.00, 3: 1.25, 4: 1.25, 5: 1.50}
CASH_DISCOUNT_PCT = 0.15
CASH_DISCOUNT_MAX_CENTS = 9000
PLAN_ALLOWED_CAP_CENTS = 42000
COPAY_CENTS = 3500
COINSURANCE_PCT = 0.20
OOP_MAX_PER_CYCLE_CENTS = 9000

COACHING_ADDON_FEE_CENTS = 4900
DISPENSING_FEE_CENTS = 2500
DISPENSING_FEE_WAIVER_SUBTOTAL_CENTS = 36000
ADHERENCE_CREDIT_TIER_0_CENTS = 0
ADHERENCE_CREDIT_TIER_1_2_CENTS = 1500
ADHERENCE_CREDIT_TIER_3_PLUS_CENTS = 3000

# --- Subscription / coaching entitlement -----------------------------------
CYCLE_LENGTH_DAYS = 30
COACHING_CREDITS_PER_CYCLE = 4
COACHING_CREDIT_REFUND_CENTS = 1000
PAUSE_MAX_DAYS = 60

# --- Calendars -------------------------------------------------------------
CONSULT_BUFFER_MINUTES = 15

# --- Pagination ------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# --- Logical clock ---------------------------------------------------------
LOGICAL_CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"

# --- Convenient scenario defaults ------------------------------------------
TEST_DEFAULTS = {
    "STATE_CODE": "CA",
    "HEIGHT_CM": 170,
    "WEIGHT_OBESE_KG": 95.0,
    "WEIGHT_BMI_30_KG": 86.7,
    "WEIGHT_BMI_27_KG": 78.03,
    "WEIGHT_BELOW_BAND_KG": 77.0,
    "EGFR_NORMAL": 88.0,
    "FRESH_LAB_COLLECTED_AT": "2026-05-20T00:00:00Z",
    "BASE_CLOCK": "2026-06-01T00:00:00Z",
}
