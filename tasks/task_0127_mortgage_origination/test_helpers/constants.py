"""Domain thresholds and constants from PRD §2.8, §2.9, §3.

All monetary values are integer cents. All ratios are 4-decimal-place
floats. All time-gated logic operates on SystemClock.now (PRD §2.9).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pre-qualification — PRD §3.2
# ---------------------------------------------------------------------------
MIN_CREDIT_SCORE_FOR_PREQUAL = 620
PREQUAL_INCOME_MULTIPLE = 4  # requested principal <= 4 * stated income


# ---------------------------------------------------------------------------
# DTI — PRD §3.7
# ---------------------------------------------------------------------------
DTI_CEILING_AT_APPROVE = 0.43           # PRD §3.8: "no greater than 0.43"
DTI_ESTIMATION_RATE_FACTOR = 0.0065     # PRD §3.7 rate-agnostic proxy
DTI_PRECISION_DP = 4                    # PRD §2.8: 4 dp


# ---------------------------------------------------------------------------
# LTV — PRD §3.7 / §3.8
# ---------------------------------------------------------------------------
LTV_CEILING_AT_APPROVE = 0.97           # PRD §3.8
LTV_PMI_THRESHOLD = 0.80                # PRD §3.7: "PMI threshold sits at 0.80"
LTV_PRECISION_DP = 4


# ---------------------------------------------------------------------------
# Income / asset verification thresholds — PRD §3.3
# ---------------------------------------------------------------------------
INCOME_VERIFICATION_TOLERANCE = 0.80    # documented >= 0.80 * stated
ASSET_MATERIALITY_FLOOR_CENTS = 1_000   # PRD §3.3: "at least 1,000"


# ---------------------------------------------------------------------------
# Appraisal — PRD §3.4
# ---------------------------------------------------------------------------
APPRAISAL_VALIDITY_DAYS = 120           # PRD §3.4: "plus 120 calendar days"


# ---------------------------------------------------------------------------
# Rate lock — PRD §3.5
# ---------------------------------------------------------------------------
RATE_LOCK_INITIAL_DAYS = 45             # PRD §3.5
RATE_LOCK_INITIAL_FEE_BPS = 25          # PRD §3.5: "25 basis points"
RATE_LOCK_FREE_LOOK_HOURS = 48          # PRD §3.5: "within 48 hours of locked_at"
RATE_LOCK_EXTENSION_CAP_DAYS = 60       # PRD §3.5: "must not exceed 60 days"

# Extension fee tiers in basis points — PRD §3.5.
RATE_LOCK_EXTENSION_FEE_BPS = {
    7: 5,    # 0.05%
    15: 10,  # 0.10%
    30: 25,  # 0.25%
}
ALLOWED_EXTENSION_EXTRA_DAYS = (7, 15, 30)


# ---------------------------------------------------------------------------
# TRID / Closing disclosure — PRD §3.6
# ---------------------------------------------------------------------------
TRID_BUSINESS_DAYS_REQUIRED = 3
TRID_HOLIDAYS_2026 = (
    "2026-01-01",  # New Year's Day
    "2026-07-06",  # Independence Day (observed)
    "2026-12-25",  # Christmas Day
)
APR_TOLERANCE_BPS = 12  # PRD §3.6: "exceeds 12 basis points"


# ---------------------------------------------------------------------------
# Closing-cost tier breakpoints — PRD §3.6
# ---------------------------------------------------------------------------
TIER_LOW_CENTS = 41_700_000       # $417,000 — PRD §3.6 inclusive boundary
TIER_MID_CENTS = 76_600_000       # $766,000 — PRD §3.6 inclusive boundary
ORIGINATION_RATE_LOW = 0.0100     # 1.00% — at or below TIER_LOW_CENTS
ORIGINATION_RATE_MID = 0.0075     # 0.75% — above TIER_LOW, at or below TIER_MID
ORIGINATION_RATE_HIGH = 0.0050    # 0.50% — above TIER_MID

# State tax rates keyed by Borrower.state_code — PRD §3.6.
STATE_TAX_RATE = {
    "CA": 0.0050,
    "NY": 0.0125,
    "TX": 0.0075,
}
STATE_TAX_RATE_DEFAULT = 0.0100


# ---------------------------------------------------------------------------
# Disclosure / APR caps — PRD §3.6
# ---------------------------------------------------------------------------
APR_BPS_MAX = 2500              # PRD §3.6: "no greater than 2,500"
LOCKED_RATE_BPS_MAX = 2000      # PRD §3.5: "not exceeding 2,000"


# ---------------------------------------------------------------------------
# Credit score range — PRD §3.1
# ---------------------------------------------------------------------------
CREDIT_SCORE_MIN = 300
CREDIT_SCORE_MAX = 850


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_OFFSET = 0


# ---------------------------------------------------------------------------
# Allowed enum values (mirrored from PRD §3 for parameter use).
# ---------------------------------------------------------------------------
ALLOWED_LOAN_TERM_MONTHS = (120, 180, 240, 360)
ALLOWED_LOAN_PURPOSES = ("PURCHASE", "REFINANCE")
ALLOWED_INCOME_SOURCE_TYPES = ("W2", "SELF_EMPLOYED", "OTHER")
ALLOWED_ASSET_TYPES = ("CHECKING", "SAVINGS", "INVESTMENT", "GIFT")
ALLOWED_DISCLOSURE_KINDS = ("LOAN_ESTIMATE", "CLOSING_DISCLOSURE")
ALLOWED_UDAAP_OUTCOMES = ("PASS", "FLAG", "BLOCK")
ALLOWED_UNDERWRITE_DECISIONS = ("APPROVE", "COUNTER_OFFER", "DENY")


# ---------------------------------------------------------------------------
# Test defaults — convenient base values reused across factories/fixtures.
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "BORROWER_FULL_NAME": "Test Borrower",
    "BORROWER_SSN_LAST4": "1234",
    "BORROWER_ANNUAL_INCOME_CENTS": 12_000_000,   # $120,000
    "BORROWER_CREDIT_SCORE": 720,
    "BORROWER_STATE_CODE": "CA",
    "PROPERTY_ADDRESS": "100 Test Lane, Test City, CA 94101",
    "SALE_PRICE_CENTS": 40_000_000,               # $400,000
    "REQUESTED_LOAN_AMOUNT_CENTS": 20_000_000,    # $200,000 (1x stated income)
    "LOAN_TERM_MONTHS": 360,
    "LOAN_PURPOSE": "PURCHASE",
    "ASSIGNED_LOAN_OFFICER_ID": "lo-001",
    "APPRAISED_VALUE_CENTS": 40_000_000,          # match sale_price
    "APPRAISAL_REPORT_DATE": "2026-03-01T00:00:00.000Z",
    "DEFAULT_CLOCK_ANCHOR": "2026-03-02T10:00:00.000Z",
    "INCOME_DOCUMENTED_ANNUAL_CENTS": 12_000_000,
    "ASSET_BALANCE_CENTS": 5_000_000,             # $50,000
    "LOCKED_RATE_BPS": 650,                       # 6.50%
    "LE_APR_BPS": 650,
    "TOTAL_LOAN_COSTS_CENTS": 500_000,            # $5,000
    "TOTAL_OTHER_COSTS_CENTS": 800_000,           # $8,000
}


__all__ = [
    "MIN_CREDIT_SCORE_FOR_PREQUAL",
    "PREQUAL_INCOME_MULTIPLE",
    "DTI_CEILING_AT_APPROVE",
    "DTI_ESTIMATION_RATE_FACTOR",
    "DTI_PRECISION_DP",
    "LTV_CEILING_AT_APPROVE",
    "LTV_PMI_THRESHOLD",
    "LTV_PRECISION_DP",
    "INCOME_VERIFICATION_TOLERANCE",
    "ASSET_MATERIALITY_FLOOR_CENTS",
    "APPRAISAL_VALIDITY_DAYS",
    "RATE_LOCK_INITIAL_DAYS",
    "RATE_LOCK_INITIAL_FEE_BPS",
    "RATE_LOCK_FREE_LOOK_HOURS",
    "RATE_LOCK_EXTENSION_CAP_DAYS",
    "RATE_LOCK_EXTENSION_FEE_BPS",
    "ALLOWED_EXTENSION_EXTRA_DAYS",
    "TRID_BUSINESS_DAYS_REQUIRED",
    "TRID_HOLIDAYS_2026",
    "APR_TOLERANCE_BPS",
    "TIER_LOW_CENTS",
    "TIER_MID_CENTS",
    "ORIGINATION_RATE_LOW",
    "ORIGINATION_RATE_MID",
    "ORIGINATION_RATE_HIGH",
    "STATE_TAX_RATE",
    "STATE_TAX_RATE_DEFAULT",
    "APR_BPS_MAX",
    "LOCKED_RATE_BPS_MAX",
    "CREDIT_SCORE_MIN",
    "CREDIT_SCORE_MAX",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "ALLOWED_LOAN_TERM_MONTHS",
    "ALLOWED_LOAN_PURPOSES",
    "ALLOWED_INCOME_SOURCE_TYPES",
    "ALLOWED_ASSET_TYPES",
    "ALLOWED_DISCLOSURE_KINDS",
    "ALLOWED_UDAAP_OUTCOMES",
    "ALLOWED_UNDERWRITE_DECISIONS",
    "TEST_DEFAULTS",
]
