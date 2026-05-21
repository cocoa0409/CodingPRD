"""Static configuration values for the DMV Registration/Title API.

All structural names — header names, envelope fields, pagination params,
role strings, jurisdiction code, calculation constants, fixed enforcement
instants — are defined here so the rest of the codebase reads them from a
single source of truth (SCAFFOLD.yaml / PRD.md).
"""

from decimal import Decimal

# -----------------------------------------------------------------------------
# Auth header names (PRD §2.1 / SCAFFOLD §1.4 priority-1 auth check)
# -----------------------------------------------------------------------------
HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# Roles enum (SCAFFOLD §1.7 / PRD §2.1) — exact spelling matters.
ROLE_APPLICANT = "Applicant"
ROLE_VIN_VERIFIER = "VinVerifier"
ROLE_TAX_ASSESSOR = "TaxAssessor"
ROLE_PLATE_ISSUER = "PlateIssuer"
ROLE_SALVAGE_OFFICER = "SalvageOfficer"
ROLE_EMISSIONS_INSPECTOR = "EmissionsInspector"
ROLE_LIEN_CLERK = "LienClerk"
ROLE_REAL_ID_REVIEWER = "RealIDReviewer"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLES = {
    ROLE_APPLICANT,
    ROLE_VIN_VERIFIER,
    ROLE_TAX_ASSESSOR,
    ROLE_PLATE_ISSUER,
    ROLE_SALVAGE_OFFICER,
    ROLE_EMISSIONS_INSPECTOR,
    ROLE_LIEN_CLERK,
    ROLE_REAL_ID_REVIEWER,
    ROLE_PLATFORM_ADMIN,
}

# -----------------------------------------------------------------------------
# Pagination defaults (SCAFFOLD.response_envelope.pagination_defaults / PRD §2.3)
# -----------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# -----------------------------------------------------------------------------
# Jurisdiction (PRD §3.1)
# -----------------------------------------------------------------------------
JURISDICTION_STATE_CODE = "CA"

# -----------------------------------------------------------------------------
# Enums — Owner
# -----------------------------------------------------------------------------
REAL_ID_NOT_APPLIED = "NOT_APPLIED"
REAL_ID_PENDING = "PENDING"
REAL_ID_APPROVED = "APPROVED"
REAL_ID_REVOKED = "REVOKED"
REAL_ID_STATUSES = {
    REAL_ID_NOT_APPLIED,
    REAL_ID_PENDING,
    REAL_ID_APPROVED,
    REAL_ID_REVOKED,
}

# -----------------------------------------------------------------------------
# Enums — Vehicle
# -----------------------------------------------------------------------------
VIN_UNVERIFIED = "UNVERIFIED"
VIN_VERIFIED = "VERIFIED"
VIN_MISMATCH = "MISMATCH"
VIN_HOLD = "HOLD"
VIN_VERIFICATION_STATUSES = {VIN_UNVERIFIED, VIN_VERIFIED, VIN_MISMATCH, VIN_HOLD}

TITLE_STATUS_CLEAN = "CLEAN"
TITLE_STATUS_SALVAGE_PENDING_REBUILD = "SALVAGE_PENDING_REBUILD"
TITLE_STATUS_REBUILT = "REBUILT"
TITLE_STATUS_NON_REPAIRABLE = "NON_REPAIRABLE"
TITLE_STATUSES = {
    TITLE_STATUS_CLEAN,
    TITLE_STATUS_SALVAGE_PENDING_REBUILD,
    TITLE_STATUS_REBUILT,
    TITLE_STATUS_NON_REPAIRABLE,
}

LIEN_STATUS_NONE = "NONE"
LIEN_STATUS_ACTIVE = "ACTIVE"
LIEN_STATUS_RELEASED = "RELEASED"
LIEN_STATUSES = {LIEN_STATUS_NONE, LIEN_STATUS_ACTIVE, LIEN_STATUS_RELEASED}

FUEL_GASOLINE = "GASOLINE"
FUEL_DIESEL = "DIESEL"
FUEL_HYBRID = "HYBRID"
FUEL_ELECTRIC = "ELECTRIC"
FUEL_TYPES = {FUEL_GASOLINE, FUEL_DIESEL, FUEL_HYBRID, FUEL_ELECTRIC}

# -----------------------------------------------------------------------------
# Enums — Title brand
# -----------------------------------------------------------------------------
TITLE_BRAND_CLEAN = "CLEAN"
TITLE_BRAND_SALVAGE = "SALVAGE"
TITLE_BRAND_REBUILT = "REBUILT"
TITLE_BRAND_FLOOD = "FLOOD"
TITLE_BRAND_LEMON = "LEMON"
TITLE_BRANDS = {
    TITLE_BRAND_CLEAN,
    TITLE_BRAND_SALVAGE,
    TITLE_BRAND_REBUILT,
    TITLE_BRAND_FLOOD,
    TITLE_BRAND_LEMON,
}

# -----------------------------------------------------------------------------
# Enums — LienRecord
# -----------------------------------------------------------------------------
LIEN_RECORD_ACTIVE = "ACTIVE"
LIEN_RECORD_RELEASED = "RELEASED"
LIEN_RECORD_STATUSES = {LIEN_RECORD_ACTIVE, LIEN_RECORD_RELEASED}

# -----------------------------------------------------------------------------
# Enums — EmissionsInspection
# -----------------------------------------------------------------------------
INSPECTION_SCHEDULED = "SCHEDULED"
INSPECTION_IN_PROGRESS = "IN_PROGRESS"
INSPECTION_PASSED = "PASSED"
INSPECTION_FAILED = "FAILED"
INSPECTION_CANCELLED = "CANCELLED"
INSPECTION_STATUSES = {
    INSPECTION_SCHEDULED,
    INSPECTION_IN_PROGRESS,
    INSPECTION_PASSED,
    INSPECTION_FAILED,
    INSPECTION_CANCELLED,
}

# -----------------------------------------------------------------------------
# Enums — RealIDApplication
# -----------------------------------------------------------------------------
REALID_SUBMITTED = "SUBMITTED"
REALID_DOC_REVIEW = "DOC_REVIEW"
REALID_APPROVED = "APPROVED"
REALID_DOC_REJECTED = "DOC_REJECTED"
REALID_REVOKED = "REVOKED"
REALID_APP_STATUSES = {
    REALID_SUBMITTED,
    REALID_DOC_REVIEW,
    REALID_APPROVED,
    REALID_DOC_REJECTED,
    REALID_REVOKED,
}

# -----------------------------------------------------------------------------
# Enums — Plate
# -----------------------------------------------------------------------------
PLATE_ISSUED = "ISSUED"
PLATE_ACTIVE = "ACTIVE"
PLATE_SUSPENDED = "SUSPENDED"
PLATE_SURRENDERED = "SURRENDERED"
PLATE_STATUSES = {PLATE_ISSUED, PLATE_ACTIVE, PLATE_SUSPENDED, PLATE_SURRENDERED}

PLATE_SURRENDER_SALVAGE_TRIGGERED = "SALVAGE_TRIGGERED"
PLATE_SURRENDER_OWNER_REQUEST = "OWNER_REQUEST"
PLATE_SURRENDER_LIEN_DEFAULT = "LIEN_DEFAULT"
PLATE_SURRENDER_TRANSFER_COMPLETE = "TRANSFER_COMPLETE"
PLATE_SURRENDER_REASONS = {
    PLATE_SURRENDER_SALVAGE_TRIGGERED,
    PLATE_SURRENDER_OWNER_REQUEST,
    PLATE_SURRENDER_LIEN_DEFAULT,
    PLATE_SURRENDER_TRANSFER_COMPLETE,
}

# -----------------------------------------------------------------------------
# Enums — TransferApplication
# -----------------------------------------------------------------------------
APP_TYPE_INITIAL_REGISTRATION = "INITIAL_REGISTRATION"
APP_TYPE_TITLE_TRANSFER = "TITLE_TRANSFER"
APPLICATION_TYPES = {APP_TYPE_INITIAL_REGISTRATION, APP_TYPE_TITLE_TRANSFER}

TXAPP_DRAFT = "DRAFT"
TXAPP_VIN_VERIFIED = "VIN_VERIFIED"
TXAPP_SALVAGE_REVIEW = "SALVAGE_REVIEW"
TXAPP_SALVAGE_APPROVED = "SALVAGE_APPROVED"
TXAPP_EMISSIONS_PENDING = "EMISSIONS_PENDING"
TXAPP_EMISSIONS_PASSED = "EMISSIONS_PASSED"
TXAPP_TAX_ASSESSED = "TAX_ASSESSED"
TXAPP_PLATE_ISSUED = "PLATE_ISSUED"
TXAPP_COMPLETED = "COMPLETED"
TXAPP_REJECTED = "REJECTED"
TXAPP_STATUSES = {
    TXAPP_DRAFT,
    TXAPP_VIN_VERIFIED,
    TXAPP_SALVAGE_REVIEW,
    TXAPP_SALVAGE_APPROVED,
    TXAPP_EMISSIONS_PENDING,
    TXAPP_EMISSIONS_PASSED,
    TXAPP_TAX_ASSESSED,
    TXAPP_PLATE_ISSUED,
    TXAPP_COMPLETED,
    TXAPP_REJECTED,
}
# Frozen states under REAL ID revocation cascade (§3.10)
TXAPP_REAL_ID_FREEZE_STATES = {
    TXAPP_VIN_VERIFIED,
    TXAPP_EMISSIONS_PENDING,
    TXAPP_EMISSIONS_PASSED,
    TXAPP_TAX_ASSESSED,
}
# States that get rerouted into SALVAGE_REVIEW on salvage cascade (§3.3)
TXAPP_SALVAGE_CASCADE_STATES = {
    TXAPP_VIN_VERIFIED,
    TXAPP_EMISSIONS_PENDING,
    TXAPP_EMISSIONS_PASSED,
    TXAPP_TAX_ASSESSED,
}

# Rejection reasons
REJECTION_EMISSIONS_FAILED = "EMISSIONS_FAILED"
REJECTION_NON_REPAIRABLE_SALVAGE = "NON_REPAIRABLE_SALVAGE"
REJECTION_UNPAID_TIMEOUT = "UNPAID_TIMEOUT"
REJECTION_OWNER_HOLDS = "OWNER_HOLDS"
REJECTION_WITHDRAWN = "WITHDRAWN"

# Salvage severity
SALVAGE_PARTIAL = "PARTIAL"
SALVAGE_TOTAL = "TOTAL"
SALVAGE_SEVERITIES = {SALVAGE_PARTIAL, SALVAGE_TOTAL}

# Approve-salvage decisions
SALVAGE_DECISION_APPROVE = "APPROVE"
SALVAGE_DECISION_DENY = "DENY"

# Emissions outcome
EMISSIONS_OUTCOME_PASSED = "PASSED"
EMISSIONS_OUTCOME_FAILED = "FAILED"

# Ledger kinds
LEDGER_SALES_TAX = "SALES_TAX"
LEDGER_REG_FEE = "REG_FEE"
LEDGER_PROCESSING_FEE = "PROCESSING_FEE"
LEDGER_REFUND_TAX = "REFUND_TAX"
LEDGER_REFUND_REG = "REFUND_REG"
LEDGER_REFUND_PROCESSING = "REFUND_PROCESSING"

# -----------------------------------------------------------------------------
# Calculation constants (SCAFFOLD §1.3)
# -----------------------------------------------------------------------------
# registration_fee
BASE_LIGHT = Decimal("65.00")  # < 3000 lbs
BASE_MID = Decimal("110.00")   # >= 3000, < 6000
BASE_HEAVY = Decimal("185.00")  # >= 6000
WEIGHT_LIGHT_MAX_EXCL = 3000
WEIGHT_HEAVY_MIN_INCL = 6000
AGE_FACTOR_STEP = Decimal("0.05")
AGE_FACTOR_FLOOR = Decimal("0.50")
COUNTY_SURCHARGE = Decimal("22.00")
NON_RESIDENT_SURCHARGE = Decimal("55.00")

# sales_tax_on_transfer
RATE_RESIDENT = Decimal("0.0725")
RATE_NON_RESIDENT = Decimal("0.085")

# total_due_with_processing
TIER_1_MAX = Decimal("200.00")
TIER_2_MAX = Decimal("1000.00")
TIER_3_MAX = Decimal("5000.00")
TIER_1_FEE = Decimal("8.00")
TIER_2_FEE = Decimal("18.00")
TIER_3_FEE = Decimal("38.00")
TIER_4_RATE = Decimal("0.02")

# REAL ID scoring
ID_WEIGHT = 40
RES_WEIGHT = 30
SSN_WEIGHT = 25
AGE_BONUS = 5
REVISION_PENALTY_PER_CYCLE = 5
AGE_BONUS_MIN_INCL = 18
AGE_BONUS_MAX_INCL = 80
APPROVAL_THRESHOLD = Decimal("80.00")

# Emissions expiry
EMISSIONS_EXPIRY_DAYS = 730  # 24 months

# Transfer-application tax-assessed unpaid timeout
UNPAID_TIMEOUT_DAYS = 7

# REAL ID approved expiry
REALID_APPROVED_EXPIRY_YEARS = 8

# Federal REAL ID enforcement instant — strict before allows non-APPROVED issuance
# 2027-05-07T00:00:00Z
REALID_ENFORCEMENT_ISO = "2027-05-07T00:00:00Z"

# Inspection schedule grace
INSPECTION_START_GRACE_MINUTES = 15

# Inspection slot buffer
INSPECTION_SLOT_BUFFER_MINUTES = 15

# Resubmit limit
REALID_MAX_REVISIONS = 3
