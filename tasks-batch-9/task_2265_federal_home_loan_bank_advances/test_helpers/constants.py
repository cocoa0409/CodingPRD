"""Named constants declared by the PRD, plus the probe identifiers used by tests.

Every value here is a literal the PRD states in prose or in one of its tables.
Nothing is derived or invented.
"""

# ---------------------------------------------------------------------------
# Basis points and rounding (PRD 2.6)
# ---------------------------------------------------------------------------
BPS_DENOMINATOR = 10_000

# ---------------------------------------------------------------------------
# Logical clock and market reinvestment rate (PRD 2.9)
# ---------------------------------------------------------------------------
CLOCK_START = "2026-08-01T00:00:00Z"
DEFAULT_MARKET_RATE_BPS = 300

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ---------------------------------------------------------------------------
# Membership stock (PRD 3.1)
# ---------------------------------------------------------------------------
PAR_VALUE_CENTS = 10_000
MEMBERSHIP_STOCK_RATE_BPS = 12
MEMBERSHIP_STOCK_FLOOR_CENTS = 1_000_000
MEMBERSHIP_STOCK_CEILING_CENTS = 250_000_000
MIN_TOTAL_ASSETS_CENTS = 100_000_000
DEFAULT_CREDIT_RATING_TIER = 2

# ---------------------------------------------------------------------------
# Custody windows (PRD 3.3)
# ---------------------------------------------------------------------------
CUSTODY_BUFFER_DAYS = 2

# ---------------------------------------------------------------------------
# Eligibility gates and discount factors (PRD 3.4)
# ---------------------------------------------------------------------------
MAX_LTV_BPS = 9_500
MAX_DELINQUENCY_DAYS = 60
DISCOUNT_FACTOR_FLOOR_BPS = 2_000
PROVISIONAL_RECOGNITION_SHARE_BPS = 5_000
STALE_APPRAISAL_DAYS = 365

HIGH_LTV_THRESHOLD_BPS = 8_000
HIGH_LTV_PENALTY_BPS = 500
DELINQUENCY_PENALTY_THRESHOLD_DAYS = 30
DELINQUENCY_PENALTY_BPS = 1_000
DOCUMENTATION_EXCEPTION_PENALTY_BPS = 700
STALE_APPRAISAL_PENALTY_BPS = 300

# Base discount factor in basis points, keyed by asset class then listing mode.
# A missing (class, mode) pair means no base factor exists for that pairing.
BASE_DISCOUNT_FACTOR_BPS = {
    "SF_MORTGAGE": {"BLANKET": 7_800, "SPECIFIC": 8_600, "DELIVERED": 9_200},
    "MULTIFAMILY": {"BLANKET": 6_800, "SPECIFIC": 7_400, "DELIVERED": 8_000},
    "CRE": {"BLANKET": 5_500, "SPECIFIC": 6_200, "DELIVERED": 6_800},
    "HELOC": {"BLANKET": 5_000, "SPECIFIC": 5_800, "DELIVERED": 6_400},
    "SMALL_BUSINESS": {"BLANKET": 4_000, "SPECIFIC": 4_800, "DELIVERED": 5_400},
    "CDFI_COMMUNITY": {"BLANKET": 4_500, "SPECIFIC": 5_200, "DELIVERED": 5_800},
    "AGENCY_MBS": {"SPECIFIC": 9_000, "DELIVERED": 9_400},
    "TREASURY": {"SPECIFIC": 9_500, "DELIVERED": 9_700},
}

SECURITIES_ASSET_CLASSES = ("AGENCY_MBS", "TREASURY")
STALE_APPRAISAL_ASSET_CLASSES = ("CRE", "MULTIFAMILY")

# ---------------------------------------------------------------------------
# Advance sizing (PRD 3.5)
# ---------------------------------------------------------------------------
TIER_CAP_BPS = {1: 10_000, 2: 9_000, 3: 7_500, 4: 5_000}
STATUTORY_CAP_BPS = 3_000
ADVANCE_RATE_FLOOR_BPS = 50
SUBSIDY_CAP_BPS = 2_000
MAX_ACTIVITY_STOCK_PCT_BPS = 2_000
RESTRICTED_MAX_TERM_DAYS = 90

# ---------------------------------------------------------------------------
# Community program allocations (PRD 3.6)
# ---------------------------------------------------------------------------
BUCKET_FIRST_TIME_BPS = 3_500
BUCKET_REHABILITATION_BPS = 2_500
BUCKET_GENERAL_BPS = 4_000
MAX_SUBSIDY_RATE_BPS = 500
MIN_FISCAL_YEAR = 2020

# ---------------------------------------------------------------------------
# Prepayment (PRD 3.7)
# ---------------------------------------------------------------------------
FEE_DAY_BASIS = 360
ADMIN_FEE_BPS = 5
SYMMETRIC_CREDIT_CAP_BPS = 200
QUOTE_VALIDITY_DAYS = 5

# ---------------------------------------------------------------------------
# Verification reviews (PRD 3.8)
# ---------------------------------------------------------------------------
FINDING_WEIGHTS = {"CRITICAL": 3.0, "MAJOR": 1.0, "MINOR": 0.25}
RETEST_CEILING = 2

# Haircut bands, inclusive lower bound on exception_rate_pct -> haircut_bps.
HAIRCUT_BANDS = ((0.0, 0), (2.0, 300), (5.0, 700), (10.0, 1_500))
HAIRCUT_QUALIFIED_THRESHOLD_PCT = 2.0
HAIRCUT_FAIL_THRESHOLD_PCT = 10.0

# ---------------------------------------------------------------------------
# Posture and shortfall (PRD 2.8, 3.9)
# ---------------------------------------------------------------------------
POSTURE_BUFFER_BPS = 500
SHORTFALL_BUFFER_BPS = 200
SHORTFALL_CURE_DAYS = 5

# ---------------------------------------------------------------------------
# Identifiers used to probe unknown resources
# ---------------------------------------------------------------------------
UNKNOWN_MEMBER_BANK_ID = "33333333-3333-4333-8333-333333333333"
UNKNOWN_STOCK_SUBSCRIPTION_ID = "33333333-3333-4333-8333-333333333334"
UNKNOWN_SAFEKEEPING_RECEIPT_ID = "33333333-3333-4333-8333-333333333335"
UNKNOWN_REVIEW_ID = "33333333-3333-4333-8333-333333333336"
UNKNOWN_REVIEW_FINDING_ID = "33333333-3333-4333-8333-333333333337"
UNKNOWN_ADVANCE_PRODUCT_ID = "33333333-3333-4333-8333-333333333338"
UNKNOWN_PREPAYMENT_EVENT_ID = "33333333-3333-4333-8333-333333333339"
UNKNOWN_ALLOCATION_ID = "33333333-3333-4333-8333-33333333333a"
UNKNOWN_ADVANCE_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_COLLATERAL_ASSET_ID = "22222222-2222-4222-8222-222222222222"
