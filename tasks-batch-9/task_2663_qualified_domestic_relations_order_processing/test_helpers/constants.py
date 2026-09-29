"""Numeric and temporal constants fixed by the QDRO API contract.

Anything a test would otherwise hard-code twice lives here: the basis-point
scale, the plan's registration defaults, the settlement thresholds, the
pagination bounds, and the logical clock's pre-set reading.
"""

# ─── Envelope and pagination ──────────────────────────────────────────────

API_REQUEST_ID_PREFIX = "req_"

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0
MIN_OFFSET = 0

PAGINATION_META_KEYS = ["limit", "offset", "total_count", "has_more"]
ENVELOPE_META_KEYS = ["api_request_id", "api_request_timestamp"]

# ─── Basis points ─────────────────────────────────────────────────────────

BPS_SCALE = 10000          # 10000 basis points is 100 percent
MAX_BPS = 10000

# ─── Logical clock ────────────────────────────────────────────────────────

# The clock's reading before it has ever been set.
CLOCK_UNSET_DEFAULT = "2026-08-01T00:00:00Z"

# Instants the recipes in this suite drive the clock to.
CLOCK_2026_09_01 = "2026-09-01T00:00:00Z"
CLOCK_2026_09_10 = "2026-09-10T00:00:00Z"
CLOCK_2026_09_15 = "2026-09-15T00:00:00Z"
CLOCK_2026_09_20 = "2026-09-20T00:00:00Z"
CLOCK_2026_10_31 = "2026-10-31T00:00:00Z"
CLOCK_2026_11_01 = "2026-11-01T00:00:00Z"
CLOCK_2026_11_20 = "2026-11-20T00:00:00Z"
CLOCK_2028_03_02 = "2028-03-02T00:00:00Z"
CLOCK_2028_03_02_PLUS_1S = "2028-03-02T00:00:01Z"
CLOCK_2028_03_03 = "2028-03-03T00:00:00Z"

# ─── Plan registration defaults ───────────────────────────────────────────

DEFAULT_REQUIRES_MODEL_LANGUAGE = True
DEFAULT_PERMITS_BENEFIT_NOT_OTHERWISE_AVAILABLE = False
DEFAULT_MAX_ASSIGNABLE_PCT_BPS = 5000
DEFAULT_MAX_ASSIGNABLE_AMOUNT_CENTS = 100000000
DEFAULT_REVIEW_PERIOD_DAYS = 45
DEFAULT_RESUBMISSION_WINDOW_DAYS = 60
DEFAULT_SEGREGATION_PERIOD_DAYS = 548
DEFAULT_MAX_REVISIONS = 3
DEFAULT_PROCEDURES_STATUS = "DRAFT"
DEFAULT_PARTICIPANT_COUNT = 0

# Accepted ranges declared for the plan's tunables.
MIN_MAX_ASSIGNABLE_PCT_BPS = 1
MIN_MAX_ASSIGNABLE_AMOUNT_CENTS = 1
MIN_WINDOW_DAYS = 1
MAX_REVIEW_PERIOD_DAYS = 365
MAX_RESUBMISSION_WINDOW_DAYS = 365
MAX_SEGREGATION_PERIOD_DAYS = 1095
MIN_MAX_REVISIONS = 1
MAX_MAX_REVISIONS = 10

# ─── Participant and account defaults ─────────────────────────────────────

DEFAULT_EMPLOYMENT_STATUS = "ACTIVE"
DEFAULT_BENEFIT_COMMENCED = False
DEFAULT_MONTHLY_PAYMENT_CENTS = 0
DEFAULT_BASIS_CENTS = 0
DEFAULT_IS_ASSIGNABLE = True

# ─── Distribution settlement ──────────────────────────────────────────────

WITHHOLDING_RATE_BPS = 2000                  # twenty percent
WITHHOLDING_TAXABLE_FLOOR_CENTS = 20000      # the comparison is >= this figure

ADMIN_FEE_LOW_CENTS = 2500                   # net_before_fee below 100000
ADMIN_FEE_MID_CENTS = 5000                   # 100000 through 999999 inclusive
ADMIN_FEE_HIGH_CENTS = 7500                  # 1000000 and above
ADMIN_FEE_MID_THRESHOLD_CENTS = 100000
ADMIN_FEE_HIGH_THRESHOLD_CENTS = 1000000

# The age at which a cash election stops being an early distribution.
EARLY_DISTRIBUTION_AGE_YEARS = 59
EARLY_DISTRIBUTION_AGE_EXTRA_MONTHS = 6

# ─── Field name groupings used by shape assertions ────────────────────────

PLAN_ACCOUNT_DERIVED_FIELDS = [
    "vested_balance_cents",
    "assignable_base_cents",
    "after_tax_basis_cents",
    "held_amount_cents",
    "available_balance_cents",
]

CASE_OPERATIVE_TERM_FIELDS = [
    "approach",
    "formula_code",
    "assigned_percentage_bps",
    "assigned_flat_amount_cents",
    "shared_payment_end_date",
]

BENEFIT_PROJECTION_FIELDS = [
    "assignable_base_cents",
    "gross_assigned_amount_cents",
    "effective_approach",
    "earnings_growth_bps",
    "earnings_adjustment_cents",
    "separate_interest_balance_cents",
    "shared_payment_per_period_cents",
    "after_tax_basis_carryover_cents",
    "valuation_snapshot_count",
]

SWEEP_RESPONSE_ID_ARRAYS = [
    "expired_hold_ids",
    "lapsed_case_ids",
    "denied_draft_order_ids",
    "expired_notice_ids",
    "closed_ap_account_ids",
]

DISTRIBUTION_SETTLEMENT_FIELDS = [
    "basis_recovery_cents",
    "taxable_amount_cents",
    "federal_withheld_cents",
    "net_before_fee_cents",
    "admin_fee_cents",
    "net_amount_cents",
    "distribution_code",
    "tax_year",
]

TAX_REPORT_SIGNED_FIELDS = [
    "reportable_gross_cents",
    "reportable_taxable_cents",
    "federal_withheld_cents",
]
