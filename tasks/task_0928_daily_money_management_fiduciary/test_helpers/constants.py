"""Domain thresholds and numeric constants stated in the PRD."""

# --- logical clock ---------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"
DEFAULT_CLOCK_RENDERED = "2026-05-01T00:00:00.000Z"

# The instant most fixtures pin the clock to: Monday 2026-06-01, 09:00 UTC,
# comfortably before the 16:00:00 same-day cut-off.
BASE_CLOCK_UTC = "2026-06-01T09:00:00Z"
BASE_BUDGET_MONTH = "2026-06"

# --- settlement channel lead times & cut-off -------------------------------
SAME_DAY_CUTOFF_UTC = "16:00:00"
LEAD_DAYS_CHECK = 5
LEAD_DAYS_ACH = 2
LEAD_DAYS_BILLER_DIRECT = 0

# --- segregation of duties / dual control ----------------------------------
SECOND_APPROVAL_THRESHOLD_CENTS = 100000

# --- fiduciary service fee (tiered on the pre-fee principal) ---------------
SERVICE_FEE_TIER1_UPPER_EXCLUSIVE_CENTS = 50000
SERVICE_FEE_TIER2_UPPER_EXCLUSIVE_CENTS = 250000
SERVICE_FEE_TIER1_CENTS = 250
SERVICE_FEE_TIER2_CENTS = 500
SERVICE_FEE_TIER3_CENTS = 900

# --- payment lifecycle windows & fees --------------------------------------
STOP_PAYMENT_WINDOW_HOURS = 48
STOP_PAYMENT_FEE_CENTS = 3000
NSF_FEE_CENTS = 3500
DUPLICATE_PAYMENT_BUFFER_DAYS = 3

# --- authorization ---------------------------------------------------------
AUTHORIZATION_MAX_TERM_DAYS = 730
LIMITED_SCOPE_MAX_PAYMENT_CENTS = 250000
REP_PAYEE_MAX_PAYMENT_CENTS = 400000

# --- budget / posture reasons ----------------------------------------------
BUDGET_OVERRIDE_REASON_MIN_CHARS = 20
FRAUD_UNFREEZE_REASON_MIN_CHARS = 20

# --- fraud alert scoring & SLA ---------------------------------------------
FRAUD_AMOUNT_HIGH_CENTS = 500000
FRAUD_AMOUNT_MID_CENTS = 100000
FRAUD_AMOUNT_POINTS_HIGH = 50
FRAUD_AMOUNT_POINTS_MID = 30
FRAUD_AMOUNT_POINTS_LOW = 10
FRAUD_NOVELTY_POINTS_NEVER_PAID = 40
FRAUD_NOVELTY_SETTLED_COUNT_THIN_MAX = 2
FRAUD_NOVELTY_POINTS_THIN = 20
FRAUD_NOVELTY_POINTS_ESTABLISHED = 0
FRAUD_CHANNEL_POINTS_CHECK = 20
FRAUD_CHANNEL_POINTS_ACH = 10
FRAUD_CHANNEL_POINTS_BILLER_DIRECT = 0
FRAUD_BAND_HIGH_MIN_SCORE = 90
FRAUD_BAND_MEDIUM_MIN_SCORE = 50
FRAUD_ACK_SLA_HOURS_HIGH = 4
FRAUD_ACK_SLA_HOURS_MEDIUM = 24
FRAUD_ACK_SLA_HOURS_LOW = 72

# --- disputes --------------------------------------------------------------
DISPUTE_FILING_WINDOW_DAYS = 60
DISPUTE_PROVISIONAL_CREDIT_MAX_CENTS = 500000

# --- reconciliation --------------------------------------------------------
PERIOD_REOPEN_WINDOW_DAYS = 30
PERIOD_REOPEN_MAX_COUNT = 1

# --- benefits --------------------------------------------------------------
BENEFIT_APPEAL_MAX_COUNT = 1
RETRO_AWARD_MAX_LOOKBACK_DAYS = 180
BURIAL_EXCLUSION_CAP_CENTS = 150000
RETIREMENT_COUNTABLE_RATE = 0.665
LIFE_INSURANCE_COUNTABLE_RATE = 0.500

PROGRAM_RESOURCE_LIMIT_CENTS = {
    "SSI": 200000,
    "MEDICAID": 300000,
    "SNAP": 275000,
    "LIHEAP": 400000,
}
PROGRAM_INCOME_LIMIT_CENTS = {
    "SSI": 96700,
    "MEDICAID": 150000,
    "SNAP": 182000,
    "LIHEAP": 250000,
}

# --- care-team coordination ------------------------------------------------
COORD_ACK_SLA_HOURS_URGENT = 2
COORD_ACK_SLA_HOURS_ROUTINE = 48
COORD_ACK_SLA_HOURS_INFORMATIONAL = 120
COORD_REROUTE_MAX_COUNT = 2

# --- disclosure ------------------------------------------------------------
CATEGORY_ORDER = ["BILL_PAY", "BUDGET", "BENEFITS", "FRAUD", "CARE_TEAM", "BALANCES"]

# --- pagination ------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_LIMIT = 1

# --- convenient test defaults ---------------------------------------------
TEST_DEFAULTS = {
    "BOND_COVERAGE_CENTS": 100000000,
    "BOND_EFFECTIVE_DATE": "2026-01-01",
    "BOND_EXPIRY_DATE": "2026-12-31",
    "AUTH_EFFECTIVE_DATE": "2026-01-01",
    "AUTH_EXPIRY_DATE": "2026-12-31",
    "OPENING_BALANCE_CENTS": 5000000,
    "ALLOCATION_CENTS": 300000,
    "PAYMENT_AMOUNT_CENTS": 80000,
}
