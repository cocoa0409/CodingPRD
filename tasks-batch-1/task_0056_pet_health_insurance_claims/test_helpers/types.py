"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    POLICY_HOLDER = "PolicyHolder"
    UNDERWRITER = "Underwriter"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


class PolicyStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class PolicyYearStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ConditionExclusionStatus(str, Enum):
    PRE_EXISTING = "PRE_EXISTING"
    COVERED = "COVERED"


class ClaimType(str, Enum):
    ILLNESS = "ILLNESS"
    ACCIDENT = "ACCIDENT"
    WELLNESS = "WELLNESS"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"


class OcrStatus(str, Enum):
    PENDING_OCR = "PENDING_OCR"
    OCR_DONE = "OCR_DONE"
    REVIEW_NEEDED = "REVIEW_NEEDED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# All seven entities carry id/created_at/updated_at/version (common_fields: true).

class Account(TypedDict):
    id: str
    email: str
    full_name: str
    active_policy_count: int
    monthly_premium_cents: int
    multi_pet_discount_applied: bool
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    account_id: str
    pet_name: str
    species: str
    base_premium_cents: int
    annual_deductible_cents: int
    reimbursement_rate_bps: int
    annual_cap_cents: int
    waiting_period_days: int
    wellness_rider: bool
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PolicyYear(TypedDict):
    id: str
    policy_id: str
    year_index: int
    period_start: str
    period_end: str
    deductible_met_cents: int
    reimbursed_cents: int
    wellness_used_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MedicalCondition(TypedDict):
    id: str
    policy_id: str
    name: str
    first_diagnosed_date: str
    exclusion_status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    condition_id: Optional[str]
    claim_type: str
    incident_date: str
    submitted_amount_cents: int
    eligible_amount_cents: int
    deductible_applied_cents: int
    reimbursed_cents: int
    wellness_paid_cents: int
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict):
    id: str
    claim_id: str
    description: str
    billed_amount_cents: int
    allowed_amount_cents: int
    excluded: bool
    created_at: str
    updated_at: str
    version: int


class InvoiceDocument(TypedDict):
    id: str
    claim_id: str
    file_uri: str
    ocr_total_cents: Optional[int]
    ocr_status: str
    ocr_mismatch_bps: Optional[int]
    created_at: str
    updated_at: str
    version: int
