"""Domain types: entity TypedDicts, status enums, role enum for the RCM firm API."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    CODER = "Coder"
    BILLER = "Biller"
    DENIAL_SPECIALIST = "DenialSpecialist"
    PAYMENT_POSTER = "PaymentPoster"
    CREDENTIALING_SPECIALIST = "CredentialingSpecialist"
    PRACTICE_USER = "PracticeUser"


class PracticeStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PayerType(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"


class CredentialingStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class FeeScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SCRUBBED = "SCRUBBED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    PAID = "PAID"
    CLOSED = "CLOSED"
    VOID = "VOID"


class DenialStatus(str, Enum):
    OPEN = "OPEN"
    APPEALED = "APPEALED"
    OVERTURNED = "OVERTURNED"
    UPHELD = "UPHELD"
    WRITTEN_OFF = "WRITTEN_OFF"


class AppealStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    OVERTURNED = "OVERTURNED"
    UPHELD = "UPHELD"
    WITHDRAWN = "WITHDRAWN"


class RemittanceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    POSTING = "POSTING"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PostingStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    COLLECTIONS = "COLLECTIONS"
    WRITTEN_OFF = "WRITTEN_OFF"


class AgingBucket(str, Enum):
    CURRENT = "CURRENT"
    DAYS_31_60 = "DAYS_31_60"
    DAYS_61_90 = "DAYS_61_90"
    OVER_90 = "OVER_90"


# ---- Entity TypedDicts ----
# common_fields: true -> id, created_at, updated_at, version


class Practice(TypedDict):
    id: str
    name: str
    npi: str
    tax_id: str
    billing_fee_pct: float
    status: str
    ar_balance_cents: int
    collected_ytd_cents: int
    created_at: str
    updated_at: str
    version: int


class Payer(TypedDict):
    id: str
    name: str
    payer_type: str
    timely_filing_days: int
    appeal_window_days: int
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    practice_id: str
    npi: str
    first_name: str
    last_name: str
    specialty: str
    credentialing_status: str
    credentialing_expiration_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayerEnrollment(TypedDict):
    id: str
    provider_id: str
    payer_id: str
    effective_date: str
    termination_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict):
    id: str
    practice_id: str
    effective_date: str
    end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> only id + created_at
class FeeScheduleLine(TypedDict):
    id: str
    fee_schedule_id: str
    cpt_code: str
    allowed_amount_cents: int
    created_at: str


class Claim(TypedDict):
    id: str
    practice_id: str
    provider_id: str
    payer_id: str
    service_date: str
    deductible_remaining_cents: int
    coinsurance_pct: float
    copay_cents: int
    status: str
    billed_amount_cents: int
    allowed_amount_cents: int
    contractual_adjustment_cents: int
    patient_responsibility_cents: int
    expected_reimbursement_cents: int
    insurance_paid_cents: int
    write_off_cents: int
    outstanding_balance_cents: int
    scrubbed_by_user_id: Optional[str]
    submitted_by_user_id: Optional[str]
    submission_date: Optional[str]
    appeal_round: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> only id + created_at
class ClaimLine(TypedDict):
    id: str
    claim_id: str
    cpt_code: str
    units: int
    charge_amount_cents: int
    allowed_amount_cents: int
    created_at: str


class Denial(TypedDict):
    id: str
    claim_id: str
    denial_code: str
    denied_amount_cents: int
    denial_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    denial_id: str
    level: int
    narrative: str
    status: str
    recovered_amount_cents: int
    submitted_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemittanceAdvice(TypedDict):
    id: str
    payer_id: str
    remittance_ref: str
    total_amount_cents: int
    allocated_amount_cents: int
    unallocated_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentPosting(TypedDict):
    id: str
    remittance_id: str
    claim_id: str
    insurance_paid_cents: int
    patient_responsibility_cents: int
    adjustment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PatientStatement(TypedDict):
    id: str
    claim_id: str
    practice_id: str
    statement_amount_cents: int
    amount_paid_cents: int
    first_sent_date: Optional[str]
    aging_bucket: str
    status: str
    created_at: str
    updated_at: str
    version: int
