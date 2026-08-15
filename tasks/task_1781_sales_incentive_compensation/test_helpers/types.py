"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD resource descriptions. PayrollExport is the single
append-only exception to the common-fields convention: it carries only `id`
and `created_at` (no `updated_at`, no `version`).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    COMP_ADMIN = "CompAdmin"
    COMP_ANALYST = "CompAnalyst"
    COMP_MANAGER = "CompManager"
    REP = "Rep"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class AttainmentMode(str, Enum):
    DIRECT_ONLY = "DIRECT_ONLY"
    INCLUDE_ROLLUP = "INCLUDE_ROLLUP"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class AcceptanceStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class TransactionStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"


class CreditType(str, Enum):
    DIRECT = "DIRECT"
    ROLLUP = "ROLLUP"


class CreditStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    LOCKED = "LOCKED"
    REVERSED = "REVERSED"


class AdjustmentSource(str, Enum):
    MANUAL = "MANUAL"
    DISPUTE = "DISPUTE"
    CLAWBACK = "CLAWBACK"


class AdjustmentStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DisputeReason(str, Enum):
    CREDIT_MISSING = "CREDIT_MISSING"
    CREDIT_AMOUNT = "CREDIT_AMOUNT"
    QUOTA_ERROR = "QUOTA_ERROR"
    CURVE_MISAPPLIED = "CURVE_MISAPPLIED"
    DRAW_ERROR = "DRAW_ERROR"
    OTHER = "OTHER"


class DisputeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    EXPORTED = "EXPORTED"


class CurveTier(TypedDict):
    attainment_floor_bps: int
    rate_bps: int


class Split(TypedDict):
    rep_id: str
    split_bps: int


class CompProgram(TypedDict):
    id: str
    name: str
    current_period_index: int
    accrued_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class CompPlan(TypedDict):
    id: str
    program_id: str
    name: str
    effective_start_date: str
    effective_end_date: str
    curve_tiers: List[CurveTier]
    attainment_mode: str
    rollup_rate_bps: int
    payout_cap_cents: Optional[int]
    document_version: int
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Rep(TypedDict):
    id: str
    program_id: str
    name: str
    employee_ref: str
    manager_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanAssignment(TypedDict):
    id: str
    program_id: str
    rep_id: str
    plan_id: str
    quota_cents: int
    draw_amount_cents_per_period: int
    draw_recoverable: bool
    guarantee_amount_cents_per_period: int
    effective_start_date: str
    effective_end_date: Optional[str]
    status: str
    acceptance_status: str
    accepted_document_version: Optional[int]
    draw_outstanding_cents: int
    draw_forgiven_cents: int
    current_period_earned_cents: int
    current_attainment_bps: int
    provisional_period_payout_cents: int
    lifetime_earned_cents: int
    lifetime_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class SalesTransaction(TypedDict):
    id: str
    program_id: str
    external_ref: str
    amount_cents: int
    transaction_date: str
    splits: List[Split]
    booked_period_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditEntry(TypedDict):
    id: str
    transaction_id: str
    assignment_id: str
    rep_id: str
    parent_credit_id: Optional[str]
    credit_type: str
    credit_amount_cents: int
    posted_period_index: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Adjustment(TypedDict):
    id: str
    assignment_id: str
    dispute_id: Optional[str]
    amount_cents: int
    source: str
    reason: str
    period_index: int
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    assignment_id: str
    credit_entry_id: Optional[str]
    period_index: int
    reason: str
    requested_amount_cents: int
    approved_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PayoutStatement(TypedDict):
    id: str
    assignment_id: str
    period_index: int
    earned_credits_cents: int
    adjustments_cents: int
    earned_total_cents: int
    attainment_bps: int
    gross_payout_cents: int
    payout_cap_applied: bool
    draw_paid_cents: int
    draw_recovered_cents: int
    guarantee_trueup_cents: int
    deficit_cents: int
    net_payable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayrollExport(TypedDict):
    # Append-only record: carries ONLY id + created_at (no updated_at, no version).
    id: str
    created_at: str
    program_id: str
    period_index: int
    statement_ids: List[str]
    statement_count: int
    total_cents: int


class PlanEffectiveness(TypedDict):
    plan_id: str
    assignments_count: int
    statements_count: int
    avg_attainment_bps: int
    total_earned_cents: int
    total_payout_cents: int
    distribution: dict
