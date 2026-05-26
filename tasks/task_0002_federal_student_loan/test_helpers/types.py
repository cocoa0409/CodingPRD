"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ────────────────────────────────────────────
class LoanStatus(str, Enum):
    ORIGINATED = "ORIGINATED"
    IN_SCHOOL = "IN_SCHOOL"
    GRACE = "GRACE"
    REPAYMENT = "REPAYMENT"
    DEFERMENT = "DEFERMENT"
    FORBEARANCE = "FORBEARANCE"
    DEFAULT = "DEFAULT"
    PAID_OFF = "PAID_OFF"
    DISCHARGED = "DISCHARGED"


class RepaymentPlanStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"


class PlanType(str, Enum):
    STANDARD = "STANDARD"
    IBR = "IBR"
    PAYE = "PAYE"
    SAVE = "SAVE"


class LoanType(str, Enum):
    DIRECT_SUB = "DIRECT_SUB"
    DIRECT_UNSUB = "DIRECT_UNSUB"
    DIRECT_PLUS = "DIRECT_PLUS"


class IncomeCertificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class QualifyingEmploymentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class EmployerType(str, Enum):
    GOVERNMENT = "GOVERNMENT"
    NONPROFIT_501C3 = "NONPROFIT_501C3"
    OTHER_NONPROFIT = "OTHER_NONPROFIT"
    PRIVATE_NONQUALIFYING = "PRIVATE_NONQUALIFYING"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class DischargeApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DischargeType(str, Enum):
    VETERAN_TOTAL_DISABILITY = "VETERAN_TOTAL_DISABILITY"
    PSLF = "PSLF"


class ReasonCode(str, Enum):
    GRACE_AUTO_START = "GRACE_AUTO_START"
    GRACE_AUTO_END = "GRACE_AUTO_END"
    DEFERMENT_REQUEST = "DEFERMENT_REQUEST"
    FORBEARANCE_REQUEST = "FORBEARANCE_REQUEST"
    RESUME_REPAYMENT = "RESUME_REPAYMENT"
    DEFAULT_DECLARATION = "DEFAULT_DECLARATION"
    REHABILITATION_COMPLETE = "REHABILITATION_COMPLETE"
    PAY_OFF = "PAY_OFF"
    DISCHARGE_APPROVED = "DISCHARGE_APPROVED"


class UserRole(str, Enum):
    LoanServicer = "LoanServicer"
    Borrower = "Borrower"
    CollectionsAgent = "CollectionsAgent"


# ─── Entity TypedDicts ───────────────────────────────────────
# Entities with common_fields: true carry id + created_at + updated_at + version.
class Borrower(TypedDict, total=False):
    id: str
    full_name: str
    ssn_last4: str
    is_veteran: bool
    current_agi_cents: Optional[int]
    current_family_size: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    borrower_id: str
    loan_type: str
    principal_cents: int
    interest_rate_bps: int
    disbursement_date: str
    status: str
    principal_balance_cents: int
    accrued_interest_cents: int
    capitalized_interest_cents: int
    last_accrual_date: str
    delinquency_days: int
    pslf_qualifying_payment_count: int
    status_change_at: str
    created_at: str
    updated_at: str
    version: int


class RepaymentPlan(TypedDict, total=False):
    id: str
    loan_id: str
    plan_type: str
    status: str
    monthly_payment_cents: int
    effective_date: str
    superseded_by_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncomeCertification(TypedDict, total=False):
    id: str
    borrower_id: str
    agi_cents: int
    family_size: int
    state_code: str
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QualifyingEmployment(TypedDict, total=False):
    id: str
    borrower_id: str
    employer_name: str
    employer_type: str
    period_start: str
    period_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    loan_id: str
    repayment_plan_id: Optional[str]
    amount_cents: int
    payment_date: str
    status: str
    principal_applied_cents: int
    interest_applied_cents: int
    is_pslf_qualifying: bool
    reversed_by_payment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DischargeApplication(TypedDict, total=False):
    id: str
    loan_id: str
    discharge_type: str
    status: str
    review_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only audit-log entity — common_fields: false. Only id + created_at.
class StatusChange(TypedDict, total=False):
    id: str
    loan_id: str
    from_status: str
    to_status: str
    reason_code: str
    actor_role: str
    effective_at: str
    created_at: str
