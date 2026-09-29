"""TypedDict shapes for every entity the condominium association API returns.

Every entity except LedgerEntry and Vote carries the common fields
``id`` / ``created_at`` / ``updated_at`` / ``version``.  LedgerEntry and Vote
carry only ``id`` and ``created_at`` -- the PRD forbids implementations from
emitting ``updated_at`` or ``version`` on ledger entries or votes, so those two
shapes deliberately omit them.
"""

from __future__ import annotations

from typing import Any, TypedDict


class CommonFields(TypedDict):
    """Fields present on every versioned entity."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyFields(TypedDict):
    """Fields present on the two append-only entities (LedgerEntry, Vote)."""

    id: str
    created_at: str


class Association(CommonFields):
    legal_name: str
    fiscal_year_start_month: int
    total_interest_bp: int
    operating_cash_cents: int
    reserve_balance_cents: int
    reserve_designated_cents: int
    restricted_sa_cash_cents: int
    master_policy_deductible_cents: int
    association_deductible_cap_cents: int
    late_fee_grace_days: int
    late_fee_percent_bp: int
    late_fee_min_cents: int
    late_fee_cap_cents: int
    lien_threshold_cents: int
    budget_veto_bp: int
    special_assessment_approval_bp: int
    board_quorum_seats: int
    hearing_docket_capacity: int
    element_window_buffer_hours: int
    reserve_adequacy_threshold_bp: int
    reserve_contribution_min_bp: int
    fine_tier_1_cents: int
    fine_tier_2_cents: int
    fine_tier_3_daily_cents: int
    fine_cap_cents: int
    repeat_lookback_days: int
    cure_period_days: int
    appeal_window_days: int
    budget_notice_days: int
    certificate_validity_days: int
    resale_cert_fee_cents: int


class UnitOwner(CommonFields):
    association_id: str
    full_name: str
    email: str
    board_role: str
    is_seated: bool
    owned_unit_count: int


class Unit(CommonFields):
    association_id: str
    current_owner_id: str
    unit_label: str
    interest_bp: int
    heated_sqft: int
    monthly_assessment_cents: int
    balance_due_cents: int
    credit_balance_cents: int
    oldest_unpaid_age_days: int
    delinquency_stage: str
    voting_eligible: bool
    lien_recorded_at: str | None
    transfer_blocked: bool


class LedgerEntry(AppendOnlyFields):
    unit_id: str
    billing_run_id: str | None
    source_case_id: str | None
    special_assessment_id: str | None
    source_claim_id: str | None
    reverses_entry_id: str | None
    entry_type: str
    bucket: str | None
    amount_cents: int
    due_on: str | None
    posted_at: str
    effective_period: str | None
    applied_allocations: list[dict[str, Any]] | None
    unapplied_cents: int
    applied_cents: int
    status: str
    memo: str | None


class Budget(CommonFields):
    association_id: str
    supersedes_budget_id: str | None
    ratification_meeting_id: str | None
    fiscal_year: int
    operating_total_cents: int
    reserve_contribution_cents: int
    assessment_total_cents: int
    monthly_assessable_cents: int
    status: str
    notice_sent_at: str | None
    revision_round: int
    no_weight_bp: int
    allocation_snapshot: list[dict[str, Any]] | None
    adopted_at: str | None


class BillingRun(CommonFields):
    association_id: str
    source_budget_id: str
    period: str
    due_on: str
    assessment_charged_cents: int
    remainder_cents_allocated: int
    late_fees_charged_cents: int
    charged_unit_count: int
    escalated_unit_count: int
    fines_finalized_count: int
    executed_at: str


class SpecialAssessment(CommonFields):
    association_id: str
    funding_claim_id: str | None
    purpose: str
    total_amount_cents: int
    installment_count: int
    approval_status: str
    funding_status: str
    ballot_opened_at: str | None
    ballot_closed_at: str | None
    eligible_weight_bp: int
    yes_weight_bp: int
    installments_posted: int
    charged_cents: int
    collected_cents: int
    refunded_cents: int
    requires_supermajority_disclosure: bool


class Vote(AppendOnlyFields):
    association_id: str
    subject_type: str
    subject_id: str
    meeting_id: str | None
    unit_id: str | None
    voter_owner_id: str
    voter_kind: str
    choice: str
    weight_bp: int
    counted: bool
    cast_at: str


class BoardMeeting(CommonFields):
    association_id: str
    scheduled_start: str
    scheduled_end: str
    agenda_kinds: list[str]
    notice_sent_at: str | None
    status: str
    seated_director_count: int
    quorum_met: bool
    hearing_slot_count: int


class CommonElement(CommonFields):
    association_id: str
    name: str
    element_class: str
    is_life_safety: bool
    status: str
    replacement_cost_cents: int
    useful_life_years: int
    effective_age_years: int
    reserve_designated_cents: int
    last_serviced_at: str | None


class VendorContract(CommonFields):
    association_id: str
    covered_element_id: str
    vendor_name: str
    contract_cap_cents: int
    committed_cents: int
    invoiced_cents: int
    insurance_cert_expires_at: str
    effective_from: str
    effective_to: str
    status: str
    approval_yes_count: int
    pinned_element_version: int | None
    suspension_reason: str | None


class MaintenanceWorkOrder(CommonFields):
    association_id: str
    contract_id: str
    element_id: str
    claim_id: str | None
    scope: str
    window_start: str
    window_end: str
    estimated_cost_cents: int
    final_cost_cents: int | None
    encumbered_cents: int
    is_emergency: bool
    hold_reason: str | None
    status: str


class InsuranceClaim(CommonFields):
    association_id: str
    unit_id: str | None
    element_id: str | None
    loss_type: str
    loss_at: str
    gross_damage_cents: int
    within_unit_boundary_cents: int
    common_element_damage_cents: int
    affected_unit_ids: list[str]
    adjustment_status: str
    litigation_status: str
    deductible_allocation: list[dict[str, Any]] | None
    association_absorbed_cents: int
    owner_chargeback_cents: int
    appeal_round: int
    disclosure_required: bool


class ViolationCase(CommonFields):
    association_id: str
    unit_id: str
    prior_case_id: str | None
    reported_by_owner_id: str | None
    decision_owner_id: str | None
    hearing_meeting_id: str | None
    rule_code: str
    continuing_days: int
    notice_sent_at: str | None
    cure_deadline_at: str | None
    hearing_slot_start: str | None
    hearing_round: int
    fine_tier: int | None
    fine_amount_cents: int | None
    fine_entry_id: str | None
    appeal_deadline_at: str | None
    status: str


class ResaleCertificate(CommonFields):
    unit_id: str
    pinned_budget_id: str | None
    requesting_agent_id: str | None
    closing_date: str
    payoff_basis: str
    status: str
    pinned_unit_version: int | None
    pinned_budget_version: int | None
    ledger_balance_cents: int
    projected_payoff_cents: int
    proration_credit_cents: int
    open_violation_count: int
    special_assessment_disclosure_cents: int
    disclosed_claim_ids: list[str]
    cert_fee_entry_id: str | None
    requires_reissue: bool
    issued_at: str | None
    expires_at: str | None


class ReserveAdequacyReport(TypedDict):
    """Computed payload of GET /associations/{id}/reserve-adequacy."""

    fully_funded_cents: int
    spendable_cents: int
    percent_funded_bp: int
    posture: str


class UnitStatement(TypedDict, total=False):
    """Computed payload of GET /units/{id}/statement."""

    unit_id: str
    balance_due_cents: int
    credit_balance_cents: int
    oldest_unpaid_age_days: int
    delinquency_stage: str
    bucket_balances: dict[str, int]


class LenderQuestionnaire(TypedDict, total=False):
    """Computed payload of GET /resale-certificates/{id}/lender-questionnaire."""

    ledger_balance_cents: int
    projected_payoff_cents: int
    proration_credit_cents: int
    delinquency_stage: str
    open_violation_count: int
    special_assessment_disclosure_cents: int
    disclosed_claim_ids: list[str]
