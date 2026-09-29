"""TypedDict shapes for every resource the HOA Declarant Turnover API persists.

§2.4 of the PRD: every persisted resource carries ``id``, ``created_at``,
``updated_at`` and ``version``, so those four keys appear on every shape here
through the shared ``CommonFields`` base.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """The four system-managed properties every persisted resource carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Association(CommonFields, total=False):
    name: str
    total_planned_lots: int
    turnover_threshold_pct: float
    fixed_turnover_date: str
    statute_of_repose_years: int
    reserve_pool_cents: int
    reserve_claim_pool_cents: int
    declarant_monthly_subsidy_cents: int
    sold_lot_count: int
    sold_lot_pct: float
    subsidy_receivable_cents: int
    subsidy_end_date: Optional[str]
    reserve_claim_committed_cents: int
    reserve_claim_available_cents: int
    budget_forecast_status: str


class TurnoverCase(CommonFields, total=False):
    association_id: str
    total_seats: int
    governance_status: str
    financial_status: str
    turnover_posture: str
    trigger_basis: Optional[str]
    trigger_certified_at: Optional[str]
    trigger_certified_by_user_id: Optional[str]
    declarant_appointed_seats: int
    owner_elected_seats: int
    owner_elected_seats_required: int
    vacant_seats: int
    records_transfer_completeness_pct: float
    settlement_blocked: bool


class Lot(CommonFields, total=False):
    association_id: str
    lot_number: str
    sale_status: str
    closing_date: Optional[str]


class CommonAreaComponent(CommonFields, total=False):
    association_id: str
    name: str
    category: str
    replacement_cost_cents: int
    useful_life_years: int
    effective_age_years: int
    promised_completion_date: str
    build_status: str
    conveyance_status: str
    substantial_completion_date: Optional[str]
    conveyed_at: Optional[str]


class ReserveStudy(CommonFields, total=False):
    association_id: str
    funding_method: str
    planned_annual_contribution_cents: int
    projected_annual_expenditure_cents: int
    status: str
    evaluated_method: Optional[str]
    adequacy_verdict: str
    recommended_annual_contribution_cents: int
    component_count: int
    fully_funded_balance_cents: int
    percent_funded: float
    min_projected_balance_cents: int


class SubsidyEntry(CommonFields, total=False):
    association_id: str
    direction: str
    amount_cents: int
    period_month: str
    status: str
    posted_by_user_id: str
    reverses_entry_id: Optional[str]
    reason: Optional[str]


class AuditEngagement(CommonFields, total=False):
    association_id: str
    period_start: str
    period_end: str
    status: str
    finding_status: str
    audited_receivable_snapshot_cents: int
    unreconciled_delta_cents: int
    issued_by_user_id: Optional[str]


class DefectClaim(CommonFields, total=False):
    association_id: str
    component_id: str
    defect_summary: str
    repair_cost_estimate_cents: int
    diminution_value_cents: int
    status: str
    negotiation_round: int
    valuation_basis: Optional[str]
    reserve_subtotal_cents: int
    litigation_admin_fee_cents: int
    reserved_amount_cents: int
    settlement_amount_cents: Optional[int]
    repose_deadline: Optional[str]


class VendorContract(CommonFields, total=False):
    association_id: str
    component_id: str
    vendor_name: str
    developer_affiliated: bool
    annual_cost_cents: int
    service_window_start: str
    service_window_end: str
    status: str
    assignment_status: str
    cancellation_window_end: Optional[str]


class RecordsTransferItem(CommonFields, total=False):
    turnover_case_id: str
    category: str
    required: bool
    status: str
    delivered_at: Optional[str]
    rejection_reason: Optional[str]


class Director(CommonFields, total=False):
    turnover_case_id: str
    full_name: str
    seat_type: str
    status: str
    seated_by_user_id: str
    vacated_at: Optional[str]


class AssessmentSchedule(CommonFields, total=False):
    association_id: str
    fiscal_year: int
    projected_operating_cost_cents: int
    status: str
    billable_lot_count: int
    reserve_contribution_cents: int
    subsidy_offset_cents: int
    annual_requirement_cents: int
    per_lot_monthly_assessment_cents: int
    annual_budget_total_cents: int
    residual_cents: int
    increase_pct_vs_prior: float
    owner_vote_required: bool
    owner_vote_ratified: bool


class ReposeSweepResult(TypedDict, total=False):
    swept_claim_count: int
    time_barred_claim_ids: List[str]


class ClockState(TypedDict, total=False):
    current_utc: str


Payload = Dict[str, Any]
Headers = Dict[str, str]
