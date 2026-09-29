"""
Domain vocabulary for the Theatrical Capitalization & Investor Reporting API.

Every enum member and every response field named here is taken from the PRD.
The two production state axes, the eleven downstream state machines, the five
roles and the response shape of each of the fifteen entities are all declared
below so tests can refer to them by name instead of by string literal.

Note the single deliberate asymmetry in the response shapes: per the PRD,
"A `TheatreEngagement` is a booking record that is written once and never
modified, so it carries only `id` and `created_at`." Its TypedDict therefore
omits `updated_at` and `version`; every other entity carries the full set.
"""

from typing import Any, Dict, List, Optional, TypedDict

# ─── Roles ────────────────────────────────────────────────────────────────
# "The five roles are `GeneralManager`, `Comptroller`, `SyndicationCounsel`,
#  `LeadProducer`, and `Investor`."


class Role:
    GENERAL_MANAGER = "GeneralManager"
    COMPTROLLER = "Comptroller"
    SYNDICATION_COUNSEL = "SyndicationCounsel"
    LEAD_PRODUCER = "LeadProducer"
    INVESTOR = "Investor"


ALL_ROLES = [
    Role.GENERAL_MANAGER,
    Role.COMPTROLLER,
    Role.SYNDICATION_COUNSEL,
    Role.LEAD_PRODUCER,
    Role.INVESTOR,
]

OPERATOR_ROLES = [
    Role.GENERAL_MANAGER,
    Role.COMPTROLLER,
    Role.SYNDICATION_COUNSEL,
    Role.LEAD_PRODUCER,
]


# ─── Enumerations ─────────────────────────────────────────────────────────


class OfferingEntityType:
    LP = "LP"
    LLC = "LLC"


class OfferingStatus:
    """The syndication axis: DRAFT, OFFERING, FULLY_SUBSCRIBED, CAPITALIZED."""

    DRAFT = "DRAFT"
    OFFERING = "OFFERING"
    FULLY_SUBSCRIBED = "FULLY_SUBSCRIBED"
    CAPITALIZED = "CAPITALIZED"


class OperatingStatus:
    """The production-calendar axis."""

    PRE_PRODUCTION = "PRE_PRODUCTION"
    REHEARSAL = "REHEARSAL"
    PREVIEWS = "PREVIEWS"
    RUNNING = "RUNNING"
    CLOSING_NOTICE = "CLOSING_NOTICE"
    CLOSED = "CLOSED"


class RecoupmentStatus:
    UNRECOUPED = "UNRECOUPED"
    RECOUPED = "RECOUPED"


class BudgetStatus:
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


class RoyaltyBasis:
    FIXED_GROSS = "FIXED_GROSS"
    POOL = "POOL"


class EngagementType:
    REHEARSAL = "REHEARSAL"
    TECH = "TECH"
    PERFORMANCE_RUN = "PERFORMANCE_RUN"


class BudgetComponent:
    PRODUCTION = "PRODUCTION"
    REHEARSAL = "REHEARSAL"
    ADVERTISING = "ADVERTISING"
    RESERVE = "RESERVE"
    BONDS_AND_DEPOSITS = "BONDS_AND_DEPOSITS"


class CommitmentStatus:
    PLANNED = "PLANNED"
    COMMITTED = "COMMITTED"
    SPENT = "SPENT"


class DocType:
    LP_AGREEMENT = "LP_AGREEMENT"
    LLC_OPERATING_AGREEMENT = "LLC_OPERATING_AGREEMENT"


class OfferingDocumentStatus:
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class AccreditationStatus:
    UNVERIFIED = "UNVERIFIED"
    ACCREDITED = "ACCREDITED"
    NON_ACCREDITED = "NON_ACCREDITED"


class SubscriptionStatus:
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_CURE = "RETURNED_FOR_CURE"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RESCINDED = "RESCINDED"


class AccountBasis:
    RECOUPMENT_RETURN = "RECOUPMENT_RETURN"
    NET_PROFIT = "NET_PROFIT"


class OperatingBudgetStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ParticipantRole:
    AUTHOR = "AUTHOR"
    COMPOSER = "COMPOSER"
    DIRECTOR = "DIRECTOR"
    CHOREOGRAPHER = "CHOREOGRAPHER"
    DESIGNER = "DESIGNER"
    LEAD_PRODUCER = "LEAD_PRODUCER"
    STAR = "STAR"


class ParticipantStatus:
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class WrapStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    DISPUTED = "DISPUTED"
    AMENDED = "AMENDED"
    VOID = "VOID"


class AllocationStatus:
    ALLOCATED = "ALLOCATED"
    REVERSED = "REVERSED"


class IncomeSource:
    CAST_ALBUM = "CAST_ALBUM"
    FILM_LICENSE = "FILM_LICENSE"
    STOCK_AND_AMATEUR = "STOCK_AND_AMATEUR"
    TOURING_LICENSE = "TOURING_LICENSE"
    MERCHANDISE = "MERCHANDISE"


class IncomeStatus:
    RECORDED = "RECORDED"
    ALLOCATED = "ALLOCATED"


class DistributionType:
    RECOUPMENT_RETURN = "RECOUPMENT_RETURN"
    NET_PROFIT = "NET_PROFIT"
    SUBSIDIARY_RIGHTS = "SUBSIDIARY_RIGHTS"
    RESERVE_RELEASE = "RESERVE_RELEASE"


class DistributionStatus:
    DECLARED = "DECLARED"
    PAID = "PAID"


class ClosingReason:
    SCHEDULED_END = "SCHEDULED_END"
    ECONOMIC = "ECONOMIC"
    VENUE_LOSS = "VENUE_LOSS"


class ClosingNoticeStatus:
    ISSUED = "ISSUED"
    WITHDRAWN = "WITHDRAWN"
    SETTLED = "SETTLED"


# ─── Response shapes ──────────────────────────────────────────────────────
# "Houses, production files, budget lines, operating budgets, offering
#  documents, investors, subscriptions, capital accounts, royalty
#  participants, weekly wraps, royalty allocations, licensing-income rows,
#  distributions, and closing notices all carry the full set: `id`,
#  `created_at`, `updated_at`, and `version`."


class _Versioned(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Theatre(_Versioned, total=False):
    name: str
    seat_count: int
    top_ticket_price_cents: int
    changeover_buffer_days: int
    weekly_fixed_rent_cents: int


class Production(_Versioned, total=False):
    title: str
    offering_entity_type: str
    capitalization_target_cents: int
    reserve_target_cents: int
    theatre_id: str
    pre_recoupment_pool_pct: float
    post_recoupment_pool_pct: float
    subsidiary_rights_investor_share_pct: float
    closing_notice_min_days: int
    royalty_basis: str
    offering_status: str
    operating_status: str
    recoupment_status: str
    budget_status: str
    budget_total_cents: int
    budget_committed_cents: int
    capital_raised_cents: int
    released_capital_cents: int
    escrow_balance_cents: int
    recouped_amount_cents: int
    recoupment_pct: float
    deferred_royalty_cents: int
    distributed_total_cents: int
    distributable_cash_cents: int
    total_pool_points: int
    active_investor_count: int


class TheatreEngagement(TypedDict, total=False):
    """The one entity with no `updated_at` and no `version`."""

    id: str
    created_at: str
    production_id: str
    theatre_id: str
    engagement_type: str
    start_date: str
    end_date: str


class BudgetLine(_Versioned, total=False):
    production_id: str
    component: str
    description: str
    amount_cents: int
    commitment_status: str


class OperatingBudget(_Versioned, total=False):
    production_id: str
    weekly_fixed_running_cost_cents: int
    variable_cost_pct: float
    performances_per_week: int
    status: str


class OfferingDocument(_Versioned, total=False):
    production_id: str
    doc_type: str
    offering_amount_cents: int
    unit_price_cents: int
    max_investors: int
    effective_date: str
    expiration_date: str
    status: str
    withdrawal_reason: Optional[str]
    submitted_units_total: int
    accepted_units_total: int
    accepted_amount_cents: int
    accepted_investor_count: int


class Investor(_Versioned, total=False):
    legal_name: str
    jurisdiction: str
    contact_email: str
    accreditation_status: str


class Subscription(_Versioned, total=False):
    offering_document_id: str
    investor_id: str
    units: int
    amount_cents: int
    status: str
    cure_round_count: int
    defect_note: Optional[str]
    rescission_reason: Optional[str]


class InvestorAccount(_Versioned, total=False):
    production_id: str
    investor_id: str
    units_total: int
    contributed_cents: int
    ownership_pct: float
    basis: str
    recoupment_credited_cents: int
    declared_distribution_cents: int
    distributions_paid_cents: int


class RoyaltyParticipant(_Versioned, total=False):
    production_id: str
    participant_name: str
    role: str
    fixed_gross_pct: float
    pool_points: int
    min_guarantee_cents: int
    pool_share_pct: float
    cumulative_royalty_cents: int
    status: str


class WeeklyWrap(_Versioned, total=False):
    production_id: str
    operating_budget_id: str
    operating_budget_version_pinned: int
    week_ending_date: str
    performances: int
    gross_receipts_cents: int
    paid_attendance: int
    running_expenses_cents: int
    capacity_gross_cents: int
    paid_capacity_pct: float
    variable_cost_cents: int
    adjusted_gross_cents: int
    royalty_base_cents: int
    royalty_basis_applied: Optional[str]
    royalty_pool_cents: Optional[int]
    weekly_operating_profit_cents: Optional[int]
    deferred_royalty_added_cents: Optional[int]
    status: str
    submitted_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    dispute_note: Optional[str]
    void_reason: Optional[str]


class RoyaltyAllocation(_Versioned, total=False):
    wrap_id: str
    royalty_participant_id: str
    basis: str
    points_at_allocation: int
    allocated_cents: int
    status: str


class SubsidiaryRightsIncome(_Versioned, total=False):
    production_id: str
    source: str
    gross_income_cents: int
    received_date: str
    investor_share_cents: int
    status: str


class InvestorDistribution(_Versioned, total=False):
    production_id: str
    distribution_type: str
    total_amount_cents: int
    allocation_breakdown: List[Dict[str, Any]]
    status: str


class ClosingNotice(_Versioned, total=False):
    production_id: str
    notice_date: str
    final_performance_date: str
    reason: str
    notice_days: int
    closing_costs_cents: Optional[int]
    reserve_balance_at_settlement_cents: Optional[int]
    reserve_released_cents: Optional[int]
    closing_cost_shortfall_cents: Optional[int]
    status: str
    issued_by_user_id: str
    settled_by_user_id: Optional[str]
    withdrawal_reason: Optional[str]


class RecoupmentReport(TypedDict, total=False):
    """The pure read published side by side for investor reporting."""

    production_id: str
    capitalization_target_cents: int
    cash_basis_recouped_cents: int
    cash_basis_recoupment_pct: float
    accrual_basis_recouped_cents: int
    accrual_basis_recoupment_pct: float
    deferred_royalty_cents: int
    subsidiary_rights_receivable_cents: int
    recoupment_status: str
    distributable_cash_cents: int


class BreakEvenAnalysis(TypedDict, total=False):
    production_id: str
    operating_budget_id: str
    royalty_min_guarantee_floor_cents: int
    target_adjusted_gross_cents: int
    break_even_gross_cents: int
    capacity_gross_projection_cents: int
    break_even_paid_capacity_pct: float
    weeks_to_recoup_at_last_certified_run_rate: Optional[int]
