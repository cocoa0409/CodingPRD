"""Domain types for the Conference Revenue Distribution & Membership Change API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.  Three resource types are deliberately lighter: a distribution line,
a postseason unit and a ballot carry only ``id`` and ``created_at`` (PRD §2.5),
so their TypedDicts omit ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    COMMISSIONER = "Commissioner"
    FINANCE_OFFICER = "FinanceOfficer"
    TREASURER = "Treasurer"
    AUDITOR = "Auditor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SCHEDULE_COORDINATOR = "ScheduleCoordinator"
    PLATFORM_ADMIN = "PlatformAdmin"
    MEMBER_REPRESENTATIVE = "MemberRepresentative"


ALL_ROLES = [role.value for role in UserRole]


# ---------------------------------------------------------------------------
# Status / enumeration vocabularies
# ---------------------------------------------------------------------------
class GovernanceStatus(str, Enum):
    FORMING = "FORMING"
    OPERATING = "OPERATING"


class ReservePosture(str, Enum):
    OPEN = "OPEN"
    RESERVE_RESTRICTED = "RESERVE_RESTRICTED"
    FROZEN = "FROZEN"


class MemberStatus(str, Enum):
    PETITIONED = "PETITIONED"
    ADMISSION_DENIED = "ADMISSION_DENIED"
    ADMITTED_PHASING = "ADMITTED_PHASING"
    FULL_SHARE = "FULL_SHARE"
    WITHDRAWAL_NOTICED = "WITHDRAWAL_NOTICED"
    DEPARTED = "DEPARTED"


class AdmissionPath(str, Enum):
    CHARTER = "CHARTER"
    PETITIONED = "PETITIONED"


class RevenuePoolStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    BOOKS_CLOSED = "BOOKS_CLOSED"
    CLOSED = "CLOSED"


class PoolType(str, Enum):
    MEDIA_RIGHTS = "MEDIA_RIGHTS"
    POSTSEASON_UNIT = "POSTSEASON_UNIT"
    CHAMPIONSHIP = "CHAMPIONSHIP"


class AllocationMethod(str, Enum):
    APPEARANCE_PERFORMANCE_WEIGHTED = "APPEARANCE_PERFORMANCE_WEIGHTED"
    EQUAL_SHARE = "EQUAL_SHARE"
    UNIT_BASED = "UNIT_BASED"


class DistributionRunStatus(str, Enum):
    COMPUTED = "COMPUTED"
    POSTED = "POSTED"
    SUPERSEDED = "SUPERSEDED"
    REVERSED = "REVERSED"


class RunVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL_AUDITED = "FINAL_AUDITED"


class DistributionLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class BowlAppearanceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"


class EventTier(str, Enum):
    BOWL = "BOWL"
    TOURNAMENT = "TOURNAMENT"


class PostseasonUnitStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    VALIDATED = "VALIDATED"
    VOIDED = "VOIDED"


class MembershipActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VOTING = "VOTING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    WITHDRAWN = "WITHDRAWN"


class ActionType(str, Enum):
    ADMIT = "ADMIT"
    WITHDRAW = "WITHDRAW"


class BallotStatus(str, Enum):
    CAST = "CAST"
    VOIDED = "VOIDED"


class BallotChoice(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"
    ABSTAIN = "ABSTAIN"


class BudgetProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    VOTING = "VOTING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProtectedRivalryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class ScheduleGameStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PLAYED = "PLAYED"
    CANCELLED = "CANCELLED"


class ChampionshipEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HOST_AT_RISK = "HOST_AT_RISK"
    HOSTED = "HOSTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class AuditReportStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"


class AuditOpinion(str, Enum):
    UNQUALIFIED = "UNQUALIFIED"
    QUALIFIED = "QUALIFIED"
    ADVERSE = "ADVERSE"


class ValuationVariant(str, Enum):
    ROLLING_SIX_YEAR = "ROLLING_SIX_YEAR"
    CURRENT_YEAR_ONLY = "CURRENT_YEAR_ONLY"


class TransferType(str, Enum):
    CONTRIBUTION = "CONTRIBUTION"
    WITHDRAWAL = "WITHDRAWAL"


# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version
# ---------------------------------------------------------------------------
class Conference(TypedDict):
    id: str
    name: str
    fiscal_year_start_month: int
    current_fiscal_year: int
    unit_value_cents: int
    phase_schedule_years: int
    governance_status: str
    approved_operating_expense_cents: int
    approved_governance_expense_cents: int
    reserve_target_cents: int
    reserve_balance_cents: int
    reserve_posture: str
    funded_ratio_bps: int
    escrow_balance_cents: int
    governance_fee_revenue_cents: int
    validated_postseason_unit_count: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    name: str
    city: str
    seating_capacity: int
    concurrent_event_capacity: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    conference_id: str
    name: str
    institution_code: str
    admission_path: str
    status: str
    home_venue_id: str
    travel_partner_member_id: Optional[str]
    primary_contact_email: Optional[str]
    grant_of_rights_through_fiscal_year: int
    distribution_phase_bps: int
    voting_weight_bps: int
    phase_year: int
    entry_fee_cents: int
    entry_fee_paid_cents: int
    withdrawal_notice_at: Optional[str]
    withdrawal_effective_fiscal_year: Optional[int]
    notice_days: Optional[int]
    notice_multiplier_bps: int
    base_assessment_cents: int
    surcharge_bracket_bps: int
    surcharge_cents: int
    last_full_annual_distribution_cents: int
    exit_settlement_total_cents: int
    exit_settlement_paid_cents: int
    schedule_compliance_score: int
    created_at: str
    updated_at: str
    version: int


class RevenuePool(TypedDict):
    id: str
    conference_id: str
    fiscal_year: int
    pool_type: str
    allocation_method: str
    gross_revenue_cents: int
    estimated_expense_cents: int
    audited_expense_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionRun(TypedDict):
    id: str
    revenue_pool_id: str
    variant: str
    status: str
    net_pool_cents: int
    reserve_draw_cents: int
    distributable_cents: int
    total_weight_bps: int
    remainder_cents: int
    memo: Optional[str]
    computed_by_user_id: str
    posted_by_user_id: Optional[str]
    posted_at: Optional[str]
    superseded_by_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BowlAppearance(TypedDict):
    id: str
    member_id: str
    fiscal_year: int
    event_name: str
    event_tier: str
    payout_cents: int
    submitted_expense_cents: int
    travel_miles: int
    units_claimed: int
    status: str
    revision_round: int
    allowable_expense_cents: int
    travel_allowance_cents: int
    reimbursement_ceiling_cents: int
    reimbursed_cents: int
    residual_to_pool_cents: int
    created_at: str
    updated_at: str
    version: int


class MembershipAction(TypedDict):
    id: str
    conference_id: str
    member_id: str
    action_type: str
    effective_fiscal_year: int
    entry_fee_cents: int
    rationale: Optional[str]
    status: str
    amend_count: int
    quorum_weight_bps: int
    required_approval_bps: int
    eligible_weight_bps: int
    cast_weight_bps: int
    for_weight_bps: int
    against_weight_bps: int
    quorum_met: bool
    approval_ratio_bps: int
    proposed_by_user_id: str
    closed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BudgetProposal(TypedDict):
    id: str
    conference_id: str
    fiscal_year: int
    proposed_operating_expense_cents: int
    proposed_governance_expense_cents: int
    note: Optional[str]
    status: str
    required_approval_bps: int
    eligible_weight_bps: int
    cast_weight_bps: int
    for_weight_bps: int
    against_weight_bps: int
    quorum_met: bool
    approval_ratio_bps: int
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProtectedRivalry(TypedDict):
    id: str
    conference_id: str
    member_a_id: str
    member_b_id: str
    required_annual_meetings: int
    label: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScheduleGame(TypedDict):
    id: str
    conference_id: str
    home_member_id: str
    away_member_id: str
    venue_id: str
    game_date: str
    fiscal_year: int
    media_designated: bool
    protected_rivalry_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChampionshipEvent(TypedDict):
    id: str
    conference_id: str
    venue_id: str
    host_member_id: str
    revenue_pool_id: str
    sport: str
    fiscal_year: int
    window_start: str
    window_end: str
    status: str
    host_compliance_score_at_award: int
    ticket_revenue_cents: Optional[int]
    sponsorship_revenue_cents: Optional[int]
    event_expense_cents: Optional[int]
    net_event_revenue_cents: Optional[int]
    host_share_cents: Optional[int]
    participant_pool_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AuditReport(TypedDict):
    id: str
    conference_id: str
    distribution_run_id: str
    fiscal_year: int
    opinion: str
    note: Optional[str]
    status: str
    reconciliation_delta_cents: int
    issued_by_user_id: Optional[str]
    accepted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Lighter resources: only id + created_at (PRD §2.5)
# ---------------------------------------------------------------------------
class DistributionLine(TypedDict):
    id: str
    distribution_run_id: str
    member_id: str
    weight_bps: int
    gross_share_cents: int
    remainder_cent_awarded: int
    withheld_cents: int
    governance_fee_cents: int
    gor_offset_cents: int
    net_payable_cents: int
    status: str
    created_at: str


class PostseasonUnit(TypedDict):
    id: str
    bowl_appearance_id: str
    member_id: str
    fiscal_year: int
    unit_index: int
    status: str
    created_at: str


class Ballot(TypedDict):
    id: str
    membership_action_id: Optional[str]
    budget_proposal_id: Optional[str]
    member_id: str
    choice: str
    weight_bps: int
    status: str
    cast_by_user_id: str
    created_at: str


# Resources that never carry updated_at / version.
LIGHT_RESOURCE_FORBIDDEN_FIELDS = ("updated_at", "version")
