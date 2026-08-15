"""Domain types: entity TypedDicts, status enums, role enum (PRD 2.1, 2.5, 3.x)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROPERTY_MANAGER = "PropertyManager"
    LEASING_AGENT = "LeasingAgent"
    TENANT = "Tenant"
    SYSTEM_OPS = "SystemOps"


class PostingPriorityPolicy(str, Enum):
    FEES_FIRST = "FEES_FIRST"
    RENT_FIRST = "RENT_FIRST"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class LeaseAction(str, Enum):
    ACTIVATE = "ACTIVATE"
    MOVE_OUT = "MOVE_OUT"


class LateFeeType(str, Enum):
    FLAT = "FLAT"
    PERCENT_PLUS_DAILY = "PERCENT_PLUS_DAILY"


class ChargeKind(str, Enum):
    RENT = "RENT"
    LATE_FEE = "LATE_FEE"
    NSF_FEE = "NSF_FEE"
    PLAN_SETUP_FEE = "PLAN_SETUP_FEE"
    DAMAGE_FEE = "DAMAGE_FEE"


class ChargeSource(str, Enum):
    MANUAL = "MANUAL"
    SWEEP = "SWEEP"
    PLAN = "PLAN"
    RETURN = "RETURN"


class ChargeStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    WAIVED = "WAIVED"
    VOID = "VOID"


class PaymentChannel(str, Enum):
    ACH = "ACH"
    CARD = "CARD"
    CHECK = "CHECK"
    MONEY_ORDER = "MONEY_ORDER"
    CASH = "CASH"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    RETURNED = "RETURNED"


class PaymentAction(str, Enum):
    POST = "POST"
    RETURN = "RETURN"


class AllocationDirection(str, Enum):
    APPLY = "APPLY"
    REVERSE = "REVERSE"


class NoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SERVED = "SERVED"
    CURED = "CURED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class NoticeAction(str, Enum):
    ISSUE = "ISSUE"
    SERVE = "SERVE"


class ServiceMethod(str, Enum):
    PERSONAL = "PERSONAL"
    POSTED_AND_MAILED = "POSTED_AND_MAILED"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"


class CancelReason(str, Enum):
    SUPERSEDED = "SUPERSEDED"
    MOVE_OUT = "MOVE_OUT"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CURED = "CURED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class PlanAction(str, Enum):
    APPROVE = "APPROVE"


class InstallmentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    MISSED = "MISSED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_ADJUSTED = "RESOLVED_ADJUSTED"
    REOPENED = "REOPENED"


class DisputeAction(str, Enum):
    RESOLVE = "RESOLVE"
    REOPEN = "REOPEN"


class DisputeOutcome(str, Enum):
    UPHELD = "UPHELD"
    ADJUSTED = "ADJUSTED"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    REFERRED = "REFERRED"
    SETTLED = "SETTLED"
    RECALLED = "RECALLED"


class ReferralAction(str, Enum):
    REFER = "REFER"
    SETTLE = "SETTLE"
    RECALL = "RECALL"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# Every primary resource carries id / created_at / updated_at / version
# (PRD 2.5); the payment allocation is the sole append-only exception and
# exposes only id / created_at.
# ---------------------------------------------------------------------------


class Property(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    posting_priority_policy: str
    late_fee_cap_cents: int
    nsf_fee_cap_cents: int
    monthly_waiver_cap_cents: int
    min_partial_payment_percent: int
    collections_threshold_cents: int
    notice_cure_period_days: int
    plan_cooling_off_days: int
    plan_setup_fee_cents: int
    plan_setup_fee_threshold_cents: int
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    property_id: str
    primary_tenant_id: str
    unit_label: str
    monthly_rent_cents: int
    due_day: int
    grace_period_days: int
    late_fee_type: str
    late_fee_flat_cents: int
    late_fee_percent_bps: int
    late_fee_daily_cents: int
    term_start_date: str
    term_end_date: str
    status: str
    move_out_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerCharge(TypedDict, total=False):
    id: str
    lease_id: str
    kind: str
    source: str
    period_start_date: str
    period_end_date: str
    due_date: str
    amount_cents: int
    waived_cents: int
    outstanding_cents: int
    status: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    lease_id: str
    tenant_id: str
    channel: str
    amount_cents: int
    received_date: str
    status: str
    posted_date: Optional[str]
    return_reason_code: Optional[str]
    nsf_fee_cents: Optional[int]
    return_count: int
    created_at: str
    updated_at: str
    version: int


class PaymentAllocation(TypedDict, total=False):
    """Append-only ledger entry: id and created_at only, no updated_at/version."""
    id: str
    payment_id: str
    charge_id: str
    direction: str
    amount_cents: int
    allocation_order: int
    note: str
    created_at: str


class DelinquencyNotice(TypedDict, total=False):
    id: str
    lease_id: str
    charge_ids: List[str]
    period_start_date: str
    period_end_date: str
    amount_demanded_cents: int
    status: str
    issued_date: Optional[str]
    cure_deadline_date: Optional[str]
    service_method: Optional[str]
    served_date: Optional[str]
    served_by_user_id: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict, total=False):
    sequence_number: int
    due_date: str
    amount_cents: int
    status: str


class PaymentPlan(TypedDict, total=False):
    id: str
    lease_id: str
    charge_ids: List[str]
    drafted_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    setup_fee_cents: int
    scheduled_total_cents: int
    installment_count: int
    first_installment_date: str
    installments: List[Installment]
    missed_installment_count: int
    defaulted_date: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    lease_id: str
    charge_id: str
    tenant_id: str
    reason: str
    status: str
    reopen_count: int
    adjusted_amount_cents: Optional[int]
    resolution_notes: str
    created_at: str
    updated_at: str
    version: int


class CollectionsReferral(TypedDict, total=False):
    id: str
    lease_id: str
    referred_balance_cents: int
    status: str
    agency_name: Optional[str]
    referred_date: Optional[str]
    recall_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerRead(TypedDict, total=False):
    forward_balance_cents: int
    chronological_balance_cents: int
    total_charged_cents: int
    total_waived_cents: int
    total_applied_net_cents: int
    total_outstanding_cents: int
    open_charge_count: int


class SweepReport(TypedDict, total=False):
    late_fees_assessed_count: int
    installments_marked_missed_count: int
    plans_defaulted_count: int
    plans_cured_count: int
    notices_cured_count: int
    notices_expired_count: int
