"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity descriptions (§2.5 common fields, §3 workflows).
All primary resources carry id + created_at + updated_at + version (PRD §2.5).
"""
from enum import Enum
from typing import Optional, TypedDict


class ApplicationKind(str, Enum):
    INITIAL = "INITIAL"
    RECERTIFICATION = "RECERTIFICATION"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DocumentType(str, Enum):
    PROOF_OF_AGE = "PROOF_OF_AGE"
    PROOF_OF_INCOME = "PROOF_OF_INCOME"
    PROOF_OF_RESIDENCY = "PROOF_OF_RESIDENCY"


class DocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class CardholderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECERTIFICATION_DUE = "RECERTIFICATION_DUE"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class CardIssueReason(str, Enum):
    INITIAL = "INITIAL"
    REPLACEMENT = "REPLACEMENT"
    RENEWAL = "RENEWAL"


class CardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REPLACED = "REPLACED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class MerchantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class OfferCategory(str, Enum):
    GROCERY = "GROCERY"
    PHARMACY = "PHARMACY"
    DINING = "DINING"
    RETAIL = "RETAIL"
    SERVICES = "SERVICES"


class OfferStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class WaiverType(str, Enum):
    TRANSIT_FARE = "TRANSIT_FARE"
    FACILITY_FEE = "FACILITY_FEE"


class TransactionStatus(str, Enum):
    POSTED = "POSTED"
    FLAGGED = "FLAGGED"
    VOIDED = "VOIDED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    CARDHOLDER = "Cardholder"
    ELIGIBILITY_SPECIALIST = "EligibilitySpecialist"
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    MERCHANT_OPERATOR = "MerchantOperator"
    FRAUD_ANALYST = "FraudAnalyst"


class BenefitApplication(TypedDict, total=False):
    id: str
    kind: str
    applicant_full_name: str
    date_of_birth: str
    annual_income_cents: int
    residency_address: str
    cardholder_id: Optional[str]
    status: str
    reviewed_by_user_id: Optional[str]
    info_request_reason: Optional[str]
    denial_reason: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VerificationDocument(TypedDict, total=False):
    id: str
    application_id: str
    document_type: str
    document_reference: str
    status: str
    reviewed_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Cardholder(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    annual_income_cents: int
    residency_address: str
    status: str
    pre_suspension_status: Optional[str]
    recertification_due_date: str
    fraud_flag_count: int
    ytd_discount_cents: int
    ytd_transaction_count: int
    age_years: int
    created_at: str
    updated_at: str
    version: int


class BenefitCard(TypedDict, total=False):
    id: str
    cardholder_id: str
    card_number: str
    issue_reason: str
    status: str
    issued_at: str
    expires_at: str
    replaces_card_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Merchant(TypedDict, total=False):
    id: str
    name: str
    reimbursement_rate_pct: float
    monthly_reimbursement_cap_cents: int
    status: str
    current_month_reimbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class DiscountOffer(TypedDict, total=False):
    id: str
    merchant_id: str
    category: str
    discount_pct: float
    max_discount_cents: int
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeWaiverGrant(TypedDict, total=False):
    id: str
    cardholder_id: str
    waiver_type: str
    start_date: str
    end_date: str
    created_at: str
    updated_at: str
    version: int


class UsageTransaction(TypedDict, total=False):
    id: str
    card_id: str
    merchant_id: str
    cardholder_id: str
    offer_id: str
    category: str
    purchase_amount_cents: int
    discount_cents: int
    status: str
    flagged_by_user_id: Optional[str]
    flag_reason: Optional[str]
    voided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReimbursementClaim(TypedDict, total=False):
    id: str
    merchant_id: str
    period_month: str
    program_fund_id: Optional[str]
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramFund(TypedDict, total=False):
    id: str
    fiscal_year: int
    allocated_cents: int
    paid_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int
