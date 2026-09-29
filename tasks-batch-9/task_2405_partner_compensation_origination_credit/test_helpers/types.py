"""Domain types for the Partner Compensation & Origination Credit API.

Entity TypedDicts, state enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# ─── Roles ────────────────────────────────────────────

class UserRole(str, Enum):
    CYCLE_ADMIN = "CycleAdmin"
    PARTNER = "Partner"
    COMMITTEE_MEMBER = "CommitteeMember"
    CREDIT_ARBITER = "CreditArbiter"
    AUDIT_OBSERVER = "AuditObserver"


# ─── State enums ──────────────────────────────────────

class CycleState(str, Enum):
    OPEN_INTAKE = "OPEN_INTAKE"
    SELF_ASSESSMENT = "SELF_ASSESSMENT"
    PEER_REVIEW = "PEER_REVIEW"
    DELIBERATION = "DELIBERATION"
    AWARDS_PUBLISHED = "AWARDS_PUBLISHED"
    TRUE_UP_OPEN = "TRUE_UP_OPEN"
    CLOSED = "CLOSED"


class PartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NOTICE_GIVEN = "NOTICE_GIVEN"
    DEPARTED = "DEPARTED"


class PracticeGroup(str, Enum):
    LITIGATION = "LITIGATION"
    CORPORATE = "CORPORATE"
    TAX = "TAX"
    IP = "IP"
    REGULATORY = "REGULATORY"


class CompensationModel(str, Enum):
    LOCKSTEP = "LOCKSTEP"
    FORMULA = "FORMULA"
    DISCRETIONARY = "DISCRETIONARY"


class MatterState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    WRITTEN_OFF = "WRITTEN_OFF"


class MatterType(str, Enum):
    NEW_CLIENT = "NEW_CLIENT"
    EXPANDED_MATTER = "EXPANDED_MATTER"
    CROSS_SELL = "CROSS_SELL"
    EXISTING = "EXISTING"


class CreditRole(str, Enum):
    ORIGINATING = "ORIGINATING"
    BILLING = "BILLING"
    RESPONSIBLE = "RESPONSIBLE"
    WORKING = "WORKING"


class AllocationSource(str, Enum):
    CLAIM_ALLOCATED = "CLAIM_ALLOCATED"
    SHARING_CONVENTION = "SHARING_CONVENTION"
    DEFAULT_BILLING = "DEFAULT_BILLING"
    WORKING_DERIVED = "WORKING_DERIVED"
    TRANSITION = "TRANSITION"


class AllocationState(str, Enum):
    ACTIVE = "ACTIVE"
    TRANSFERRED = "TRANSFERRED"
    SUPERSEDED = "SUPERSEDED"


class RecordKind(str, Enum):
    BILLABLE = "BILLABLE"
    NON_BILLABLE = "NON_BILLABLE"


class RecordCategory(str, Enum):
    CLIENT_WORK = "CLIENT_WORK"
    FIRM_MANAGEMENT = "FIRM_MANAGEMENT"
    RECRUITING = "RECRUITING"
    PRO_BONO = "PRO_BONO"
    TRAINING = "TRAINING"


class ClaimState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    ALLOCATED = "ALLOCATED"
    REJECTED = "REJECTED"


class ClaimBasis(str, Enum):
    NEW_CLIENT = "NEW_CLIENT"
    EXPANDED_MATTER = "EXPANDED_MATTER"
    CROSS_SELL = "CROSS_SELL"


class AssessmentState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"


class PeerReviewState(str, Enum):
    ASSIGNED = "ASSIGNED"
    SCORED = "SCORED"
    RECUSED = "RECUSED"


class BallotState(str, Enum):
    PENDING = "PENDING"
    CAST = "CAST"
    ABSTAINED = "ABSTAINED"
    RECUSED = "RECUSED"


class AwardState(str, Enum):
    PROPOSED = "PROPOSED"
    PUBLISHED = "PUBLISHED"
    FINALIZED = "FINALIZED"


class PaymentState(str, Enum):
    PENDING = "PENDING"
    DRAWING = "DRAWING"
    TRUED_UP = "TRUED_UP"
    SETTLED = "SETTLED"


class DrawPaymentKind(str, Enum):
    SCHEDULED_DRAW = "SCHEDULED_DRAW"
    DRAW_REVERSAL = "DRAW_REVERSAL"
    TRUE_UP = "TRUE_UP"
    CLAWBACK = "CLAWBACK"
    CAPITAL_WITHHOLDING = "CAPITAL_WITHHOLDING"


class TransitionState(str, Enum):
    PROPOSED = "PROPOSED"
    EFFECTIVE = "EFFECTIVE"
    VOIDED = "VOIDED"


# ─── Entity shapes ────────────────────────────────────

class CompensationCycle(TypedDict):
    id: str
    fiscal_year: int
    state: str
    distributable_pool_cents: int
    lockstep_unit_cents: int
    discretionary_pool_pct: float
    draw_pct: float
    claim_deadline_on: str
    assessment_deadline_on: str
    lockstep_reserved_cents: int
    discretionary_pool_cents: int
    formula_pool_cents: int
    haircut_applied_pct: float
    total_formula_score: float
    total_committee_points: float
    undistributed_cash_cents: int
    unsettled_award_count: int
    reopen_count: int
    confidentiality_locked: bool
    created_at: str
    updated_at: str
    version: int


class Partner(TypedDict):
    id: str
    full_name: str
    practice_group: str
    compensation_model: str
    lockstep_step: int
    admission_year: int
    is_committee_member: bool
    is_credit_arbiter: bool
    evaluation_required: bool
    status: str
    departure_effective_on: Optional[str]
    opening_capital_cents: int
    target_capital_cents: int
    capital_account_balance_cents: int
    ytd_draw_paid_cents: int
    verified_billable_hours: float
    non_billable_points: float
    credited_collection_provisional_cents: int
    credited_collection_final_cents: int
    normalized_credit_index_provisional: float
    normalized_credit_index_final: float
    blended_realization_pct: float
    weighted_profitability_points: float
    formula_score_provisional: float
    formula_score_final: float
    committee_points: float
    responsible_matter_count: int
    created_at: str
    updated_at: str
    version: int


class Matter(TypedDict):
    id: str
    client_key: str
    client_display_name: str
    matter_type: str
    practice_group: str
    opened_on: str
    state: str
    billing_attorney_id: str
    responsible_attorney_id: str
    prior_responsible_attorney_id: Optional[str]
    billed_cents: int
    collected_cents: int
    direct_cost_cents: int
    realization_pct: float
    profitability_index_contribution: float
    profitability_index_fully_loaded: float
    verified_billable_hours: float
    origination_pct_assigned: float
    is_first_matter_for_client: bool
    written_off_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditAllocation(TypedDict):
    id: str
    matter_id: str
    partner_id: str
    credit_role: str
    credit_pct: float
    source: str
    credit_from: str
    credit_through: Optional[str]
    state: str
    credited_collection_provisional_cents: int
    credited_collection_final_cents: int
    created_at: str
    updated_at: str
    version: int


class ContributionRecord(TypedDict):
    id: str
    partner_id: str
    cycle_id: str
    matter_id: Optional[str]
    kind: str
    category: str
    hours: float
    standard_rate_cents: int
    service_period_start: str
    service_period_end: str
    verified: bool
    verified_at: Optional[str]
    standard_value_cents: int
    created_at: str
    updated_at: str
    version: int


class CreditClaim(TypedDict):
    id: str
    cycle_id: str
    matter_id: str
    claimant_partner_id: str
    disputing_partner_id: Optional[str]
    resolved_prior_originator_id: Optional[str]
    claim_basis: str
    requested_pct: float
    contested_pct: Optional[float]
    approved_pct: Optional[float]
    counterparty_pct: Optional[float]
    narrative: str
    dispute_grounds: Optional[str]
    remand_reason: Optional[str]
    state: str
    revision_count: int
    remand_count: int
    created_at: str
    updated_at: str
    version: int


class SelfAssessment(TypedDict):
    id: str
    partner_id: str
    cycle_id: str
    narrative: str
    claimed_origination_pct_total: float
    claimed_non_billable_hours: float
    state: str
    revision_count: int
    returned_reason: Optional[str]
    submitted_at: Optional[str]
    accepted_at: Optional[str]
    scored_review_count: int
    mean_peer_score: float
    created_at: str
    updated_at: str
    version: int


class PeerReview(TypedDict):
    id: str
    self_assessment_id: str
    reviewer_partner_id: str
    state: str
    technical_score: Optional[int]
    collaboration_score: Optional[int]
    client_service_score: Optional[int]
    composite_score: Optional[float]
    comment: Optional[str]
    recusal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeBallot(TypedDict):
    id: str
    cycle_id: str
    subject_partner_id: str
    committee_member_id: str
    state: str
    points_proposed: Optional[float]
    rationale: Optional[str]
    recusal_reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompensationAward(TypedDict):
    id: str
    partner_id: str
    cycle_id: str
    award_state: str
    payment_state: str
    basis_model: str
    target_award_cents: int
    final_award_cents: int
    draw_schedule_monthly_cents: int
    draw_paid_cents: int
    true_up_delta_cents: int
    capital_call_cents: int
    capital_shortfall_cents: int
    reconsideration_count: int
    created_at: str
    updated_at: str
    version: int


class DrawPayment(TypedDict):
    """The cash ledger row is append-only: it carries id and created_at and
    nothing else of that family — no updated_at and no version."""
    id: str
    award_id: str
    kind: str
    period_year: int
    period_month: int
    amount_cents: int
    reversed: bool
    memo: Optional[str]
    created_at: str


class CreditTransition(TypedDict):
    id: str
    departing_partner_id: str
    successor_partner_id: Optional[str]
    matter_id: str
    transferred_pct: float
    prior_credit_pct: float
    state: str
    effective_on: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
