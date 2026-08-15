"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity narratives (section 3) and the common resource
properties of section 2.4 — every resource in this API carries id, created_at,
updated_at, and version (no entity is exempt).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BOARD_OFFICER = "BoardOfficer"
    BOARD_MEMBER = "BoardMember"
    MANAGING_AGENT = "ManagingAgent"
    SHAREHOLDER = "Shareholder"


class FlipTaxPolicy(str, Enum):
    GROSS_PERCENT = "GROSS_PERCENT"
    PER_SHARE = "PER_SHARE"


class AllocationMethod(str, Enum):
    PRO_RATA_SHARES = "PRO_RATA_SHARES"
    EQUAL_SPLIT = "EQUAL_SPLIT"


class OccupancyStatus(str, Enum):
    OWNER_OCCUPIED = "OWNER_OCCUPIED"
    SUBLET = "SUBLET"
    VACANT = "VACANT"


class Standing(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    DELINQUENT = "DELINQUENT"
    TERMINATED = "TERMINATED"


class LedgerEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ChargeStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"
    WAIVED = "WAIVED"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class ArrearsActionType(str, Enum):
    LATE_NOTICE = "LATE_NOTICE"
    DEMAND_LETTER = "DEMAND_LETTER"
    TERMINATION_NOTICE = "TERMINATION_NOTICE"


class ArrearsActionStatus(str, Enum):
    ISSUED = "ISSUED"
    CURED = "CURED"
    ESCALATED = "ESCALATED"
    WITHDRAWN = "WITHDRAWN"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    TRANSFERRED = "TRANSFERRED"


class InterviewOutcome(str, Enum):
    PENDING = "PENDING"
    FAVORABLE = "FAVORABLE"
    UNFAVORABLE = "UNFAVORABLE"
    WAIVED = "WAIVED"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class ResolutionKind(str, Enum):
    APPROVE_PURCHASE = "APPROVE_PURCHASE"
    REJECT_PURCHASE = "REJECT_PURCHASE"
    APPROVE_SCHEDULE = "APPROVE_SCHEDULE"
    APPROVE_REFINANCE = "APPROVE_REFINANCE"
    APPROVE_SUBLET = "APPROVE_SUBLET"
    APPROVE_ALTERATION = "APPROVE_ALTERATION"
    ISSUE_ARREARS_ACTION = "ISSUE_ARREARS_ACTION"
    SET_POLICY = "SET_POLICY"


class SubjectEntityKind(str, Enum):
    PURCHASE_APPLICATION = "PurchaseApplication"
    CHARGE_SCHEDULE = "ChargeSchedule"
    SUBLET_AGREEMENT = "SubletAgreement"
    ALTERATION_AGREEMENT = "AlterationAgreement"
    SHAREHOLDER = "Shareholder"
    COOPERATIVE = "Cooperative"


class ResolutionStatus(str, Enum):
    OPEN = "OPEN"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WITHDRAWN = "WITHDRAWN"


class VoteChoice(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    ABSTAIN = "ABSTAIN"


class SubletStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    TERMINATED_EARLY = "TERMINATED_EARLY"


class AlterationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    ABANDONED = "ABANDONED"


class MeetingKind(str, Enum):
    ANNUAL = "ANNUAL"
    SPECIAL = "SPECIAL"


class PreparationState(str, Enum):
    PREPARING = "PREPARING"
    NOTICE_SENT = "NOTICE_SENT"
    ADJOURNED = "ADJOURNED"


class QuorumState(str, Enum):
    QUORUM_PENDING = "QUORUM_PENDING"
    QUORUM_MET = "QUORUM_MET"
    QUORUM_FAILED = "QUORUM_FAILED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    ADJOURNED_NO_QUORUM = "ADJOURNED_NO_QUORUM"
    COMPLETED = "COMPLETED"


class BallotKind(str, Enum):
    IN_PERSON = "IN_PERSON"
    PROXY = "PROXY"


class BallotStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COUNTED = "COUNTED"
    INVALIDATED = "INVALIDATED"


class Cooperative(TypedDict, total=False):
    id: str
    name: str
    address: str
    total_shares: int
    underlying_mortgage_principal_cents: int
    underlying_mortgage_rate_bps: int
    flip_tax_policy: str
    flip_tax_percent_bps: int
    flip_tax_per_share_cents: int
    sublet_policy_years_max: int
    sublet_policy_gap_years: int
    arrears_late_fee_flat_cents: int
    arrears_interest_rate_bps: int
    arrears_grace_days: int
    arrears_termination_threshold_cents: int
    annual_meeting_quorum_percent_bps: int
    current_utc: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict, total=False):
    id: str
    cooperative_id: str
    unit_label: str
    shares_allocated: int
    occupancy_status: str
    last_sublet_end_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shareholder(TypedDict, total=False):
    id: str
    cooperative_id: str
    full_name: str
    email: str
    standing: str
    arrears_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ShareLedgerEntry(TypedDict, total=False):
    id: str
    cooperative_id: str
    unit_id: str
    shareholder_id: str
    shares_held: int
    entry_status: str
    effective_at: str
    created_at: str
    updated_at: str
    version: int


class ChargeSchedule(TypedDict, total=False):
    id: str
    cooperative_id: str
    fiscal_year: int
    annual_operating_budget_cents: int
    allocation_method: str
    schedule_status: str
    effective_from: str
    effective_to: str
    approving_resolution_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceCharge(TypedDict, total=False):
    id: str
    cooperative_id: str
    unit_id: str
    schedule_id: str
    billing_month: str
    due_date: Optional[str]
    base_amount_cents: int
    late_fee_cents: int
    interest_cents: int
    paid_cents: int
    outstanding_cents: int
    charge_status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    cooperative_id: str
    shareholder_id: str
    charge_id: str
    amount_cents: int
    posted_at: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class ArrearsAction(TypedDict, total=False):
    id: str
    cooperative_id: str
    shareholder_id: str
    action_type: str
    action_status: str
    issued_at: str
    cure_deadline: str
    cure_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class PurchaseApplication(TypedDict, total=False):
    id: str
    cooperative_id: str
    unit_id: str
    seller_shareholder_id: str
    buyer_full_name: str
    buyer_email: str
    gross_sale_price_cents: int
    financing_percent_bps: int
    application_status: str
    flip_tax_cents: Optional[int]
    debt_to_income_bps: int
    post_closing_liquidity_cents: int
    submitted_at: Optional[str]
    deciding_resolution_id: Optional[str]
    transferred_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Interview(TypedDict, total=False):
    id: str
    cooperative_id: str
    application_id: str
    scheduled_at: str
    panel_member_user_ids: List[str]
    interview_outcome: str
    interview_status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Resolution(TypedDict, total=False):
    id: str
    cooperative_id: str
    resolution_kind: str
    subject_entity_kind: str
    subject_entity_id: str
    payload_json: dict
    votes_required: int
    votes_for: int
    votes_against: int
    votes_abstain: int
    resolution_status: str
    supersedes_resolution_id: Optional[str]
    opened_at: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResolutionVote(TypedDict, total=False):
    id: str
    cooperative_id: str
    resolution_id: str
    voter_user_id: str
    vote_choice: str
    cast_at: str
    created_at: str
    updated_at: str
    version: int


class SubletAgreement(TypedDict, total=False):
    id: str
    cooperative_id: str
    unit_id: str
    shareholder_id: str
    subtenant_name: str
    sublet_start_date: str
    sublet_end_date: str
    monthly_sublet_fee_cents: Optional[int]
    sublet_status: str
    created_at: str
    updated_at: str
    version: int


class AlterationAgreement(TypedDict, total=False):
    id: str
    cooperative_id: str
    unit_id: str
    shareholder_id: str
    scope_description: str
    contractor_name: str
    contractor_insurance_cents: int
    work_window_start: str
    work_window_end: str
    security_deposit_cents: Optional[int]
    contractor_bid_cents: int
    involves_wet_over_dry: bool
    alteration_status: str
    created_at: str
    updated_at: str
    version: int


class Meeting(TypedDict, total=False):
    id: str
    cooperative_id: str
    meeting_kind: str
    scheduled_at: str
    preparation_state: str
    quorum_state: str
    shares_represented: int
    meeting_status: str
    created_at: str
    updated_at: str
    version: int


class Ballot(TypedDict, total=False):
    id: str
    cooperative_id: str
    meeting_id: str
    shareholder_id: str
    ballot_kind: str
    shares_voted: int
    candidate_user_ids: List[str]
    ballot_status: str
    created_at: str
    updated_at: str
    version: int
