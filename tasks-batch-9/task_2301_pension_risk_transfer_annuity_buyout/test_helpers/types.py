"""Domain types for the Pension Risk Transfer & Annuity Buyout API.

Status enums, action enums, role enum and entity TypedDicts. Field names are
exactly the names the PRD uses on the wire.
"""

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PLAN_SPONSOR = "PlanSponsor"
    PLAN_FIDUCIARY = "PlanFiduciary"
    ACTUARY = "Actuary"
    PLAN_ADMINISTRATOR = "PlanAdministrator"
    REGULATOR = "Regulator"
    INSURER_REP = "InsurerRep"
    PARTICIPANT = "Participant"
    INDEPENDENT_EXPERT_USER = "IndependentExpertUser"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------


class PlanStatus(str, Enum):
    ONGOING = "ONGOING"
    SETTLEMENT_AUTHORIZED = "SETTLEMENT_AUTHORIZED"
    RESIDUAL = "RESIDUAL"
    TERMINATION_FILED = "TERMINATION_FILED"
    FILING_DEFICIENT = "FILING_DEFICIENT"
    TERMINATED = "TERMINATED"


class AmendmentScope(str, Enum):
    LUMP_SUM_ONLY = "LUMP_SUM_ONLY"
    BUYOUT_ONLY = "BUYOUT_ONLY"
    BOTH = "BOTH"


class AmendmentAction(str, Enum):
    ADOPT = "ADOPT"
    RESCIND = "RESCIND"


class StrategyType(str, Enum):
    LUMP_SUM_WINDOW = "LUMP_SUM_WINDOW"
    ANNUITY_BUYOUT = "ANNUITY_BUYOUT"
    LDI_GLIDEPATH = "LDI_GLIDEPATH"
    HYBRID_WINDOW_AND_BUYOUT = "HYBRID_WINDOW_AND_BUYOUT"


class StrategyStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_EVALUATION = "UNDER_EVALUATION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


class StrategyDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    RETURN_FOR_REVISION = "RETURN_FOR_REVISION"


class Cohort(str, Enum):
    RETIREE_IN_PAY = "RETIREE_IN_PAY"
    DEFERRED_VESTED = "DEFERRED_VESTED"


class ParticipantStatus(str, Enum):
    IN_PLAN = "IN_PLAN"
    ASSIGNED = "ASSIGNED"
    TRANSFERRED_TO_INSURER = "TRANSFERRED_TO_INSURER"
    SETTLED_LUMP_SUM = "SETTLED_LUMP_SUM"
    RESIDUAL_ANNUITY_PURCHASED = "RESIDUAL_ANNUITY_PURCHASED"


class MortalityStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    ALIVE_CONFIRMED = "ALIVE_CONFIRMED"
    DECEASED_CONFIRMED = "DECEASED_CONFIRMED"
    DEATH_DISPUTED = "DEATH_DISPUTED"


class MortalityMatchResult(str, Enum):
    NO_MATCH = "NO_MATCH"
    DEATH_MATCH = "DEATH_MATCH"
    DISPUTE_FILED = "DISPUTE_FILED"
    DISPUTE_RESOLVED_ALIVE = "DISPUTE_RESOLVED_ALIVE"
    DISPUTE_RESOLVED_DECEASED = "DISPUTE_RESOLVED_DECEASED"


class AddressStatus(str, Enum):
    UNCONFIRMED = "UNCONFIRMED"
    CONFIRMED = "CONFIRMED"
    UNLOCATABLE = "UNLOCATABLE"


class AddressSearchTier(str, Enum):
    NONE = "NONE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class AddressSearchResult(str, Enum):
    NO_MATCH = "NO_MATCH"
    CONFIRMED_MATCH = "CONFIRMED_MATCH"


class BenefitAuditStatus(str, Enum):
    OPEN = "OPEN"
    PASSED = "PASSED"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"
    PASSED_CLOSED = "PASSED_CLOSED"
    CORRECTED = "CORRECTED"
    REOPENED = "REOPENED"
    SUPERSEDED = "SUPERSEDED"


class ParticipantAuditStatus(str, Enum):
    """The mirror of the audit lifecycle carried on the participant record."""

    NOT_AUDITED = "NOT_AUDITED"
    AUDIT_OPEN = "AUDIT_OPEN"
    CORRECTION_REQUIRED = "CORRECTION_REQUIRED"
    PASSED_CLOSED = "PASSED_CLOSED"
    CORRECTED = "CORRECTED"
    REOPENED = "REOPENED"


class AuditBasis(str, Enum):
    PLAN_DOCUMENT = "PLAN_DOCUMENT"
    COLLECTIVE_AGREEMENT = "COLLECTIVE_AGREEMENT"
    PRIOR_ADMINISTRATOR_FILE = "PRIOR_ADMINISTRATOR_FILE"


class AuditResolution(str, Enum):
    APPLY_CORRECTION = "APPLY_CORRECTION"
    ACCEPT_AS_IS = "ACCEPT_AS_IS"


class DataStatus(str, Enum):
    CLEAN = "CLEAN"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class WindowStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class ElectionStatus(str, Enum):
    NOTICE_SENT = "NOTICE_SENT"
    ELECTED_LUMP_SUM = "ELECTED_LUMP_SUM"
    ELECTED_ANNUITY = "ELECTED_ANNUITY"
    CAP_DEFERRED = "CAP_DEFERRED"
    DEFAULTED_NO_RESPONSE = "DEFAULTED_NO_RESPONSE"
    PAID = "PAID"
    VOIDED = "VOIDED"


class ElectionChoice(str, Enum):
    LUMP_SUM = "LUMP_SUM"
    ANNUITY = "ANNUITY"


class TrancheStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTING = "QUOTING"
    INSURER_SELECTED = "INSURER_SELECTED"
    PRICING_LOCKED = "PRICING_LOCKED"
    ASSETS_TRANSFERRED = "ASSETS_TRANSFERRED"
    SETTLED = "SETTLED"
    ABANDONED = "ABANDONED"


class DataReadinessFlag(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class SelectionBasis(str, Enum):
    SAFETY_WEIGHTED = "SAFETY_WEIGHTED"
    PRICE_WEIGHTED = "PRICE_WEIGHTED"


class RatingGrade(str, Enum):
    AAA = "AAA"
    AA_PLUS = "AA_PLUS"
    AA = "AA"
    AA_MINUS = "AA_MINUS"
    A_PLUS = "A_PLUS"
    A = "A"
    BBB = "BBB"


class InsurerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    WITHDRAWN = "WITHDRAWN"


class QuoteStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SUBMITTED = "SUBMITTED"
    SHORTLISTED = "SHORTLISTED"
    LOCKED = "LOCKED"
    BOUND = "BOUND"
    DECLINED = "DECLINED"
    INELIGIBLE = "INELIGIBLE"
    EXPIRED = "EXPIRED"


class SubmissionDecision(str, Enum):
    SUBMIT = "SUBMIT"
    DECLINE = "DECLINE"


class ExpertStatus(str, Enum):
    INDEPENDENCE_REVIEW = "INDEPENDENCE_REVIEW"
    ENGAGED = "ENGAGED"
    DISQUALIFIED = "DISQUALIFIED"
    OPINION_ISSUED = "OPINION_ISSUED"


class ExpertReviewDecision(str, Enum):
    ENGAGE = "ENGAGE"
    DISQUALIFY = "DISQUALIFY"


class SafestAvailableOpinion(str, Enum):
    AFFIRMATIVE = "AFFIRMATIVE"
    QUALIFIED = "QUALIFIED"
    ADVERSE = "ADVERSE"


class TransferMode(str, Enum):
    IN_KIND = "IN_KIND"
    CASH = "CASH"


class TransferStatus(str, Enum):
    INITIATED = "INITIATED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class InsurerDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class SettlementEntryType(str, Enum):
    BUYOUT_RECOGNITION = "BUYOUT_RECOGNITION"
    LUMP_SUM_RECOGNITION = "LUMP_SUM_RECOGNITION"
    REMEDIATION = "REMEDIATION"
    REMEDIATION_REVERSAL = "REMEDIATION_REVERSAL"
    PLAN_TERMINATION = "PLAN_TERMINATION"


class ComplaintCategory(str, Enum):
    BENEFIT_AMOUNT = "BENEFIT_AMOUNT"
    MISSING_PAYMENT = "MISSING_PAYMENT"
    ADDRESS_OR_IDENTITY = "ADDRESS_OR_IDENTITY"
    ANNUITY_FORM = "ANNUITY_FORM"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    RESOLVED = "RESOLVED"
    CLOSED_FINAL = "CLOSED_FINAL"


class ResponsibilityDetermination(str, Enum):
    SPONSOR_RESPONSIBLE = "SPONSOR_RESPONSIBLE"
    INSURER_RESPONSIBLE = "INSURER_RESPONSIBLE"
    NO_ERROR = "NO_ERROR"


class FilingReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN_DEFICIENT = "RETURN_DEFICIENT"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------


class PensionPlan(TypedDict):
    id: str
    sponsor_name: str
    plan_name: str
    plan_ein: str
    plan_status: str
    total_liability_cents: int
    plan_assets_cents: int
    service_cost_cents: int
    interest_cost_cents: int
    unrecognized_actuarial_loss_cents: int
    discount_rate_bps: int
    accounting_funded_status_bp: int
    participant_liability_total_cents: int
    amendment_scope: Optional[str]
    amendment_adopted_at: Optional[str]
    amendment_effective_date: Optional[str]
    cumulative_settlement_charge_cents: int
    deferred_settlement_charge_cents: int
    filing_reference: Optional[str]
    filing_submitted_at: Optional[str]
    filing_deficiency_reason: Optional[str]
    residual_effective_at: Optional[str]
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeRiskingStrategy(TypedDict):
    id: str
    plan_id: str
    strategy_type: str
    strategy_label: str
    ldi_hedge_ratio_bp: int
    strategy_status: str
    projected_accounting_cost_cents: Optional[int]
    projected_settlement_cost_cents: Optional[int]
    projected_basis_gap_cents: Optional[int]
    in_scope_participant_count: int
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    revision_count: int
    decision_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParticipantRecord(TypedDict):
    id: str
    plan_id: str
    tranche_id: Optional[str]
    participant_reference: str
    cohort: str
    date_of_birth: Optional[str]
    ssn_last4: Optional[str]
    stated_monthly_benefit_cents: int
    final_average_monthly_earnings_cents: int
    credited_service_months: int
    audited_monthly_benefit_cents: Optional[int]
    participant_status: str
    mortality_status: str
    address_status: str
    address_search_tier: str
    address_search_attempts: int
    confirmed_address_line1: Optional[str]
    confirmed_postal_code: Optional[str]
    date_of_death: Optional[str]
    benefit_audit_status: str
    data_confidence_score: int
    data_status: str
    accounting_liability_cents: int
    settlement_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class BenefitAudit(TypedDict):
    id: str
    participant_id: str
    audit_basis: str
    audit_sequence: int
    stated_monthly_benefit_cents: int
    recomputed_monthly_benefit_cents: int
    variance_cents: int
    audit_status: str
    resolution: Optional[str]
    override_rationale: Optional[str]
    reopened_by_complaint_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LumpSumWindow(TypedDict):
    id: str
    plan_id: str
    window_label: str
    opens_at: str
    closes_at: str
    eligibility_max_lump_sum_cents: int
    lump_sum_cap_cents: int
    window_status: str
    notice_count: int
    approved_lump_sum_total_cents: int
    paid_lump_sum_total_cents: int
    opened_at: Optional[str]
    closed_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParticipantElection(TypedDict):
    id: str
    window_id: str
    participant_id: str
    election_status: str
    notice_sent_at: str
    notice_estimated_lump_sum_cents: int
    election_choice: Optional[str]
    elected_at: Optional[str]
    raw_pv_cents: Optional[int]
    admin_fee_bp: Optional[int]
    admin_fee_cents: Optional[int]
    net_lump_sum_cents: Optional[int]
    revocation_count: int
    paid_at: Optional[str]
    paid_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class BuyoutTranche(TypedDict):
    id: str
    plan_id: str
    tranche_label: str
    target_cohort: str
    tranche_status: str
    assigned_participant_count: int
    accounting_liability_cents: int
    settlement_liability_cents: int
    data_readiness_flag: str
    selection_basis: Optional[str]
    selected_quote_id: Optional[str]
    selected_insurer_id: Optional[str]
    selection_score_bp: Optional[int]
    locked_premium_cents: Optional[int]
    lock_start_at: Optional[str]
    lock_expires_at: Optional[str]
    transfer_expense_cents: int
    settlement_gain_loss_cents: Optional[int]
    settled_at: Optional[str]
    abandoned_at: Optional[str]
    abandonment_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Insurer(TypedDict):
    id: str
    insurer_name: str
    rating_grade: str
    capital_ratio_bp: int
    state_guaranty_coverage_cents: int
    capacity_cents: int
    committed_capacity_cents: int
    available_capacity_cents: int
    insurer_status: str
    rating_changed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AnnuityQuote(TypedDict):
    id: str
    tranche_id: str
    insurer_id: str
    quote_status: str
    requested_at: str
    premium_cents: Optional[int]
    lock_days: Optional[int]
    quote_valid_days: Optional[int]
    submitted_at: Optional[str]
    expires_at: Optional[str]
    rating_at_submission: Optional[str]
    composite_score_bp: Optional[int]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IndependentExpert(TypedDict):
    id: str
    plan_id: str
    expert_firm_name: str
    conflict_disclosed: bool
    expert_status: str
    proposed_by_user_id: str
    reviewed_by_user_id: Optional[str]
    safest_available_opinion: Optional[str]
    opinion_issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssetTransfer(TypedDict):
    id: str
    tranche_id: str
    transfer_mode: str
    in_kind_market_value_cents: Optional[int]
    in_kind_lot_count: Optional[int]
    cash_amount_cents: Optional[int]
    gross_value_cents: int
    credited_value_cents: int
    transfer_expense_cents: int
    shortfall_cents: int
    transfer_status: str
    insurer_decision: Optional[str]
    rejection_reason: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementEntry(TypedDict):
    """Append-only ledger row: carries only id and created_at, no version."""

    id: str
    plan_id: str
    tranche_id: Optional[str]
    window_id: Optional[str]
    entry_type: str
    amount_cents: int
    deferred_amount_cents: int
    gain_loss_cents: int
    pbo_settled_cents: int
    source_reference: str
    posted_at: str
    created_at: str


class ParticipantComplaint(TypedDict):
    id: str
    participant_id: str
    tranche_id: Optional[str]
    complaint_reference: str
    complaint_category: str
    complaint_detail: str
    complaint_status: str
    responsibility_determination: Optional[str]
    determination_rationale: Optional[str]
    remediation_amount_cents: int
    reversed_amount_cents: int
    triage_count: int
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
