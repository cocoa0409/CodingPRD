"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CIRCLE_ADMIN = "CircleAdmin"
    FINANCE_OFFICER = "FinanceOfficer"
    MEMBER = "Member"
    GRANTEE_CONTACT = "GranteeContact"


class CyclePhase(str, Enum):
    DRAFT = "DRAFT"
    RECRUITMENT = "RECRUITMENT"
    POOLING = "POOLING"
    NOMINATION = "NOMINATION"
    VETTING = "VETTING"
    VOTING = "VOTING"
    AWARD = "AWARD"
    REPORTING = "REPORTING"
    CLOSED = "CLOSED"


class MembershipStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    RENEWAL_DUE = "RENEWAL_DUE"
    LAPSED = "LAPSED"
    WITHDRAWN = "WITHDRAWN"


class MembershipTier(str, Enum):
    STANDARD = "STANDARD"
    LEADER = "LEADER"


class ContributionStatus(str, Enum):
    PLEDGED = "PLEDGED"
    RECEIVED = "RECEIVED"
    REFUND_REQUESTED = "REFUND_REQUESTED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class NonprofitStanding(str, Enum):
    GOOD = "GOOD"
    SUSPENDED = "SUSPENDED"


class NominationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VETTING = "VETTING"
    NEEDS_INFO = "NEEDS_INFO"
    FINALIST = "FINALIST"
    AWARDED = "AWARDED"
    NOT_SELECTED = "NOT_SELECTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class VettingProfile(str, Enum):
    BALANCED = "BALANCED"
    EQUITY_FIRST = "EQUITY_FIRST"


class SiteVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class LearningSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BallotStatus(str, Enum):
    CAST = "CAST"


class PayoutStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class ReportingStatus(str, Enum):
    AWAITING_REPORTS = "AWAITING_REPORTS"
    REPORTS_COMPLETE = "REPORTS_COMPLETE"


class PayoutLifecycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    FAILED = "FAILED"


class ReportType(str, Enum):
    INTERIM = "INTERIM"
    FINAL = "FINAL"


class ReportStatus(str, Enum):
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RolloverMode(str, Enum):
    CARRY_FORWARD = "CARRY_FORWARD"
    RETURN_PRO_RATA = "RETURN_PRO_RATA"


class RolloverStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"


# --- Entity TypedDicts. Every resource carries the standard system-managed
# fields of PRD §2.5: id, created_at, updated_at, version. ---


class Circle(TypedDict, total=False):
    id: str
    name: str
    admin_fee_percent: int
    quorum_percent: int
    standard_minimum_cents: int
    leader_minimum_cents: int
    operating_reserve_cents: int
    vetting_profile: str
    active_member_count: int
    renewed_member_count: int
    created_at: str
    updated_at: str
    version: int


class GivingCycle(TypedDict, total=False):
    id: str
    circle_id: str
    year_label: str
    phase: str
    quorum_percent: int
    admin_fee_percent: int
    operating_reserve_cents: int
    voting_opens_at: Optional[str]
    voting_closes_at: Optional[str]
    active_member_snapshot: Optional[int]
    received_total_cents: int
    pledged_outstanding_cents: int
    refunded_total_cents: int
    released_total_cents: int
    admin_fee_transferred_cents: int
    rollover_in_cents: int
    rollover_out_cents: int
    pooled_balance_cents: int
    grant_budget_provisional_cents: int
    grant_budget_final_cents: int
    budget_locked: bool
    ballots_cast_count: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict, total=False):
    id: str
    circle_id: str
    member_id: str
    tier: str
    status: str
    renewal_count: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict, total=False):
    id: str
    cycle_id: str
    membership_id: str
    amount_cents: int
    status: str
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Nonprofit(TypedDict, total=False):
    id: str
    ein: str
    legal_name: str
    mission_category: str
    standing: str
    created_at: str
    updated_at: str
    version: int


class Nomination(TypedDict, total=False):
    id: str
    cycle_id: str
    nonprofit_id: str
    nominated_by_membership_id: str
    statement: str
    status: str
    financial_health: Optional[int]
    mission_alignment: Optional[int]
    org_capacity: Optional[int]
    vetting_score: Optional[int]
    info_rounds_used: int
    created_at: str
    updated_at: str
    version: int


class SiteVisit(TypedDict, total=False):
    id: str
    nomination_id: str
    starts_at: str
    ends_at: str
    status: str
    findings_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LearningSession(TypedDict, total=False):
    id: str
    cycle_id: str
    title: str
    starts_at: str
    ends_at: str
    capacity: int
    seats_taken: int
    rsvp_membership_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BallotAllocation(TypedDict):
    nomination_id: str
    points: int


class Ballot(TypedDict, total=False):
    id: str
    cycle_id: str
    membership_id: str
    allocations: List[BallotAllocation]
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantAward(TypedDict, total=False):
    id: str
    cycle_id: str
    nomination_id: str
    nonprofit_id: str
    amount_cents: int
    winner_points: int
    payout_status: str
    reporting_status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict, total=False):
    id: str
    award_id: str
    tranche: int
    amount_cents: int
    status: str
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GranteeReport(TypedDict, total=False):
    id: str
    award_id: str
    report_type: str
    due_at: str
    status: str
    narrative: Optional[str]
    expenditure_cents: Optional[int]
    submitted_at: Optional[str]
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RolloverDecision(TypedDict, total=False):
    id: str
    source_cycle_id: str
    target_cycle_id: Optional[str]
    mode: str
    amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
