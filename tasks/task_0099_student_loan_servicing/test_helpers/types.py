"""Domain types: entity TypedDicts, status enums, role enum.

Derived from PRD §3 entity descriptions and §2.4 audit-stamp rules.

Mutable entities (Borrower, Loan, RepaymentPlan, HardshipRequest,
DischargeApplication, EmploymentCertification) carry id + created_at +
updated_at + version per PRD §2.4. Immutable entities (Payment,
CollectionsAction, ClockState) carry only id + created_at — neither
updated_at nor version per the same section.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SERVICER_ADMIN = "ServicerAdmin"
    SERVICER_CERTIFIER = "ServicerCertifier"
    SERVICER_APPROVER = "ServicerApprover"
    COLLECTIONS_OFFICER = "CollectionsOfficer"
    BORROWER = "Borrower"
    SYSTEM_TEST = "SystemTest"


# ---------------------------------------------------------------------------
# Status enums (PRD §3.2, §3.5, §3.6, §3.7, §3.8, §3.9)
# ---------------------------------------------------------------------------
class LoanStatus(str, Enum):
    IN_SCHOOL = "IN_SCHOOL"
    GRACE = "GRACE"
    REPAYMENT = "REPAYMENT"
    DEFERMENT = "DEFERMENT"
    FORBEARANCE = "FORBEARANCE"
    DELINQUENT = "DELINQUENT"
    DEFAULT = "DEFAULT"
    REHABILITATION = "REHABILITATION"
    PAID_OFF = "PAID_OFF"
    DISCHARGED = "DISCHARGED"


class LoanType(str, Enum):
    DIRECT_SUBSIDIZED = "DIRECT_SUBSIDIZED"
    DIRECT_UNSUBSIDIZED = "DIRECT_UNSUBSIDIZED"
    DIRECT_PLUS = "DIRECT_PLUS"


class PlanType(str, Enum):
    STANDARD_10 = "STANDARD_10"
    IBR = "IBR"
    PAYE = "PAYE"
    SAVE = "SAVE"


class PlanStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class HardshipKind(str, Enum):
    DEFERMENT_IN_SCHOOL = "DEFERMENT_IN_SCHOOL"
    DEFERMENT_UNEMPLOYMENT = "DEFERMENT_UNEMPLOYMENT"
    DEFERMENT_ECONOMIC_HARDSHIP = "DEFERMENT_ECONOMIC_HARDSHIP"
    DEFERMENT_MILITARY = "DEFERMENT_MILITARY"
    FORBEARANCE_GENERAL = "FORBEARANCE_GENERAL"
    FORBEARANCE_MANDATORY = "FORBEARANCE_MANDATORY"


class HardshipStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DischargeProgram(str, Enum):
    PSLF = "PSLF"
    VETERAN_TPD = "VETERAN_TPD"


class DischargeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EmployerType(str, Enum):
    GOVERNMENT = "GOVERNMENT"
    NONPROFIT_501C3 = "NONPROFIT_501C3"
    OTHER_NONPROFIT_QUALIFYING = "OTHER_NONPROFIT_QUALIFYING"
    PRIVATE_NON_QUALIFYING = "PRIVATE_NON_QUALIFYING"


class CertificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PaymentSource(str, Enum):
    BORROWER = "BORROWER"
    EMPLOYER = "EMPLOYER"
    ADMINISTRATIVE_WAGE_GARNISHMENT = "ADMINISTRATIVE_WAGE_GARNISHMENT"
    TREASURY_OFFSET = "TREASURY_OFFSET"


class VeteranStatus(str, Enum):
    NONE = "NONE"
    VETERAN = "VETERAN"
    TPD_VETERAN = "TPD_VETERAN"


class CollectionsKind(str, Enum):
    DEFAULT_DECLARATION = "DEFAULT_DECLARATION"
    REHAB_AGREEMENT_OPEN = "REHAB_AGREEMENT_OPEN"
    REHAB_PAYMENT_RECORDED = "REHAB_PAYMENT_RECORDED"
    REHAB_COMPLETED = "REHAB_COMPLETED"
    WAGE_GARNISHMENT_ORDER = "WAGE_GARNISHMENT_ORDER"
    TREASURY_OFFSET_APPLIED = "TREASURY_OFFSET_APPLIED"


# ---------------------------------------------------------------------------
# Mutable entities — carry id + created_at + updated_at + version (PRD §2.4)
# ---------------------------------------------------------------------------
class Borrower(TypedDict, total=False):
    id: str
    full_name: str
    ssn_last4: str
    family_size: int
    state_code: str
    adjusted_gross_income_cents: int
    agi_certified_at: Optional[str]
    veteran_status: str
    aggregate_principal_balance_cents: int
    aggregate_interest_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    borrower_id: str
    loan_type: str
    original_principal_cents: int
    principal_balance_cents: int
    accrued_interest_cents: int
    capitalized_interest_cents: int
    interest_rate_bps: int
    disbursement_date: str
    status: str
    status_entered_at: str
    last_accrual_at: str
    last_payment_due_at: Optional[str]
    days_past_due: int
    qualifying_pslf_payment_count: int
    created_at: str
    updated_at: str
    version: int


class RepaymentPlan(TypedDict, total=False):
    id: str
    borrower_id: str
    plan_type: str
    status: str
    effective_from: Optional[str]
    certified_agi_cents: int
    certified_family_size: int
    monthly_payment_cents: int
    recertification_due_at: Optional[str]
    included_loan_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class HardshipRequest(TypedDict, total=False):
    id: str
    borrower_id: str
    kind: str
    requested_from: str
    requested_to: str
    cumulative_forbearance_days_at_request: int
    status: str
    applied_loan_ids: List[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DischargeApplication(TypedDict, total=False):
    id: str
    borrower_id: str
    program: str
    status: str
    approved_loan_ids: List[str]
    discharged_principal_cents: int
    discharged_interest_cents: int
    reviewed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmploymentCertification(TypedDict, total=False):
    id: str
    borrower_id: str
    employer_name: str
    employer_type: str
    period_start: str
    period_end: str
    status: str
    reviewed_by: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable entities — carry only id + created_at (PRD §2.4)
# ---------------------------------------------------------------------------
class PaymentAllocation(TypedDict, total=False):
    loan_id: str
    fees_cents: int
    interest_cents: int
    principal_cents: int
    refund_cents: int


class Payment(TypedDict, total=False):
    id: str
    borrower_id: str
    amount_cents: int
    received_at: str
    source: str
    pslf_qualifying: bool
    allocations: List[PaymentAllocation]
    created_at: str


class CollectionsAction(TypedDict, total=False):
    id: str
    borrower_id: str
    loan_id: str
    kind: str
    amount_cents: int
    occurred_at: str
    recorded_by: str
    created_at: str


class ClockState(TypedDict, total=False):
    id: str
    now: str
    created_at: str


__all__ = [
    "UserRole",
    "LoanStatus",
    "LoanType",
    "PlanType",
    "PlanStatus",
    "HardshipKind",
    "HardshipStatus",
    "DischargeProgram",
    "DischargeStatus",
    "EmployerType",
    "CertificationStatus",
    "PaymentSource",
    "VeteranStatus",
    "CollectionsKind",
    "Borrower",
    "Loan",
    "RepaymentPlan",
    "HardshipRequest",
    "DischargeApplication",
    "EmploymentCertification",
    "Payment",
    "PaymentAllocation",
    "CollectionsAction",
    "ClockState",
]
