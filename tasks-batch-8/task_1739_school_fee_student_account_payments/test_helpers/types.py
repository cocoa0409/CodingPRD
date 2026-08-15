"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    BOOKKEEPER = "Bookkeeper"
    FAMILY_MEMBER = "FamilyMember"
    SUPERINTENDENT = "Superintendent"


class SchoolYearStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class StudentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"
    GRADUATED = "GRADUATED"


class AccountPosture(str, Enum):
    CLEAR = "CLEAR"
    GRADUATION_HOLD = "GRADUATION_HOLD"
    COLLECTIONS = "COLLECTIONS"
    WRITTEN_OFF = "WRITTEN_OFF"


class OfferingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OfferingKind(str, Enum):
    COURSE = "COURSE"
    ACTIVITY = "ACTIVITY"


class FeeCatalogItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"
    DROPPED_BY_CANCELLATION = "DROPPED_BY_CANCELLATION"


class FeeAssessmentStatus(str, Enum):
    ASSESSED = "ASSESSED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    PAYMENT_PLAN = "PAYMENT_PLAN"
    DELINQUENT = "DELINQUENT"
    REFUNDED = "REFUNDED"
    WAIVED = "WAIVED"
    VOID = "VOID"


class PurchaseStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class WaiverProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class WaiverApplicationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    ACH = "ACH"
    CASH = "CASH"
    CHECK = "CHECK"


class OverpaymentPolicy(str, Enum):
    CREDIT_BALANCE = "CREDIT_BALANCE"
    REJECT = "REJECT"


class AllocationRule(str, Enum):
    INSTALLMENT_DUE = "INSTALLMENT_DUE"
    OLDEST_OUTSTANDING = "OLDEST_OUTSTANDING"


class PaymentPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"
    WAIVED_BY_DEFAULT = "WAIVED_BY_DEFAULT"


class RefundReason(str, Enum):
    WITHDRAWAL = "WITHDRAWAL"
    ACTIVITY_CANCELLATION = "ACTIVITY_CANCELLATION"
    OVERPAYMENT_RETURN = "OVERPAYMENT_RETURN"
    WRITE_OFF_REVERSAL = "WRITE_OFF_REVERSAL"


class RefundStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    DENIED = "DENIED"


class LedgerEntryType(str, Enum):
    DISTRIBUTION_CREDIT = "DISTRIBUTION_CREDIT"
    DISTRIBUTION_REVERSAL = "DISTRIBUTION_REVERSAL"
    WRITE_OFF_DEBIT = "WRITE_OFF_DEBIT"
    WRITE_OFF_REVERSAL = "WRITE_OFF_REVERSAL"


class AgingBucket(str, Enum):
    CURRENT = "CURRENT"
    BUCKET_1 = "BUCKET_1"
    BUCKET_2 = "BUCKET_2"
    BUCKET_3 = "BUCKET_3"


class CollectionsCaseStatus(str, Enum):
    OPEN = "OPEN"
    PAYMENT_PROMISED = "PAYMENT_PROMISED"
    RESOLVED = "RESOLVED"
    WRITTEN_OFF = "WRITTEN_OFF"


# --- Entity TypedDicts ---
# Common-fields entities carry id + created_at + updated_at + version (PRD §2.5).
# PaymentAllocation and LedgerEntry are immutable ledger rows carrying ONLY
# id + created_at (PRD §2.5: "Both updated_at and version are absent on these
# two resources").

class SchoolYear(TypedDict, total=False):
    id: str
    label: str
    start_date: str
    end_date: str
    refund_full_days: int
    refund_partial_days: int
    partial_refund_pct_bp: int
    payment_plan_min_cents: int
    payment_plan_max_installments: int
    writeoff_max_cents: int
    aging_interval_days: int
    graduation_hold_threshold_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    external_ref: str
    full_name: str
    grade_level: int
    family_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StudentAccount(TypedDict, total=False):
    id: str
    school_year_id: str
    student_id: str
    assessed_cents: int
    waived_cents: int
    paid_cents: int
    balance_cents: int
    family_balance_cents: int
    posture: str
    last_posture_check_at: str
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict, total=False):
    id: str
    school_year_id: str
    code: str
    name: str
    distributed_cents: int
    reconciled_cents: int
    unreconciled_cents: int
    created_at: str
    updated_at: str
    version: int


class Offering(TypedDict, total=False):
    id: str
    school_year_id: str
    kind: str
    title: str
    department_id: str
    fee_item_id: str
    start_date: str
    end_date: str
    capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeCatalogItem(TypedDict, total=False):
    id: str
    school_year_id: str
    name: str
    amount_cents: int
    department_id: str
    waiverable: bool
    refundable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class OptionalPurchaseItem(TypedDict, total=False):
    id: str
    school_year_id: str
    name: str
    amount_cents: int
    department_id: str
    refundable: bool
    inventory_cap: int
    sold_count: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    student_account_id: str
    offering_id: str
    enrolled_at: str
    withdrawn_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict, total=False):
    id: str
    student_account_id: str
    enrollment_id: Optional[str]
    fee_item_id: str
    department_id: str
    assessed_amount_cents: int
    waived_amount_cents: int
    allocated_cents: int
    refunded_cents: int
    outstanding_cents: int
    payment_plan_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Purchase(TypedDict, total=False):
    id: str
    student_account_id: str
    item_id: str
    amount_cents: int
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WaiverProgram(TypedDict, total=False):
    id: str
    school_year_id: str
    name: str
    waiver_pct_bp: int
    stacking_priority: int
    max_waived_per_student_cents: int
    eligibility_grade_min: int
    eligibility_grade_max: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WaiverApplication(TypedDict, total=False):
    id: str
    student_account_id: str
    waiver_program_id: str
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    student_account_id: str
    amount_cents: int
    method: str
    idempotency_key: str
    overpayment_policy: str
    allocated_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable ledger row — id + created_at only, NO updated_at/version (PRD §2.5)
class PaymentAllocation(TypedDict, total=False):
    id: str
    payment_id: str
    fee_assessment_id: str
    allocated_cents: int
    allocation_rule: str
    created_at: str


class PaymentPlan(TypedDict, total=False):
    id: str
    student_account_id: str
    installment_count: int
    first_due_date: str
    interval_days: int
    covered_amount_cents: int
    installment_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentPlanInstallment(TypedDict, total=False):
    id: str
    payment_plan_id: str
    sequence: int
    due_date: str
    amount_cents: int
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict, total=False):
    id: str
    student_account_id: str
    fee_assessment_id: Optional[str]
    purchase_id: Optional[str]
    reason: str
    refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable ledger row — id + created_at only, NO updated_at/version (PRD §2.5)
class LedgerEntry(TypedDict, total=False):
    id: str
    student_account_id: str
    department_id: str
    entry_type: str
    amount_cents: int
    source_payment_id: Optional[str]
    reconciliation_run_id: Optional[str]
    created_at: str


class ReconciliationRun(TypedDict, total=False):
    id: str
    school_year_id: str
    run_at: str
    entries_reconciled: int
    drift_detected: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CollectionsCase(TypedDict, total=False):
    id: str
    student_account_id: str
    opened_at: str
    principal_cents: int
    aging_bucket: str
    written_off_cents: int
    approved_writeoff_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
