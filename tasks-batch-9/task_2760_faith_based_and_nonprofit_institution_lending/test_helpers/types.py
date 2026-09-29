"""
TypedDict shapes for the eleven resource collections (PRD §2.4).

All eleven carry the same four server-managed properties — ``id``,
``created_at``, ``updated_at`` and ``version`` — declared once in
``CommonFields`` and inherited by every resource type below.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """PRD §2.4: the four server-managed properties every collection carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Institution(CommonFields, total=False):
    legal_name: str
    institution_type: str
    denomination_code: str
    requires_denominational_approval: bool
    bylaws_borrowing_cap_cents: int
    bylaws_quorum_pct: float
    community_program_count: int
    endowment_market_value_cents: int
    audited_period_count: int
    period_count: int
    unrestricted_giving_base_cents: int
    net_available_for_debt_service_dollars: int
    membership_trend_pct: Optional[float]
    cumulative_forgiveness_cents: int


class GivingPeriod(CommonFields, total=False):
    institution_id: str
    period_label: str
    period_start: str
    period_end: str
    source: str
    total_contributions_cents: int
    restricted_contributions_cents: int
    donor_restricted_endowment_draw_cents: int
    operating_expense_cents: int
    member_household_count: int
    unrestricted_contributions_cents: int
    net_available_for_debt_service_cents: int


class GovernanceAuthorization(CommonFields, total=False):
    institution_id: str
    resolution_date: str
    bylaws_citation: str
    board_votes_for: int
    board_votes_total: int
    authorized_amount_cents: int
    expires_on: str
    denominational_body: Optional[str]
    status: str
    revision_round: int
    board_quorum_pct: Optional[float]
    verified_by_user_id: Optional[str]
    minutes_reference: Optional[str]
    denominational_decision_note: Optional[str]
    rework_note: Optional[str]


class PledgeCampaign(CommonFields, total=False):
    institution_id: str
    campaign_name: str
    goal_cents: int
    pledge_period_months: int
    sponsor_collection_rate_bps: int
    status: str
    total_pledged_cents: int
    active_pledged_cents: int
    lapsed_pledged_cents: int
    fulfilled_pledged_cents: int
    collected_to_date_cents: int
    attrition_adjusted_value_cents: int
    sponsor_projected_value_cents: int
    close_note: Optional[str]


class Pledge(CommonFields, total=False):
    pledge_campaign_id: str
    donor_tier: str
    pledged_amount_cents: int
    installment_count: int
    status: str
    collected_cents: int
    payments_made_count: int
    missed_payments_count: int
    effective_attrition_pct: float
    lapse_reason: Optional[str]
    reinstatement_note: Optional[str]


class CollateralAsset(CommonFields, total=False):
    institution_id: str
    asset_type: str
    description_label: str
    appraised_value_cents: int
    appraisal_date: str
    alternative_use_score: int
    appraisal_age_days: int
    lending_value_cents: int
    assigned_loan_application_id: Optional[str]
    lien_position: Optional[int]
    lien_effective_from: Optional[str]
    lien_effective_to: Optional[str]
    lien_history: List[Dict[str, Any]]
    release_note: Optional[str]


class LoanApplication(CommonFields, total=False):
    institution_id: str
    governance_authorization_id: str
    pledge_campaign_id: Optional[str]
    purpose: str
    requested_amount_cents: int
    term_months: int
    interest_rate_bps: int
    status: str
    revision_count: int
    giving_basis: Optional[str]
    giving_base_cents: Optional[int]
    net_available_dollars: Optional[int]
    collateral_lending_value_cents: Optional[int]
    max_supportable_principal_cents: Optional[int]
    prepared_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    revision_reason: Optional[str]
    analyst_note: Optional[str]
    referral_note: Optional[str]


class Loan(CommonFields, total=False):
    loan_application_id: str
    principal_cents: int
    term_months: int
    giving_basis: str
    annual_debt_service_cents: int
    interest_reserve_shortfall_cents: int
    servicing_status: str
    risk_posture: str
    disbursed_principal_cents: int
    undrawn_commitment_cents: int
    cancelled_commitment_cents: int
    reserved_draw_cents: int
    retainage_held_cents: int
    retainage_released_cents: int
    outstanding_principal_cents: int
    principal_repaid_cents: int
    forgiven_principal_cents: int
    deferred_payments_count: int


class DrawRequest(CommonFields, total=False):
    loan_id: str
    project_phase: str
    requested_amount_cents: int
    percent_complete: float
    status: str
    approved_amount_cents: Optional[int]
    inspector_note: Optional[str]
    void_reason: Optional[str]
    reinstatement_note: Optional[str]
    disbursement_date: Optional[str]
    completion_pct_at_disbursement: Optional[float]
    retainage_cents: Optional[int]
    interest_reserve_applied_cents: Optional[int]
    inspection_fee_cents: Optional[int]
    net_disbursed_cents: Optional[int]


class Covenant(CommonFields, total=False):
    loan_id: str
    covenant_type: str
    threshold_ratio: float
    test_frequency: str
    status: str
    consecutive_fail_count: int
    test_count: int
    waiver_count: int
    last_test_as_of: Optional[str]
    last_test_numerator_dollars: Optional[int]
    last_test_denominator_dollars: Optional[int]
    last_test_ratio: Optional[float]
    last_test_result: Optional[str]
    cure_evidence_note: Optional[str]
    waiver_note: Optional[str]


class WorkoutPlan(CommonFields, total=False):
    loan_id: str
    predecessor_workout_plan_id: Optional[str]
    option: str
    deferral_months: Optional[int]
    extension_months: Optional[int]
    forgiveness_amount_cents: Optional[int]
    denominational_support_letter: bool
    narrative: str
    status: str
    mission_impact_score: float
    membership_trend_points: int
    giving_trend_points: int
    community_points: int
    denominational_points: int
    approved_by_user_id: Optional[str]
    approval_note: Optional[str]


class UnderwritingSummary(TypedDict, total=False):
    """PRD §3.5 computed read — GET /loan-applications/{id}/underwriting-summary."""

    giving_basis: str
    period_count: int
    audited_period_count: int
    window_period_labels: List[str]
    giving_base_cents: int
    net_available_dollars: int
    membership_trend_pct: float
    collateral_lending_value_cents: int
    max_supportable_principal_cents: int
    requested_amount_cents: int
    binding_cap: str


class CampaignValuation(TypedDict, total=False):
    """PRD §3.3 computed read — GET /pledge-campaigns/{id}/valuation."""

    basis: str
    projected_value_cents: int
    collected_to_date_cents: int
    active_pledged_cents: int
    lapsed_pledged_cents: int
    fulfilled_pledged_cents: int
    total_pledged_cents: int
    goal_cents: int
    status: str
    underperform_threshold_cents: int
    maturity_threshold_cents: int
