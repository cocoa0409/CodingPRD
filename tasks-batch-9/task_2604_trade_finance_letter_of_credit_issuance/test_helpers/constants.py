"""Numeric and calendar constants the PRD pins by value."""

# --- logical clock (PRD 2.5 / 3.9) ---
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- facility (PRD 3.1) ---
MIN_FACILITY_LIMIT_CENTS = 100000
FACILITY_RESTRICT_PCT = 95
COLLATERAL_ADVANCE_RATE_PCT = 90

# --- bank eligibility (PRD 3.1 / 3.4) ---
COUNTRY_WEIGHT = 6
RATING_WEIGHT = 4
RATING_POINTS = {"AA": 100, "A": 75, "BBB": 50, "BB": 25}
MAX_CONFIRM_COUNTRY_RISK = 60

# --- exposure (PRD 3.2 / 3.3) ---
MIN_CREDIT_AMOUNT_CENTS = 100000
TENOR_RISK_BPS_PER_MONTH = 25
DAYS_PER_MONTH = 30

# --- issuance charges (PRD 3.3) ---
DAYS_PER_QUARTER = 90
COMMISSION_TIER_1_CAP_CENTS = 5000000
COMMISSION_TIER_2_CAP_CENTS = 50000000
COMMISSION_TIER_1_BPS = 15
COMMISSION_TIER_2_BPS = 10
COMMISSION_TIER_3_BPS = 7
MIN_COMMISSION_CENTS = 25000

# --- confirmation charge (PRD 3.4) ---
CONFIRM_BASE_BPS = 20
CONFIRM_RISK_BPS_PER_POINT = 1

# --- amendments (PRD 3.5) ---
AMENDMENT_FEE_CENTS = 7500
AMENDMENT_CONSENT_DAYS = 10
AMENDMENT_COOLING_OFF_DAYS = 2
AMENDABLE_FIELDS = (
    "amount_cents",
    "tolerance_pct",
    "expiry_date",
    "latest_shipment_date",
    "incoterm",
    "incoterm_place",
    "presentation_period_days",
    "partial_shipment_allowed",
    "transhipment_allowed",
)

# --- examination period (PRD 3.6) ---
EXAMINATION_BANKING_DAYS = 5
WAIVER_RESPONSE_DAYS = 2
END_OF_DAY_SUFFIX = "T23:59:59.999Z"

# --- settlement (PRD 3.9) ---
SIGHT_COMMISSION_BPS = 12
NEGOTIATION_COMMISSION_BPS = 20
DOC_FEE_BPS = 5
DOC_FLAT_FEE_CENTS = 3500
DISCOUNT_RATE_BPS = 450
DISCOUNT_DAY_BASIS = 360

# --- screening (PRD 3.8) ---
SANCTIONED_COUNTRY_CODES = ("IR", "KP", "SY", "CU")
HIGH_RISK_TRANSIT_CODES = ("AE", "HK", "TR")
DUAL_USE_HS_PREFIXES = ("8471", "8542", "9013", "2811")
CONTROLLED_KEYWORDS = ("centrifuge", "maraging", "gyroscope")
COUNTRY_HIT_WEIGHT = 100
DUAL_USE_HIT_WEIGHT = 60
KEYWORD_HIT_WEIGHT = 40
TRANSIT_HIT_WEIGHT = 20
SCORE_CAP = 200
SANCTIONS_REVIEW_SCORE = 40
SANCTIONS_BLOCK_SCORE = 100

# --- pagination (PRD 2.3) ---
DEFAULT_LIMIT = 10
MAX_LIMIT = 100

# --- claim admission table (PRD 3.9) ---
CLAIM_ADMISSION = {
    "SIGHT_PAYMENT": ("PAYMENT", "REIMBURSEMENT"),
    "NEGOTIATION": ("NEGOTIATION", "REIMBURSEMENT"),
    "ACCEPTANCE": ("ACCEPTANCE", "REIMBURSEMENT"),
    "DEFERRED_PAYMENT": ("DEFERRED_PAYMENT", "REIMBURSEMENT"),
}

# --- sweep counters (PRD 3.9) ---
SWEEP_COUNTERS = (
    "credits_expired",
    "presentations_precluded",
    "waiver_requests_expired",
    "amendments_lapsed",
    "allocations_released",
    "facilities_reactivated",
)
