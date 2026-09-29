"""Typed shapes for every response row the API returns.

Rows carry an id, a created_at and, where the contract declares an updated_at and
a version counter, those two as well. ProductionRecord is the single immutable row
in the model: it carries an id and a created_at and nothing else from that set.
"""

from typing import Any, Dict, List, Optional, TypedDict


class ResponseMeta(TypedDict):
    api_request_id: str
    api_request_timestamp: str


class ErrorPayload(TypedDict, total=False):
    error_id: str
    message: str


class Operator(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    region_code: str
    financial_assurance_tier: str
    bond_amount_cents: int
    status: str
    required_bond_cents: int
    active_well_count: int
    orphan_candidate_count: int
    successor_operator_id: Optional[str]
    insolvency_declared_at: Optional[str]
    bond_forfeited_at: Optional[str]


class Well(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    api_well_number: str
    operator_id: str
    spud_year: int
    total_depth_ft: int
    casing_strings: int
    methane_scfd: float
    groundwater_depth_ft: int
    population_within_1000ft: int
    surface_disturbance_acres: float
    last_production_month: Optional[str]
    status: str
    access_status: str
    screening_score: float
    remediation_score: float
    idle_months: int
    cumulative_boe_60mo: float
    orphan_confirmed_at: Optional[str]


class ProductionRecord(TypedDict, total=False):
    id: str
    created_at: str
    well_id: str
    month: str
    oil_bbl: float
    gas_mcf: float
    boe: float
    reported_by_user_id: str


class OrphanDetermination(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    well_id: str
    inspector_notes: str
    status: str
    revision_round: int
    created_by_user_id: str
    decided_by_user_id: Optional[str]
    snapshot_idle_months: Optional[int]
    snapshot_cumulative_boe_60mo: Optional[float]
    snapshot_screening_score: Optional[float]
    decision_rationale: Optional[str]
    submitted_at: Optional[str]
    decided_at: Optional[str]


class SiteAccess(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    well_id: str
    surface_owner_name: str
    mode: str
    waiting_period_days: int
    compensation_cents: int
    notice_sent_at: str
    window_end_at: str
    status: str
    legal_authority_citation: Optional[str]
    resolved_at: Optional[str]


class WellTransfer(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    well_id: str
    from_operator_id: str
    to_operator_id: str
    status: str
    transferee_required_bond_cents: int
    decided_by_user_id: Optional[str]
    approved_at: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]


class Contractor(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    license_number: str
    bond_amount_cents: int
    performance_score: float
    license_status: str
    suspended_at: Optional[str]


class Solicitation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    region_code: str
    scope_description: str
    bid_due_at: str
    ceiling_cents: int
    min_technical_score: float
    status: str
    reopen_round: int
    created_by_user_id: str


class Bid(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    solicitation_id: str
    contractor_id: str
    cement_per_sack_cents: int
    rig_day_rate_cents: int
    casing_per_ft_cents: int
    mobilization_fee_cents: int
    technical_score: float
    evaluated_unit_cost_cents: int
    price_score: Optional[float]
    composite_score: Optional[float]
    status: str
    evaluated_by_user_id: Optional[str]
    nonresponsive_reason: Optional[str]


class UnitCostContract(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    solicitation_id: str
    contractor_id: str
    winning_bid_id: str
    cement_per_sack_cents: int
    rig_day_rate_cents: int
    casing_per_ft_cents: int
    mobilization_fee_cents: int
    ceiling_cents: int
    obligated_cents: int
    status: str
    awarded_by_user_id: str


class PluggingJob(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    well_id: str
    contract_id: str
    scheduled_start: str
    planned_cement_sacks: int
    planned_rig_days: int
    planned_casing_ft: int
    plugging_cost_estimate_cents: int
    crew_window_end_at: str
    status: str
    rework_round: int
    cement_sacks_used: Optional[int]
    rig_days_used: Optional[int]
    casing_removed_ft: Optional[int]
    downhole_conditions: Optional[str]
    plug_intervals: Optional[List[Any]]
    last_round_cost_cents: Optional[int]
    actual_cost_cents: int
    funded_cents: int
    mobilized_at: Optional[str]
    plugging_accepted_at: Optional[str]
    reclaimed_at: Optional[str]


class ReclamationTask(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    job_id: str
    task_type: str
    status: str
    inspection_round: int
    inspected_by_user_id: Optional[str]
    notes: Optional[str]
    completed_at: Optional[str]


class FundingSource(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    kind: str
    name: str
    authorized_cents: int
    committed_cents: int
    disbursed_cents: int
    expires_at: str
    federal_match_required_pct: Optional[int]
    allowable_cost_categories: List[str]
    bond_operator_id: Optional[str]
    status: str
    reporting_required: bool


class FundingAllocation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    job_id: str
    source_id: str
    allocated_cents: int
    disbursed_cents: int
    waterfall_rank: int
    status: str
    committed_by_user_id: str
    disbursed_by_user_id: Optional[str]
    disbursed_at: Optional[str]
    deobligated_at: Optional[str]


class GrantReport(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    source_id: str
    period_start: str
    period_end: str
    wells_plugged_count: int
    reported_cost_cents: int
    federal_share_pct: float
    status: str
    revision_round: int
    submitted_by_user_id: Optional[str]
    reviewer_note: Optional[str]


VERSIONED_ROW_FIELDS = ("id", "created_at", "updated_at", "version")
IMMUTABLE_ROW_FIELDS = ("id", "created_at")

JsonDict = Dict[str, Any]
