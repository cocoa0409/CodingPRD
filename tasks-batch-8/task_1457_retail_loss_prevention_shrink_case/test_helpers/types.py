"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    LP_ANALYST = "LPAnalyst"
    LP_MANAGER = "LPManager"
    HR_PARTNER = "HRPartner"
    LP_ADMIN = "LPAdmin"
    AUDITOR = "Auditor"
    POS_FEED = "PosFeed"


class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ExceptionType(str, Enum):
    REFUND_NO_RECEIPT = "REFUND_NO_RECEIPT"
    HIGH_VALUE_VOID = "HIGH_VALUE_VOID"
    PRICE_OVERRIDE = "PRICE_OVERRIDE"
    NO_SALE_DRAWER = "NO_SALE_DRAWER"
    SUSPEND_CANCEL = "SUSPEND_CANCEL"
    SWEETHEART_SCAN = "SWEETHEART_SCAN"
    SELF_CHECKOUT_MISMATCH = "SELF_CHECKOUT_MISMATCH"


class EventStatus(str, Enum):
    UNAGGREGATED = "UNAGGREGATED"
    AGGREGATED = "AGGREGATED"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    CONVERTED = "CONVERTED"
    DISMISSED = "DISMISSED"


class SubjectType(str, Enum):
    EMPLOYEE = "EMPLOYEE"
    EXTERNAL = "EXTERNAL"
    UNKNOWN = "UNKNOWN"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    READY_FOR_INTERVIEW = "READY_FOR_INTERVIEW"
    INTERVIEWED = "INTERVIEWED"
    ADJUDICATING = "ADJUDICATING"
    CLOSED_SUBSTANTIATED = "CLOSED_SUBSTANTIATED"
    CLOSED_UNSUBSTANTIATED = "CLOSED_UNSUBSTANTIATED"
    CLOSED_REFERRED = "CLOSED_REFERRED"
    MERGED = "MERGED"


class CaseSource(str, Enum):
    ALERT = "ALERT"
    MANUAL = "MANUAL"
    SHRINK_VARIANCE = "SHRINK_VARIANCE"


class CasePriority(str, Enum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"


class RestitutionStatus(str, Enum):
    NONE = "NONE"
    OUTSTANDING = "OUTSTANDING"
    SETTLED = "SETTLED"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    DOCUMENTED = "DOCUMENTED"


class InterviewOutcome(str, Enum):
    ADMITTED = "ADMITTED"
    DENIED = "DENIED"
    PARTIAL = "PARTIAL"
    NO_SHOW = "NO_SHOW"


class EvidenceType(str, Enum):
    VIDEO_CLIP = "VIDEO_CLIP"
    TRANSACTION_LOG = "TRANSACTION_LOG"
    PHOTO = "PHOTO"
    WRITTEN_STATEMENT = "WRITTEN_STATEMENT"
    AUDIO = "AUDIO"


class RetentionClass(str, Enum):
    STANDARD = "STANDARD"
    EXTENDED = "EXTENDED"
    CASE_HOLD = "CASE_HOLD"


class EvidenceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SEALED = "SEALED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    PURGED = "PURGED"


class CustodyAction(str, Enum):
    COLLECTED = "COLLECTED"
    SEALED = "SEALED"
    ACCESSED = "ACCESSED"
    TRANSFERRED = "TRANSFERRED"
    RELEASED_TO_LE = "RELEASED_TO_LE"
    RETURNED_FROM_LE = "RETURNED_FROM_LE"


class DemandBasis(str, Enum):
    STATUTORY = "STATUTORY"
    ACTUAL_LOSS = "ACTUAL_LOSS"


class DemandStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    WRITTEN_OFF = "WRITTEN_OFF"
    CANCELLED = "CANCELLED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    MONEY_ORDER = "MONEY_ORDER"
    PAYROLL_DEDUCT = "PAYROLL_DEDUCT"


class PaymentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    POSTED = "POSTED"
    RETURNED = "RETURNED"


class OrcGroupStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    ACTIVE_MONITORING = "ACTIVE_MONITORING"
    DISRUPTED = "DISRUPTED"
    DISMISSED = "DISMISSED"


class CaseLinkStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class ShrinkPeriodStatus(str, Enum):
    OPEN = "OPEN"
    COUNTED = "COUNTED"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"


class PacketStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RETURNED = "RETURNED"


class Store(TypedDict, total=False):
    id: str
    store_number: str
    name: str
    region_code: str
    status: str
    total_adjudicated_loss_cents: int
    restitution_collected_cents: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    store_id: str
    employee_ref: str
    full_name: str
    status: str
    prior_substantiated_count: int
    created_at: str
    updated_at: str
    version: int


class PosExceptionEvent(TypedDict, total=False):
    id: str
    store_id: str
    register_ref: str
    employee_id: Optional[str]
    txn_ref: str
    exception_type: str
    amount_cents: int
    occurred_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Alert(TypedDict, total=False):
    id: str
    store_id: str
    employee_id: Optional[str]
    subject_type: str
    score: float
    event_count: int
    total_amount_cents: int
    window_start: str
    window_end: str
    status: str
    case_id: Optional[str]
    dismiss_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    case_number: str
    store_id: str
    source: str
    subject_type: str
    employee_id: Optional[str]
    status: str
    created_by: str
    assigned_analyst_id: Optional[str]
    manual_loss_cents: int
    recovered_value_cents: int
    total_loss_cents: int
    priority: str
    restitution_status: str
    loss_posted_period_id: Optional[str]
    loss_posted_cents: int
    adjudicated_at: Optional[str]
    adjudicated_by: Optional[str]
    closed_at: Optional[str]
    merged_into_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Interview(TypedDict, total=False):
    id: str
    case_id: str
    interviewer_id: str
    subject_employee_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    status: str
    outcome: Optional[str]
    conducted_at: Optional[str]
    notes: Optional[str]
    documented_at: Optional[str]
    doc_stale: bool
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    id: str
    case_id: str
    evidence_type: str
    captured_at: str
    retention_class: str
    retention_until: Optional[str]
    status: str
    sealed_by: Optional[str]
    legal_hold: bool
    created_at: str
    updated_at: str
    version: int


class CustodyEvent(TypedDict, total=False):
    # Append-only chain entry: carries ONLY id + created_at from the common
    # quartet; updated_at and version are absent by contract (PRD §2.4).
    id: str
    evidence_id: str
    action: str
    actor_id: str
    note: Optional[str]
    created_at: str


class CivilDemand(TypedDict, total=False):
    id: str
    case_id: str
    basis: str
    priors_offense_count: int
    recovery_cost_cents: int
    merchandise_loss_cents: int
    statutory_penalty_cents: int
    amount_due_cents: int
    fees_incurred_cents: int
    paid_to_date_cents: int
    outstanding_cents: int
    status: str
    created_by: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RestitutionPayment(TypedDict, total=False):
    id: str
    demand_id: str
    amount_cents: int
    method: str
    status: str
    applied_fees_cents: int
    applied_penalty_cents: int
    applied_merch_cents: int
    created_at: str
    updated_at: str
    version: int


class OrcGroup(TypedDict, total=False):
    id: str
    name: str
    description: Optional[str]
    status: str
    confirmed_case_count: int
    distinct_store_count: int
    exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class CaseLink(TypedDict, total=False):
    id: str
    case_id: str
    orc_group_id: str
    link_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShrinkPeriod(TypedDict, total=False):
    id: str
    store_id: str
    period_start: str
    period_end: str
    book_inventory_cents: int
    period_sales_cents: int
    counted_inventory_cents: Optional[int]
    counted_at: Optional[str]
    known_loss_posted_cents: int
    accrual_case_basis_cents: int
    accrual_sales_basis_cents: int
    variance_cents: Optional[int]
    variance_pct: Optional[float]
    status: str
    auto_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReferralPacket(TypedDict, total=False):
    id: str
    case_id: str
    jurisdiction_code: str
    status: str
    packet_exposure_cents: int
    submitted_at: Optional[str]
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
