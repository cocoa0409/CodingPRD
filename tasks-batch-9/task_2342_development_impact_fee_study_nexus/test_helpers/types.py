"""Typed shapes for the entities and response bodies of this service.

Every entity in this service carries the same four system-managed properties
(``id``, ``created_at``, ``updated_at``, ``version``), so they are factored into
``CommonFields`` and inherited by each entity shape.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """The four system-managed properties every entity carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class FeeProgram(CommonFields, total=False):
    name: str
    jurisdiction_code: str
    fiscal_year_start_month: int
    statutory_expenditure_deadline_years: int
    notice_min_days: int
    protest_threshold_bp: int
    effective_delay_days: int
    admin_charge_bp: int
    credit_cap_bp: int
    los_policy: str
    discount_rate_bp: int
    max_deferral_days: int
    default_penalty_bp: int
    at_risk_window_days: int
    report_grace_days: int
    effective_fee_study_id: Optional[str]
    last_report_fiscal_year: Optional[int]
    last_report_filed_at: Optional[str]
    last_report_filed_by_user_id: Optional[str]
    last_report_status: str


class FacilityCategory(CommonFields, total=False):
    fee_program_id: str
    code: str
    name: str
    demand_unit_label: str
    existing_los_per_demand_unit: float
    planned_los_per_demand_unit: float
    unit_cost_cents: int
    existing_deficiency_demand_units: float
    fund_posture: str
    fund_balance_cents: int
    refund_due_cents: int
    committed_demand_units: float
    deferred_receivable_cents: int
    oldest_unexpended_vintage_at: Optional[str]


class FeeStudy(CommonFields, total=False):
    fee_program_id: str
    title: str
    methodology: str
    status: str
    revision_round: int
    protest_weight_bp: int
    protest_count: int
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    notice_method: Optional[str]
    notice_days: Optional[int]
    notice_published_at: Optional[str]
    protest_window_ends_at: Optional[str]
    adopted_by_user_id: Optional[str]
    adopted_at: Optional[str]
    effective_at: Optional[str]
    activated_at: Optional[str]
    superseded_by_fee_study_id: Optional[str]


class NexusComponent(CommonFields, total=False):
    fee_study_id: str
    facility_category_id: str
    horizon_start_year: int
    horizon_end_year: int
    projected_new_dwelling_units: int
    projected_new_nonres_sqft: int
    demand_units_per_dwelling: float
    demand_units_per_1000_nonres_sqft: float
    growth_demand_units: float
    planned_facility_cost_cents: int
    planned_other_funding_cents: int
    planned_growth_share_bp: int
    planned_capacity_demand_units: float
    existing_tax_credit_per_unit_cents: int
    allocation_status: str
    allocated_at: Optional[str]
    plan_based_cost_per_unit_cents: Optional[int]
    standard_based_cost_per_unit_cents: Optional[int]
    adopted_cost_per_unit_cents: Optional[int]
    nexus_ratio: Optional[float]


class FeeScheduleItem(CommonFields, total=False):
    nexus_component_id: str
    land_use_category: str
    unit_basis: str
    conversion_factor: float
    fee_per_unit_cents: Optional[int]
    schedule_status: str


class ProtestFiling(CommonFields, total=False):
    fee_study_id: str
    protester_name: str
    parcel_count: int
    weight_bp: int
    status: str
    filed_at: str


class AssessedLine(TypedDict, total=False):
    facility_category_id: str
    facility_category_code: str
    demand_units: float
    line_gross_cents: int
    line_credit_cents: int
    line_admin_cents: int
    line_net_cents: int


class DevelopmentApplication(CommonFields, total=False):
    fee_program_id: str
    permit_number: str
    land_use_category: str
    dwelling_units: int
    nonres_sqft: int
    collection_trigger: str
    submitted_by_user_id: str
    assessment_status: str
    collection_status: str
    reassessment_required: bool
    pinned_fee_study_id: Optional[str]
    pinned_fee_study_version: Optional[int]
    assessed_lines: List[AssessedLine]
    gross_assessed_cents: int
    credit_applied_cents: int
    admin_charge_cents: int
    net_due_cents: int
    paid_cents: int
    default_penalty_cents: int
    assessed_at: Optional[str]
    reassessed_at: Optional[str]
    co_issued_at: Optional[str]


class CreditClaim(CommonFields, total=False):
    development_application_id: str
    facility_category_code: str
    credit_type: str
    valuation_method: str
    improvement_value_cents: Optional[int]
    annual_tax_contribution_cents: Optional[int]
    contribution_years: int
    claimed_credit_cents: int
    approved_cents: int
    status: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]


class DeferralAgreement(CommonFields, total=False):
    development_application_id: str
    requested_security_type: str
    security_amount_cents: int
    requested_due_at: str
    due_at: Optional[str]
    status: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    executed_at: Optional[str]
    satisfied_at: Optional[str]
    defaulted_at: Optional[str]


class FundLedgerEntry(CommonFields, total=False):
    facility_category_id: str
    development_application_id: Optional[str]
    kind: str
    amount_cents: int
    vintage_at: Optional[str]
    deadline_at: Optional[str]
    unexpended_cents: int
    entry_status: str
    project_name: Optional[str]
    refunded_entry_id: Optional[str]
    authorized_by_user_id: Optional[str]


class AnnualReportCategoryRow(TypedDict, total=False):
    facility_category_id: str
    code: str
    existing_deficiency_demand_units: float
    collections_cents: int
    expenditures_cents: int
    refunds_cents: int
    unexpended_cents: int
    refund_obligation_cents: int
    earliest_deadline_at: Optional[str]


class AnnualReport(TypedDict, total=False):
    fiscal_year: int
    window_start: str
    window_end: str
    collections_cents: int
    expenditures_cents: int
    refunds_cents: int
    unexpended_cents: int
    refund_obligation_cents: int
    earliest_deadline_at: Optional[str]
    categories: List[AnnualReportCategoryRow]
    filed_late: bool
    report_status: str


class DeadlineSweepResult(TypedDict, total=False):
    refund_due_entry_ids: List[str]
    refund_due_entry_count: int
    defaulted_agreement_ids: List[str]
    delinquent_application_ids: List[str]
    at_risk_category_ids: List[str]
    refund_due_category_ids: List[str]


Payload = Dict[str, Any]
Headers = Dict[str, str]
