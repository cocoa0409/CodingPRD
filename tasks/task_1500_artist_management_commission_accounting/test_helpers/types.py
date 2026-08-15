"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Entities with the standard four
system-managed fields carry id + created_at + updated_at + version;
StatementLine is the sole append-only exception and carries only id +
created_at (PRD section on common resource properties).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class ArtistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_HIATUS = "ON_HIATUS"
    ARCHIVED = "ARCHIVED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"
    SUNSET = "SUNSET"
    CLOSED = "CLOSED"


class IncomeType(str, Enum):
    TOURING = "TOURING"
    RECORDING = "RECORDING"
    PUBLISHING = "PUBLISHING"
    ENDORSEMENT = "ENDORSEMENT"


class IncomeEventStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    SETTLED = "SETTLED"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class IncomeEventKind(str, Enum):
    ORIGINAL = "ORIGINAL"
    ADJUSTMENT = "ADJUSTMENT"


class TermRelation(str, Enum):
    IN_TERM = "IN_TERM"
    SUNSET = "SUNSET"
    POST_TERM_EXEMPT = "POST_TERM_EXEMPT"


class AdvanceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECOUPED = "RECOUPED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ExpenseStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REIMBURSED = "REIMBURSED"


class ExpenseCategory(str, Enum):
    TRAVEL = "TRAVEL"
    PRODUCTION = "PRODUCTION"
    MARKETING = "MARKETING"
    LEGAL = "LEGAL"
    OTHER = "OTHER"


class ApprovalRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ApprovalTargetType(str, Enum):
    EXPENSE = "EXPENSE"
    OPPORTUNITY = "OPPORTUNITY"


class RequiredApprover(str, Enum):
    BUSINESS_MANAGER = "BUSINESS_MANAGER"
    ARTIST = "ARTIST"
    FIRM_ADMIN = "FIRM_ADMIN"


class OpportunityStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_EVALUATION = "UNDER_EVALUATION"
    NEGOTIATING = "NEGOTIATING"
    ACCEPTED = "ACCEPTED"
    CONVERTED = "CONVERTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class Recommendation(str, Enum):
    PURSUE = "PURSUE"
    CONSIDER = "CONSIDER"
    PASS_SUGGESTED = "PASS_SUGGESTED"


class EngagementStatus(str, Enum):
    HOLD = "HOLD"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    RELEASED = "RELEASED"


class OptionStatus(str, Enum):
    OPEN = "OPEN"
    EXERCISED = "EXERCISED"
    LAPSED = "LAPSED"
    WAIVED = "WAIVED"


class OptionType(str, Enum):
    RECORDING_CYCLE = "RECORDING_CYCLE"
    ENDORSEMENT_RENEWAL = "ENDORSEMENT_RENEWAL"
    TOUR_LEG = "TOUR_LEG"
    MERCHANDISE = "MERCHANDISE"


class MemberRole(str, Enum):
    AGENT = "AGENT"
    BUSINESS_MANAGER = "BUSINESS_MANAGER"
    PUBLICIST = "PUBLICIST"


class TeamMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FINALIZED = "FINALIZED"
    DISCARDED = "DISCARDED"


class StatementBasis(str, Enum):
    ACCRUAL = "ACCRUAL"
    CASH = "CASH"


class StatementLineType(str, Enum):
    INCOME = "INCOME"
    EXPENSE_REIMBURSEMENT = "EXPENSE_REIMBURSEMENT"
    ADVANCE_RECOUPMENT = "ADVANCE_RECOUPMENT"
    ADJUSTMENT = "ADJUSTMENT"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"
    WITHDRAWN = "WITHDRAWN"
    ESCALATED = "ESCALATED"


class DisputeReason(str, Enum):
    COMMISSION_RATE = "COMMISSION_RATE"
    INCOME_MISSING = "INCOME_MISSING"
    EXPENSE_UNAUTHORIZED = "EXPENSE_UNAUTHORIZED"
    RECOUPMENT_ERROR = "RECOUPMENT_ERROR"
    SUNSET_MISCLASSIFIED = "SUNSET_MISCLASSIFIED"
    OTHER = "OTHER"


class AuditStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED = "CLOSED"


class CostBearer(str, Enum):
    FIRM = "FIRM"
    ARTIST = "ARTIST"


class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    AGENT = "Agent"
    BUSINESS_MANAGER = "BusinessManager"
    PUBLICIST = "Publicist"
    ARTIST = "Artist"
    AUDITOR = "Auditor"


class Artist(TypedDict, total=False):
    id: str
    stage_name: str
    legal_name: str
    primary_genre: str
    home_currency: str
    status: str
    current_agreement_id: Optional[str]
    unrecouped_advance_balance_cents: int
    lifetime_gross_cents: int
    lifetime_commission_cents: int
    lifetime_disbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class Agreement(TypedDict, total=False):
    id: str
    artist_id: str
    prior_agreement_id: Optional[str]
    term_start_date: str
    term_end_date: str
    termination_date: Optional[str]
    touring_commission_base: str
    recoupment_policy: str
    status: str
    sunset_start_date: Optional[str]
    sunset_end_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommissionRateSchedule(TypedDict, total=False):
    id: str
    agreement_id: str
    income_type: str
    in_term_rate_bps: int
    sunset_rate_bps: int
    sunset_months: int
    effective_from_date: str
    effective_to_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncomeEvent(TypedDict, total=False):
    id: str
    artist_id: str
    agreement_id: str
    linked_engagement_id: Optional[str]
    parent_event_id: Optional[str]
    kind: str
    income_type: str
    source_name: str
    gross_amount_cents: int
    recognition_date: str
    received_date: Optional[str]
    received_amount_cents: Optional[int]
    status: str
    term_relation: Optional[str]
    applied_schedule_id: Optional[str]
    applied_rate_bps: Optional[int]
    commission_amount_cents: Optional[int]
    artist_net_cents: Optional[int]
    recouped_amount_cents: int
    artist_payable_cents: Optional[int]
    statement_id: Optional[str]
    recoup_statement_id: Optional[str]
    reported_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Advance(TypedDict, total=False):
    id: str
    artist_id: str
    principal_cents: int
    issued_date: str
    recoup_pct_bps: int
    applies_to_income_types: List[str]
    recouped_cents: int
    written_off_cents: int
    outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Expense(TypedDict, total=False):
    id: str
    artist_id: str
    engagement_id: Optional[str]
    category: str
    amount_cents: int
    incurred_date: str
    description: str
    status: str
    submitted_by_user_id: str
    rejection_note: Optional[str]
    reimbursed_statement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApprovalRequest(TypedDict, total=False):
    id: str
    artist_id: str
    target_type: str
    target_id: str
    required_approver: str
    status: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Opportunity(TypedDict, total=False):
    id: str
    artist_id: str
    income_type: str
    counterparty_name: str
    proposed_value_cents: int
    current_value_cents: int
    offer_expiry_date: str
    proposed_window_start: str
    proposed_window_end: str
    fit_score: int
    evaluation_score: Optional[int]
    recommendation: Optional[str]
    requires_artist_approval: bool
    round_number: int
    status: str
    converted_engagement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict, total=False):
    id: str
    artist_id: str
    opportunity_id: Optional[str]
    income_type: str
    counterparty_name: str
    start_datetime: str
    end_datetime: str
    travel_buffer_hours: int
    guarantee_cents: int
    status: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Option(TypedDict, total=False):
    id: str
    artist_id: str
    agreement_id: str
    source_opportunity_id: Optional[str]
    option_type: str
    income_type: str
    exercise_window_start: str
    exercise_window_end: str
    engagement_start_datetime: str
    engagement_end_datetime: str
    exercise_value_cents: int
    status: str
    exercised_engagement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TeamMember(TypedDict, total=False):
    id: str
    artist_id: str
    member_role: str
    display_name: str
    authority_expense_cap_cents: int
    window_start_date: str
    window_end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Statement(TypedDict, total=False):
    id: str
    artist_id: str
    prior_statement_id: Optional[str]
    period_start_date: str
    period_end_date: str
    basis: str
    revision_number: int
    status: str
    issued_at: Optional[str]
    dispute_window_ends_at: Optional[str]
    rate_snapshot: list
    gross_total_cents: int
    commission_total_cents: int
    income_net_total_cents: int
    expense_total_cents: int
    recoup_total_cents: int
    adjustment_total_cents: int
    carry_in_cents: int
    net_payable_cents: int
    disbursed_cents: int
    carry_out_cents: int
    created_at: str
    updated_at: str
    version: int


class StatementLine(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    statement_id: str
    line_type: str
    ref_id: str
    amount_cents: int
    commission_cents: int
    note: str
    created_at: str


class Dispute(TypedDict, total=False):
    id: str
    artist_id: str
    statement_id: str
    reason: str
    claimed_amount_cents: int
    status: str
    awarded_amount_cents: Optional[int]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict, total=False):
    id: str
    artist_id: str
    scope_statement_id: str
    source_dispute_id: Optional[str]
    status: str
    findings_underpayment_cents: Optional[int]
    audit_cost_cents: Optional[int]
    cost_bearer: Optional[str]
    underpayment_applied: bool
    cost_applied: bool
    reopen_count: int
    created_at: str
    updated_at: str
    version: int
