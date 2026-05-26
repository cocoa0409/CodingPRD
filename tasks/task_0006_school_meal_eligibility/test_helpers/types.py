"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PARENT = "Parent"
    SCHOOL_STAFF = "SchoolStaff"
    DISTRICT_REVIEWER = "DistrictReviewer"
    USDA_AUDITOR = "USDAAuditor"
    PLATFORM_ADMIN = "PlatformAdmin"


class MealApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    WITHDRAWN = "WITHDRAWN"


class EligibilityLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class EligibilityVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    DEFERRED = "DEFERRED"


class EligibilitySource(str, Enum):
    APPLICATION = "APPLICATION"
    DIRECT_CERTIFICATION = "DIRECT_CERTIFICATION"
    AUTO_RENEWAL = "AUTO_RENEWAL"


class EligibilityTier(str, Enum):
    FREE = "FREE"
    REDUCED = "REDUCED"
    PAID = "PAID"


class ServiceTransactionStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    REFUNDED = "REFUNDED"
    DISPUTED = "DISPUTED"


class RejectionReason(str, Enum):
    ALLERGEN_CONFLICT = "ALLERGEN_CONFLICT"
    INELIGIBLE_STATE = "INELIGIBLE_STATE"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    MANUAL = "MANUAL"


class LedgerEntryType(str, Enum):
    TOPUP = "TOPUP"
    MEAL_CHARGE = "MEAL_CHARGE"
    MEAL_REFUND = "MEAL_REFUND"
    ADJUSTMENT = "ADJUSTMENT"


class AllergyCode(str, Enum):
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    MILK = "MILK"
    EGG = "EGG"
    SOY = "SOY"
    WHEAT = "WHEAT"
    FISH = "FISH"
    SHELLFISH = "SHELLFISH"


class AllergySeverity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE_ANAPHYLACTIC = "SEVERE_ANAPHYLACTIC"


class ReimbursementClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FINALIZED = "FINALIZED"
    REJECTED = "REJECTED"


class AccountingBasis(str, Enum):
    CASH = "CASH"
    ACCRUAL = "ACCRUAL"


# ---------------------------------------------------------------------
# Entity TypedDicts — common_fields: true entities carry id + created_at +
# updated_at + version. LedgerEntry (common_fields: false) carries ONLY id +
# created_at.
# ---------------------------------------------------------------------

class Household(TypedDict, total=False):
    id: str
    primary_parent_name: str
    family_size: int
    annual_income_cents: int
    address_state: str
    direct_certification_flag: bool
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    household_id: str
    full_name: str
    school_code: str
    grade_level: int
    created_at: str
    updated_at: str
    version: int


class AllergyProfile(TypedDict, total=False):
    id: str
    student_id: str
    allergens: List[str]
    severity: str
    created_at: str
    updated_at: str
    version: int


class MealApplication(TypedDict, total=False):
    id: str
    household_id: str
    status: str
    snapshot_family_size: Optional[int]
    snapshot_annual_income_cents: Optional[int]
    snapshot_address_state: Optional[str]
    school_year: str
    decision_reason: Optional[str]
    appeal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EligibilityDetermination(TypedDict, total=False):
    id: str
    household_id: str
    source_application_id: Optional[str]
    source: str
    tier: str
    lifecycle_status: str
    verification_status: str
    valid_from_utc: str
    valid_to_utc: str
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict, total=False):
    id: str
    school_code: str
    name: str
    list_price_cents: int
    federal_reimbursement_free_cents: int
    federal_reimbursement_reduced_cents: int
    federal_reimbursement_paid_cents: int
    allergens_present: List[str]
    calories: int
    created_at: str
    updated_at: str
    version: int


class ParentAccount(TypedDict, total=False):
    id: str
    household_id: str
    balance_cents: int
    daily_topup_total_cents: int
    daily_topup_window_date: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only audit row
class LedgerEntry(TypedDict, total=False):
    id: str
    parent_account_id: str
    entry_type: str
    amount_cents: int
    linked_transaction_id: Optional[str]
    idempotency_key: Optional[str]
    created_at: str


class ServiceTransaction(TypedDict, total=False):
    id: str
    student_id: str
    menu_item_id: str
    eligibility_determination_id: Optional[str]
    applied_tier: Optional[str]
    status: str
    paid_charge_cents: int
    federal_reimbursement_cents: int
    rejection_reason: Optional[str]
    served_at_utc: str
    created_at: str
    updated_at: str
    version: int


class ReimbursementClaim(TypedDict, total=False):
    id: str
    school_code: str
    period_start_utc: str
    period_end_utc: str
    status: str
    accounting_basis: str
    total_reimbursement_cents: int
    included_transaction_count: int
    created_at: str
    updated_at: str
    version: int
