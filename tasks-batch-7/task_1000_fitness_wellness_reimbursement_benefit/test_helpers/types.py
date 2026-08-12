"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    BENEFITS_ADMIN = "BenefitsAdmin"
    CLAIMS_REVIEWER = "ClaimsReviewer"
    MEMBER = "Member"
    PROVIDER_OPERATOR = "ProviderOperator"
    AUDITOR = "Auditor"
    PLATFORM_ADMIN = "PlatformAdmin"


class EmployerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FundingModel(str, Enum):
    PREFUNDED = "PREFUNDED"
    PAY_AS_YOU_GO = "PAY_AS_YOU_GO"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TierCode(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    COUPLE = "COUPLE"
    FAMILY = "FAMILY"


class EligibilityStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class DependentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class Relationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    DOMESTIC_PARTNER = "DOMESTIC_PARTNER"


class Modality(str, Enum):
    GYM = "GYM"
    STUDIO = "STUDIO"
    APP = "APP"
    POOL = "POOL"


class NetworkTier(str, Enum):
    IN_NETWORK = "IN_NETWORK"
    PREFERRED = "PREFERRED"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"


class ProviderStatus(str, Enum):
    PENDING_ONBOARD = "PENDING_ONBOARD"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class VisitStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class VerificationMethod(str, Enum):
    GEO_FENCE = "GEO_FENCE"
    POS_SWIPE = "POS_SWIPE"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ClaimType(str, Enum):
    REIMBURSEMENT = "REIMBURSEMENT"
    DIRECT_PAY = "DIRECT_PAY"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REVERSED = "REVERSED"
    CLAWED_BACK = "CLAWED_BACK"


class FundingAccountStatus(str, Enum):
    FUNDED = "FUNDED"
    DEPLETED = "DEPLETED"
    SUSPENDED = "SUSPENDED"


class FundingEntryType(str, Enum):
    DEPOSIT = "DEPOSIT"
    HOLD = "HOLD"
    RELEASE = "RELEASE"
    DEBIT = "DEBIT"
    CLAWBACK_CREDIT = "CLAWBACK_CREDIT"


class FraudSignal(str, Enum):
    VELOCITY = "VELOCITY"
    OVERLAP_PATTERN = "OVERLAP_PATTERN"
    DUPLICATE_RECEIPT = "DUPLICATE_RECEIPT"
    GEOFENCE_MISMATCH = "GEOFENCE_MISMATCH"
    PROVIDER_PATTERN = "PROVIDER_PATTERN"


class FraudFlagStatus(str, Enum):
    OPEN = "OPEN"
    CONFIRMED = "CONFIRMED"
    CLEARED = "CLEARED"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    DELIVERED = "DELIVERED"


# --- Entity TypedDicts ---
# Common-field resources carry id + created_at + updated_at + version.
# PlanTier and FundingEntry rows carry only id + created_at (no updated_at, no version).


class Employer(TypedDict, total=False):
    id: str
    name: str
    funding_model: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BenefitPlan(TypedDict, total=False):
    id: str
    employer_id: str
    name: str
    benefit_year: int
    period_start: str
    period_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanTier(TypedDict, total=False):
    id: str
    plan_id: str
    tier_code: str
    annual_allowance_cents: int
    quarterly_cap_cents: int
    per_claim_cap_cents: int
    visit_frequency_cap: int
    dependent_cap_pct: float
    in_network_pct: float
    preferred_pct: float
    out_of_network_pct: float
    created_at: str


class Member(TypedDict, total=False):
    id: str
    employer_id: str
    plan_id: str
    external_ref: str
    full_name: str
    tier_code: str
    hire_date: str
    eligibility_date: str
    eligibility_status: str
    created_at: str
    updated_at: str
    version: int


class Dependent(TypedDict, total=False):
    id: str
    member_id: str
    full_name: str
    relationship: str
    birth_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    name: str
    modality: str
    network_tier: str
    contract_start: str
    contract_end: str
    visit_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    member_id: str
    plan_id: str
    tier_code: str
    annual_allowance_cents: int
    quarterly_cap_cents: int
    used_cents: int
    reserved_cents: int
    quarter_key: str
    quarter_used_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict, total=False):
    id: str
    enrollment_id: str
    member_id: str
    provider_id: str
    check_in_at: str
    check_out_at: str
    verification_method: str
    duration_minutes: int
    fraud_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    enrollment_id: str
    member_id: str
    provider_id: str
    claim_type: str
    service_date: str
    receipt_ref: str
    line_items: List[dict]
    visit_ids: List[str]
    claimed_amount_cents: int
    approved_amount_cents: Optional[int]
    review_status: str
    payment_status: str
    resubmission_count: int
    fraud_hold: bool
    quarter_key: str
    created_at: str
    updated_at: str
    version: int


class FundingAccount(TypedDict, total=False):
    id: str
    employer_id: str
    benefit_year: int
    funded_cents: int
    available_cents: int
    reserved_cents: int
    disbursed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingEntry(TypedDict, total=False):
    id: str
    funding_account_id: str
    claim_id: Optional[str]
    entry_type: str
    amount_cents: int
    running_available_cents: int
    created_at: str


class FraudFlag(TypedDict, total=False):
    id: str
    visit_id: Optional[str]
    claim_id: Optional[str]
    signal: str
    severity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Statement(TypedDict, total=False):
    id: str
    member_id: str
    period_yyyymm: str
    status: str
    provisional_total_cents: int
    finalized_total_cents: Optional[int]
    claim_count: int
    created_at: str
    updated_at: str
    version: int
