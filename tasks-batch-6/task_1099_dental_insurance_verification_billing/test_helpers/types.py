"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    FRONT_OFFICE = "FrontOffice"
    BILLER = "Biller"
    BILLING_MANAGER = "BillingManager"
    PATIENT = "Patient"


class PatientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COLLECTIONS = "COLLECTIONS"


class CoverageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"


class PreAuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PENDED = "PENDED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    CLOSED = "CLOSED"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    email: str
    status: str
    balance_cents: int
    created_at: str
    updated_at: str
    version: int


class InsurancePlan(TypedDict):
    id: str
    payer_name: str
    plan_name: str
    annual_maximum_cents: int
    deductible_cents: int
    deductible_applies_to: List[str]
    preventive_coinsurance_pct: int
    basic_coinsurance_pct: int
    major_coinsurance_pct: int
    cob_method: str
    created_at: str
    updated_at: str
    version: int


class Procedure(TypedDict):
    id: str
    cdt_code: str
    description: str
    category: str
    ucr_fee_cents: int
    frequency_limit_per_year: Optional[int]
    requires_narrative: bool
    requires_attachment: bool
    created_at: str
    updated_at: str
    version: int


class Coverage(TypedDict):
    id: str
    patient_id: str
    insurance_plan_id: str
    priority: str
    subscriber_id: str
    relationship: str
    effective_date: str
    term_date: str
    status: str
    benefits_used_cents: int
    deductible_met_cents: int
    created_at: str
    updated_at: str
    version: int


class Verification(TypedDict):
    id: str
    coverage_id: str
    verified_annual_maximum_cents: int
    verified_deductible_cents: int
    verified_preventive_pct: int
    verified_basic_pct: int
    verified_major_pct: int
    verified_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PreAuthorization(TypedDict):
    id: str
    patient_id: str
    coverage_id: str
    procedures: list
    narrative: Optional[str]
    status: str
    estimated_benefit_cents: int
    approved_amount_cents: Optional[int]
    attachment_count: int
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class Attachment(TypedDict):
    id: str
    claim_id: Optional[str]
    preauth_id: Optional[str]
    kind: str
    filename: str
    note: Optional[str]
    created_at: str


class Claim(TypedDict):
    id: str
    patient_id: str
    coverage_id: str
    preauth_id: Optional[str]
    primary_claim_id: Optional[str]
    procedures: list
    narrative: Optional[str]
    service_date: str
    status: str
    total_billed_cents: int
    estimated_insurance_cents: int
    estimated_patient_portion_cents: int
    paid_insurance_cents: int
    final_patient_portion_cents: int
    patient_paid_cents: int
    submitted_by_user_id: Optional[str]
    submitted_at: Optional[str]
    adjudicated_at: Optional[str]
    appeal_count: int
    aging_days: int
    aging_bucket: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    claim_id: Optional[str]
    patient_id: str
    payer_type: str
    amount_cents: int
    eob_lines: Optional[list]
    is_denial: bool
    status: str
    posted_at: str
    created_at: str
    updated_at: str
    version: int


class MembershipPlan(TypedDict):
    id: str
    name: str
    annual_fee_cents: int
    billing_period: str
    discount_pct: int
    included_cdt_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    patient_id: str
    membership_plan_id: str
    status: str
    enrolled_at: str
    period_start: str
    period_end: str
    paid_through_date: str
    next_billing_date: str
    balance_cents: int
    past_due_periods: int
    created_at: str
    updated_at: str
    version: int
