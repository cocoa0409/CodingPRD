"""TypedDict shapes for the twelve resource types of the API under test.

Field sets follow the PRD. Eleven of the twelve resource types carry
``updated_at`` and ``version`` in addition to ``id`` and ``created_at``;
``EnrollmentFileRow`` carries only ``id`` and ``created_at`` and therefore
omits both.
"""

from typing import Any, Dict, List, Optional, TypedDict


class VersionedResource(TypedDict):
    """Audit fields carried by eleven of the twelve resource types."""

    id: str
    created_at: str
    updated_at: str
    version: int


class DelegationAgreement(VersionedResource, total=False):
    payer_name: str
    payer_tax_id: str
    delegation_scope: str
    base_pmpm_cents: int
    reconciliation_method: str
    ibnr_method: str
    ibnr_completion_factor_bps: int
    target_claims_pmpm_cents: int
    professional_pool_share_bps: int
    institutional_pool_share_bps: int
    quality_withhold_bps: int
    stop_loss_attachment_cents: int
    reinsurance_recovery_bps: int
    continuity_of_care_days: int
    max_panel_size: int
    status: str
    capitation_posture: str
    accrued_capitation_cents: int
    withheld_balance_cents: int
    forfeited_withhold_cents: int
    total_assigned_members: int


class PhysicianMember(VersionedResource, total=False):
    agreement_id: str
    npi: str
    full_name: str
    specialty: str
    credential_status: str
    panel_status: str
    panel_size: int
    exit_notice_at: Optional[str]
    continuity_of_care_until: Optional[str]
    quality_composite_bps: int
    latest_scorecard_period: Optional[str]


class Enrollee(VersionedResource, total=False):
    agreement_id: str
    external_member_id: str
    age_band: str
    benefit_tier: str
    risk_score_bps: int
    coverage_start_date: str
    coverage_end_date: Optional[str]
    assigned_physician_id: Optional[str]
    gross_pmpm_cents: int
    withhold_cents: int
    net_pmpm_cents: int
    cumulative_paid_claims_cents: int


class MemberAssignment(VersionedResource, total=False):
    enrollee_id: str
    physician_id: str
    pending_to_physician_id: Optional[str]
    effective_date: str
    term_date: Optional[str]
    status: str
    assignment_source: str
    continuity_of_care_until: Optional[str]
    superseded_by_assignment_id: Optional[str]


class EnrollmentFile(VersionedResource, total=False):
    agreement_id: str
    coverage_month: str
    payer_file_reference: str
    received_at: str
    status: str
    row_count: int
    matched_row_count: int
    exception_row_count: int
    claimed_capitation_cents: int


class EnrollmentFileRow(TypedDict, total=False):
    """The single resource type with neither ``updated_at`` nor ``version``."""

    id: str
    created_at: str
    file_id: str
    external_member_id: str
    physician_npi: str
    row_action: str
    claimed_capitation_cents: int
    effective_date: str
    match_status: str


class CapitationRemittance(VersionedResource, total=False):
    file_id: str
    coverage_month: str
    reconciliation_method_used: str
    expected_capitation_cents: int
    claimed_capitation_cents: int
    retro_adjustment_cents: int
    variance_cents: int
    withhold_cents: int
    net_payable_cents: int
    institutional_allocation_cents: int
    professional_allocation_cents: int
    member_month_count_bps: int
    status: str


class RiskPool(VersionedResource, total=False):
    agreement_id: str
    pool_type: str
    pool_year_start: str
    pool_year_end: str
    status: str
    settlement_due_date: str
    funded_cents: int
    member_months_bps: int
    paid_claims_cents: int
    ibnr_reserve_cents: int
    ibnr_method_used: Optional[str]
    stop_loss_recovery_cents: int
    stop_loss_eligible_enrollee_count: int
    loss_ratio_bps: int
    deficit_flag: bool
    surplus_tier: Optional[str]
    raw_surplus_cents: int
    admin_fee_cents: int
    distributable_surplus_cents: int
    shared_savings_pool_cents: int


class DownstreamClaim(VersionedResource, total=False):
    agreement_id: str
    enrollee_id: str
    attributed_physician_id: str
    pool_id: str
    pool_type: str
    downstream_provider_name: str
    billed_cents: int
    service_date: str
    received_date: str
    allowed_cents: Optional[int]
    paid_cents: Optional[int]
    status: str
    denial_reason: Optional[str]
    appeal_count: int


class StopLossRecovery(VersionedResource, total=False):
    pool_id: str
    enrollee_id: str
    attachment_cents: int
    eligible_paid_cents: int
    excess_cents: int
    recovery_cents: int
    status: str
    submitted_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    denial_reason: Optional[str]


class QualityScorecard(VersionedResource, total=False):
    physician_id: str
    measurement_period: str
    hedis_composite_bps: int
    access_score_bps: int
    patient_experience_bps: int
    attributed_member_months: int
    composite_score_bps: int
    withhold_release_bps: int
    status: str


class PoolDistribution(VersionedResource, total=False):
    pool_id: str
    physician_id: str
    composite_score_bps_snapshot: int
    withhold_release_bps_snapshot: int
    panel_member_months_bps: int
    withhold_share_cents: int
    withhold_release_cents: int
    shared_savings_cents: int
    net_distribution_cents: int
    status: str


class SettlementPreview(TypedDict, total=False):
    """The computed, read-only projection returned by the settlement preview."""

    gross_claims_cents: int
    stop_loss_recovery_cents: int
    ibnr_reserve_cents: int
    net_claims_cents: int
    raw_surplus_cents: int
    surplus_ratio_bps: int
    surplus_tier: Optional[str]
    admin_fee_bps: int
    admin_fee_cents: int
    distributable_surplus_cents: int
    shared_savings_pool_cents: int


# Convenience aliases used across the suite.
JsonDict = Dict[str, Any]
JsonList = List[Dict[str, Any]]
