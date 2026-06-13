"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry id, created_at, updated_at, and version
(common resource properties with optimistic concurrency).
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    BURSAR = "Bursar"
    STUDENT = "Student"


# --- Status enums ---
class TermStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class PlanTemplateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OVERDUE = "OVERDUE"
    PAID = "PAID"


class ChargeStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class FinancialAidStatus(str, Enum):
    APPLIED = "APPLIED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    FAILED = "FAILED"


class LateFeeStatus(str, Enum):
    ASSESSED = "ASSESSED"
    WAIVED = "WAIVED"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


# --- Enum value categories ---
class ChargeKind(str, Enum):
    TUITION = "TUITION"
    FEE = "FEE"
    HOUSING = "HOUSING"


class AidSource(str, Enum):
    GRANT = "GRANT"
    SCHOLARSHIP = "SCHOLARSHIP"
    LOAN = "LOAN"


class PaymentPurpose(str, Enum):
    DOWN_PAYMENT = "DOWN_PAYMENT"
    INSTALLMENT = "INSTALLMENT"
    AUTOPAY = "AUTOPAY"


class RefundPolicy(str, Enum):
    DATE_BASED = "DATE_BASED"
    SCHEDULE_BASED = "SCHEDULE_BASED"


class HoldReason(str, Enum):
    DELINQUENCY_COUNT = "DELINQUENCY_COUNT"
    DELINQUENCY_AMOUNT = "DELINQUENCY_AMOUNT"


# --- Entity TypedDicts (all carry common fields) ---
class Institution(TypedDict):
    id: str
    name: str
    currency: str
    refund_policy: str
    clock_utc: str
    created_at: str
    updated_at: str
    version: int


class AcademicTerm(TypedDict):
    id: str
    institution_id: str
    code: str
    term_start: str
    term_end: str
    enroll_open: str
    enroll_close: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    institution_id: str
    external_ref: str
    full_name: str
    email: str
    has_active_hold: bool
    created_at: str
    updated_at: str
    version: int


class PlanTemplate(TypedDict):
    id: str
    institution_id: str
    name: str
    installment_count: int
    down_payment_pct: float
    plan_fee_cents: int
    late_fee_grace_days: int
    autopay_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    student_id: str
    term_id: str
    plan_template_id: str
    installment_count: int
    down_payment_pct: float
    plan_fee_cents: int
    autopay_enabled: bool
    gross_charges_cents: int
    total_aid_cents: int
    net_after_aid_cents: int
    down_payment_cents: int
    financed_principal_cents: int
    scheduled_balance_cents: int
    paid_principal_cents: int
    late_fee_balance_cents: int
    delinquent_installment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    enrollment_id: str
    sequence_index: int
    due_date: str
    amount_cents: int
    paid_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict):
    id: str
    enrollment_id: str
    kind: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancialAid(TypedDict):
    id: str
    enrollment_id: str
    source: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    enrollment_id: str
    installment_id: Optional[str]
    purpose: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LateFee(TypedDict):
    id: str
    enrollment_id: str
    installment_id: str
    days_late: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Hold(TypedDict):
    id: str
    student_id: str
    enrollment_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Withdrawal(TypedDict):
    id: str
    enrollment_id: str
    effective_date: str
    variant_used: str
    retained_charges_cents: int
    net_owed_after_withdrawal_cents: int
    refund_to_student_cents: int
    created_at: str
    updated_at: str
    version: int
