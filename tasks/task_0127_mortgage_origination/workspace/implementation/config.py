"""Constants and configuration values per PRD and SCAFFOLD."""

from decimal import Decimal

# -------------------------------------------------------------------------
# Roles (PRD §2.1)
# -------------------------------------------------------------------------
ROLE_LOAN_OFFICER = "LoanOfficer"
ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_BORROWER = "Borrower"
ROLE_ADMIN = "Admin"

VALID_ROLES = {ROLE_LOAN_OFFICER, ROLE_COMPLIANCE_OFFICER, ROLE_BORROWER, ROLE_ADMIN}

# -------------------------------------------------------------------------
# Pagination (PRD §2.3, SCAFFOLD response_envelope.pagination_defaults)
# -------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# -------------------------------------------------------------------------
# Clock (PRD §2.9)
# -------------------------------------------------------------------------
DEFAULT_CLOCK_ISO = "2026-01-01T00:00:00.000Z"

# -------------------------------------------------------------------------
# Calculation constants (SCAFFOLD §1.3)
# -------------------------------------------------------------------------
DTI_ESTIMATION_RATE_FACTOR = Decimal("0.0065")
DTI_PRECISION_DECIMALS = 4
DTI_CEILING = Decimal("0.43")

LTV_PRECISION_DECIMALS = 4
PMI_THRESHOLD = Decimal("0.80")
LTV_CEILING = Decimal("0.97")

PRE_QUAL_CREDIT_SCORE_MIN = 620
PRE_QUAL_LOAN_TO_INCOME_MULTIPLIER = 4

# Income verification: documented must be within 20% below stated
INCOME_VERIFICATION_THRESHOLD = Decimal("0.80")

# Asset verification: materiality floor
ASSET_VERIFICATION_MIN_CENTS = 1000

# APR tolerance (strict comparison: > 12 triggers re-disclosure)
APR_TOLERANCE_BPS = 12

# TRID business-day waiting period
TRID_BUSINESS_DAYS_REQUIRED = 3
HOLIDAYS_2026 = {"2026-01-01", "2026-07-06", "2026-12-25"}

# Closing-cost origination fee tiers (boundaries inclusive at the low end of each higher tier)
TIER_LOW_CENTS = 41_700_000   # $417,000
TIER_MID_CENTS = 76_600_000   # $766,000

# State tax rates (decimal proportion)
STATE_TAX_RATES = {
    "CA": Decimal("0.0050"),
    "NY": Decimal("0.0125"),
    "TX": Decimal("0.0075"),
}
DEFAULT_STATE_TAX_RATE = Decimal("0.0100")

# Origination fee tiers
ORIGINATION_FEE_TIER_LOW = Decimal("0.01")    # 1.00%
ORIGINATION_FEE_TIER_MID = Decimal("0.0075")  # 0.75%
ORIGINATION_FEE_TIER_HIGH = Decimal("0.005")  # 0.50%

# Rate-lock
LOCK_DURATION_DAYS = 45
LOCK_FEE_BPS = 25  # 0.25% of requested_loan_amount_cents
FREE_LOOK_HOURS = 48
EXTENSION_FEE_BPS = {7: 5, 15: 10, 30: 25}
EXTENSION_CAP_DAYS = 60
EXTENSION_ALLOWED_DAYS = {7, 15, 30}

# Appraisal
APPRAISAL_VALIDITY_DAYS = 120

# Loan-application enums
LOAN_TERM_MONTHS_ALLOWED = {120, 180, 240, 360}
LOAN_PURPOSE_ALLOWED = {"PURCHASE", "REFINANCE"}

# Verification source enums
INCOME_SOURCE_TYPES = {"W2", "SELF_EMPLOYED", "OTHER"}
ASSET_TYPES = {"CHECKING", "SAVINGS", "INVESTMENT", "GIFT"}

# Disclosure kinds
DISCLOSURE_KIND_LE = "LOAN_ESTIMATE"
DISCLOSURE_KIND_CD = "CLOSING_DISCLOSURE"
DISCLOSURE_KINDS = {DISCLOSURE_KIND_LE, DISCLOSURE_KIND_CD}

# UDAAP outcomes
UDAAP_OUTCOMES = {"PASS", "FLAG", "BLOCK"}

# Underwrite decision values
DECISION_APPROVE = "APPROVE"
DECISION_COUNTER = "COUNTER_OFFER"
DECISION_DENY = "DENY"
UNDERWRITE_DECISIONS = {DECISION_APPROVE, DECISION_COUNTER, DECISION_DENY}

# Loan application states
APP_INTAKE = "INTAKE"
APP_PRE_QUALIFIED = "PRE_QUALIFIED"
APP_UNDERWRITING = "UNDERWRITING"
APP_CONDITIONAL_APPROVAL = "CONDITIONAL_APPROVAL"
APP_CLEAR_TO_CLOSE = "CLEAR_TO_CLOSE"
APP_CLOSED = "CLOSED"
APP_DENIED = "DENIED"
APP_WITHDRAWN = "WITHDRAWN"
APP_TERMINAL = {APP_CLOSED, APP_DENIED, APP_WITHDRAWN}

# Rate lock states
LOCK_LOCKED = "LOCKED"
LOCK_EXTENDED = "EXTENDED"
LOCK_EXPIRED = "EXPIRED"
LOCK_CONSUMED = "CONSUMED"
LOCK_CANCELLED = "CANCELLED"
LOCK_ACTIVE = {LOCK_LOCKED, LOCK_EXTENDED}

# Verification states
VER_PENDING = "PENDING"
VER_VERIFIED = "VERIFIED"
VER_REJECTED = "REJECTED"

# Appraisal states
APR_ORDERED = "ORDERED"
APR_COMPLETED = "COMPLETED"
APR_REJECTED = "REJECTED"
APR_EXPIRED = "EXPIRED"

# Title states
TITLE_ORDERED = "ORDERED"
TITLE_CLEAR = "CLEAR"
TITLE_ISSUES = "ISSUES_FOUND"
TITLE_RESOLVED = "RESOLVED"
TITLE_OK_FOR_UNDERWRITING = {TITLE_CLEAR, TITLE_RESOLVED}

# Disclosure states
DISC_ISSUED = "ISSUED"
DISC_ACK = "ACKNOWLEDGED"
DISC_SUPERSEDED = "SUPERSEDED"
DISC_VOIDED = "VOIDED"
DISC_NON_TERMINAL = {DISC_ISSUED, DISC_ACK}
