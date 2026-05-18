"""Static configuration values used across the patent-application API.

All structural names — header names, envelope fields, pagination params, role
strings, error IDs, fee table constants — are defined here so the rest of the
codebase reads them from a single source of truth (the SCAFFOLD/PRD).
"""

# -----------------------------------------------------------------------------
# Auth header names (PRD §2.1)
# -----------------------------------------------------------------------------
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"
HEADER_IDEMPOTENCY_KEY = "X-Idempotency-Key"

# Roles enum (SCAFFOLD §1.7 / PRD §2.1)
ROLE_APPLICANT = "Applicant"
ROLE_EXAMINER = "Examiner"
ROLE_USPTO_ADMIN = "USPTOAdmin"
ROLES = {ROLE_APPLICANT, ROLE_EXAMINER, ROLE_USPTO_ADMIN}

# -----------------------------------------------------------------------------
# Pagination defaults (SCAFFOLD.response_envelope.pagination_defaults)
# -----------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# -----------------------------------------------------------------------------
# Entity-size constants (SCAFFOLD §1.3, all calculations)
# -----------------------------------------------------------------------------
ENTITY_SIZE_LARGE = "LARGE"
ENTITY_SIZE_SMALL = "SMALL"
ENTITY_SIZE_MICRO = "MICRO"
ENTITY_SIZES = {ENTITY_SIZE_LARGE, ENTITY_SIZE_SMALL, ENTITY_SIZE_MICRO}

# Entity multiplier expressed as (numerator, denominator) so we can multiply by
# integer cents and round half-up using exact Decimal arithmetic.
ENTITY_MULTIPLIER = {
    ENTITY_SIZE_LARGE: (1, 1),
    ENTITY_SIZE_SMALL: (1, 2),
    ENTITY_SIZE_MICRO: (1, 4),
}

# Micro-eligibility caps. The scaffold pins the names MICRO_INCOME_CAP_CENTS
# and MICRO_PRIOR_FILINGS_MAX but does not supply numeric values; we choose
# values matching the USPTO's actual rules:
#   - ~$220,000 gross income ceiling (annualised).
#   - At most 4 prior non-provisional US filings (i.e., MICRO ineligible at 5+).
MICRO_INCOME_CAP_CENTS = 22_000_000  # $220,000.00 in cents
MICRO_PRIOR_FILINGS_MAX = 4

# -----------------------------------------------------------------------------
# Application type enum (SCAFFOLD §1.1 Application.application_type)
# -----------------------------------------------------------------------------
APP_TYPE_UTILITY = "UTILITY"
APP_TYPE_DESIGN = "DESIGN"
APP_TYPE_PROVISIONAL = "PROVISIONAL"
APPLICATION_TYPES = {APP_TYPE_UTILITY, APP_TYPE_DESIGN, APP_TYPE_PROVISIONAL}

# Continuation type enum
CONT_NONE = "NONE"
CONT_CONTINUATION = "CONTINUATION"
CONT_CIP = "CIP"
CONTINUATION_TYPES = {CONT_NONE, CONT_CONTINUATION, CONT_CIP}

# Application status enum (SCAFFOLD §1.1)
APP_STATUS_DRAFT = "DRAFT"
APP_STATUS_FILED = "FILED"
APP_STATUS_UNDER_EXAMINATION = "UNDER_EXAMINATION"
APP_STATUS_OFFICE_ACTION_PENDING = "OFFICE_ACTION_PENDING"
APP_STATUS_ALLOWED = "ALLOWED"
APP_STATUS_GRANTED = "GRANTED"
APP_STATUS_ABANDONED = "ABANDONED"
APP_STATUS_EXPIRED = "EXPIRED"
APPLICATION_STATUSES = {
    APP_STATUS_DRAFT,
    APP_STATUS_FILED,
    APP_STATUS_UNDER_EXAMINATION,
    APP_STATUS_OFFICE_ACTION_PENDING,
    APP_STATUS_ALLOWED,
    APP_STATUS_GRANTED,
    APP_STATUS_ABANDONED,
    APP_STATUS_EXPIRED,
}
# Statuses that count as "pending" for continuation parent eligibility (§1.4 / §3.2)
CONTINUATION_PARENT_OK_STATUSES = {
    APP_STATUS_FILED,
    APP_STATUS_UNDER_EXAMINATION,
    APP_STATUS_OFFICE_ACTION_PENDING,
    APP_STATUS_ALLOWED,
    APP_STATUS_GRANTED,
}
# Statuses from which voluntary abandonment is permitted (§1.2 FILED -> ABANDONED)
VOLUNTARY_ABANDON_OK_STATUSES = {
    APP_STATUS_FILED,
    APP_STATUS_UNDER_EXAMINATION,
    APP_STATUS_OFFICE_ACTION_PENDING,
    APP_STATUS_ALLOWED,
}
# Statuses from which PCT initiation is permitted (§1.4 ERR_PCT_INELIGIBLE)
PCT_INIT_OK_STATUSES = {
    APP_STATUS_FILED,
    APP_STATUS_UNDER_EXAMINATION,
    APP_STATUS_OFFICE_ACTION_PENDING,
}

# -----------------------------------------------------------------------------
# Applicant status enum
# -----------------------------------------------------------------------------
APPLICANT_STATUS_ACTIVE = "ACTIVE"
APPLICANT_STATUS_SUSPENDED = "SUSPENDED"
APPLICANT_STATUSES = {APPLICANT_STATUS_ACTIVE, APPLICANT_STATUS_SUSPENDED}

# -----------------------------------------------------------------------------
# Office Action enums
# -----------------------------------------------------------------------------
OA_TYPE_NON_FINAL = "NON_FINAL"
OA_TYPE_FINAL = "FINAL"
OA_TYPES = {OA_TYPE_NON_FINAL, OA_TYPE_FINAL}

OA_STATUS_PENDING = "PENDING"
OA_STATUS_RESPONDED = "RESPONDED"
OA_STATUS_ABANDONED_BY_DEFAULT = "ABANDONED_BY_DEFAULT"
OA_STATUSES = {OA_STATUS_PENDING, OA_STATUS_RESPONDED, OA_STATUS_ABANDONED_BY_DEFAULT}

# -----------------------------------------------------------------------------
# Maintenance Fee enums
# -----------------------------------------------------------------------------
MAINT_STAGE_3_5 = "STAGE_3_5"
MAINT_STAGE_7_5 = "STAGE_7_5"
MAINT_STAGE_11_5 = "STAGE_11_5"
MAINTENANCE_STAGES = {MAINT_STAGE_3_5, MAINT_STAGE_7_5, MAINT_STAGE_11_5}
# Anchor years per stage (mid-year fractions intentional)
STAGE_ANCHOR_YEARS = {
    MAINT_STAGE_3_5: 3.5,
    MAINT_STAGE_7_5: 7.5,
    MAINT_STAGE_11_5: 11.5,
}

MAINT_STATUS_SCHEDULED = "SCHEDULED"
MAINT_STATUS_PAID = "PAID"
MAINT_STATUS_LAPSED = "LAPSED"
MAINTENANCE_STATUSES = {MAINT_STATUS_SCHEDULED, MAINT_STATUS_PAID, MAINT_STATUS_LAPSED}

# -----------------------------------------------------------------------------
# PCT phase enums
# -----------------------------------------------------------------------------
PCT_STATUS_INTERNATIONAL = "INTERNATIONAL"
PCT_STATUS_NATIONAL_ENTERED = "NATIONAL_ENTERED"
PCT_STATUS_LAPSED = "LAPSED"
PCT_STATUSES = {PCT_STATUS_INTERNATIONAL, PCT_STATUS_NATIONAL_ENTERED, PCT_STATUS_LAPSED}

# -----------------------------------------------------------------------------
# Fee category enum (SCAFFOLD FeeTransaction.fee_category)
# -----------------------------------------------------------------------------
FEE_CATEGORY_FILING = "FILING"
FEE_CATEGORY_EXCESS_CLAIM = "EXCESS_CLAIM"
FEE_CATEGORY_EXAMINATION = "EXAMINATION"
FEE_CATEGORY_ISSUE = "ISSUE"
FEE_CATEGORY_MAINTENANCE = "MAINTENANCE"
FEE_CATEGORY_EXTENSION = "EXTENSION"
FEE_CATEGORY_PCT_TRANSMITTAL = "PCT_TRANSMITTAL"
FEE_CATEGORY_PCT_NATIONAL = "PCT_NATIONAL"
FEE_CATEGORIES = {
    FEE_CATEGORY_FILING,
    FEE_CATEGORY_EXCESS_CLAIM,
    FEE_CATEGORY_EXAMINATION,
    FEE_CATEGORY_ISSUE,
    FEE_CATEGORY_MAINTENANCE,
    FEE_CATEGORY_EXTENSION,
    FEE_CATEGORY_PCT_TRANSMITTAL,
    FEE_CATEGORY_PCT_NATIONAL,
}

# -----------------------------------------------------------------------------
# Fee tables (SCAFFOLD §1.3 — all values in cents, large-entity base)
# -----------------------------------------------------------------------------
FILING_FEE_TABLE_CENTS = {
    APP_TYPE_UTILITY: 32000,
    APP_TYPE_DESIGN: 22000,
    APP_TYPE_PROVISIONAL: 30000,
}

# Examination fee — scaffold mentions it as "examination_fee" but does not pin
# a numeric value. Use a fixed large-entity base; tests can compare to the
# entity-adjusted amount produced by the computation function.
EXAMINATION_FEE_BASE_CENTS = 80000

# Issue fee — scaffold mentions "issue_fee" without a concrete value. Use a
# fixed large-entity base.
ISSUE_FEE_BASE_CENTS = 60000

EXCESS_TOTAL_CLAIM_UNIT_CENTS = 10001
EXCESS_INDEP_CLAIM_UNIT_CENTS = 48003

EXTENSION_FEE_TABLE_CENTS = {
    1: 22000,
    2: 64000,
    3: 148000,
}

MAINTENANCE_FEE_TABLE_CENTS = {
    MAINT_STAGE_3_5: 160000,
    MAINT_STAGE_7_5: 360000,
    MAINT_STAGE_11_5: 740000,
}
MAINTENANCE_SURCHARGE_CENTS = 16000

PCT_NATIONAL_BASE_CENTS = 51000

# -----------------------------------------------------------------------------
# Risk score weights (SCAFFOLD §1.3 applicant_risk_score)
# -----------------------------------------------------------------------------
RISK_LAPSED_WEIGHT = 25
RISK_ABANDONED_WEIGHT = 15
RISK_PENDING_WEIGHT = 5
RISK_SUSPEND_THRESHOLD = 75

# -----------------------------------------------------------------------------
# Term constants (SCAFFOLD §1.3 application_expiration)
# -----------------------------------------------------------------------------
PROVISIONAL_TERM_DAYS = 365
UTILITY_TERM_YEARS = 20
DESIGN_TERM_YEARS = 15

# Office Action statutory windows
OA_RESPONSE_DEADLINE_DAYS = 90
OA_EXTENDED_DEADLINE_DAYS = 180

# Maintenance grace period after due_at
MAINTENANCE_GRACE_PERIOD_DAYS = 180

# PCT national-phase deadline
PCT_NATIONAL_DEADLINE_MONTHS = 30

# Idempotency replay window
IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
