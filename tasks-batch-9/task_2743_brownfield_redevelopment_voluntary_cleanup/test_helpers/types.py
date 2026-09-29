"""
Shape declarations for the brownfield voluntary-cleanup API.

Two things live here. The role names exactly as the PRD spells them, split by whether
the role's ``X-User-ID`` is compared against a persisted row; and one ``TypedDict`` per
entity naming the fields the PRD says a read of that entity exposes.

The ``ContaminantFinding`` shape is deliberately narrower than the rest: the PRD says
that entity carries only ``id`` and ``created_at`` and has no update endpoint, so it
has neither ``updated_at`` nor ``version``.
"""

from typing import Any, Dict, List, Optional, TypedDict

Json = Dict[str, Any]
JsonList = List[Json]
Headers = Dict[str, str]

# ─── Roles ────────────────────────────────────────────────────────────────────

ROLE_REDEVELOPER = "Redeveloper"
ROLE_ENVIRONMENTAL_CONSULTANT = "EnvironmentalConsultant"
ROLE_INSURER = "Insurer"
ROLE_STATE_AGENCY_REVIEWER = "StateAgencyReviewer"
ROLE_LENDER = "Lender"
ROLE_PROGRAM_ADMIN = "ProgramAdmin"

ALL_ROLES = (
    ROLE_REDEVELOPER,
    ROLE_ENVIRONMENTAL_CONSULTANT,
    ROLE_INSURER,
    ROLE_STATE_AGENCY_REVIEWER,
    ROLE_LENDER,
    ROLE_PROGRAM_ADMIN,
)

# Roles whose X-User-ID must be the id of a real Party row.
ENTITY_BACKED_ROLES = (
    ROLE_REDEVELOPER,
    ROLE_ENVIRONMENTAL_CONSULTANT,
    ROLE_INSURER,
)

# Roles whose X-User-ID is an opaque operator identifier the server never resolves
# to a Party row.
OPAQUE_ROLES = (
    ROLE_STATE_AGENCY_REVIEWER,
    ROLE_LENDER,
    ROLE_PROGRAM_ADMIN,
)


# ─── Common properties ────────────────────────────────────────────────────────


class _Versioned(TypedDict):
    """The four properties every entity but ContaminantFinding carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


# ─── Entities ─────────────────────────────────────────────────────────────────


class Party(_Versioned, total=False):
    legal_name: str
    party_type: str
    state_code: str
    licence_number: Optional[str]


class Laboratory(_Versioned, total=False):
    lab_name: str
    certification_code: str
    concurrent_capacity: int


class Site(_Versioned, total=False):
    owner_party_id: str
    site_name: str
    county_code: str
    acreage: float
    intended_reuse: str
    institutional_control_committed: bool
    planned_acquisition_date: str
    acquisition_status: str
    acquisition_date: Optional[str]
    delineation_status: str
    cleanup_posture: str
    impaired_control_count: int


class AssessmentPhase(_Versioned, total=False):
    site_id: str
    consultant_party_id: str
    supersedes_phase_id: Optional[str]
    phase_type: str
    field_start_date: str
    field_end_date: str
    aai_report_date: Optional[str]
    delineation_confidence: str
    delineation_complete: bool
    status: str
    review_round: int
    findings_count: int
    max_exceedance_factor: float
    submitted_at: Optional[str]
    reviewed_by_user_id: Optional[str]


class ContaminantFinding(TypedDict, total=False):
    """Immutable analytical record: only ``id`` and ``created_at`` accompany it."""

    id: str
    created_at: str
    assessment_phase_id: str
    contaminant_code: str
    media: str
    sample_location_code: str
    max_concentration_ugl: float
    screening_level_ugl: float
    delineated: bool
    exceedance_factor: float


class CleanupGoal(_Versioned, total=False):
    site_id: str
    contaminant_code: str
    media: str
    screening_level_ugl: float
    basis: str
    control_credit_type: Optional[str]
    contaminant_count_in_media: int
    goal_ugl: float
    cumulative_cap_applied: bool
    attainment_status: str
    compliant_streak: int


class LiabilityProtection(_Versioned, total=False):
    site_id: str
    inquiry_state: str
    obligation_state: str
    bfpp_status: str
    aai_phase_id: Optional[str]
    aai_report_date: Optional[str]
    aai_expires_on: Optional[str]
    obligations_total_weight: int
    current_weight: int
    satisfied_weight: int
    at_risk_weight: int
    lapsed_weight: int
    compliance_pct: float


class ContinuingObligation(_Versioned, total=False):
    liability_protection_id: str
    obligation_category: str
    description: str
    due_date: str
    recurrence_days: int
    imposed_by_user_id: str
    status: str
    certified_at: Optional[str]
    certification_count: int
    prior_due_date: Optional[str]


class VcpEnrollment(_Versioned, total=False):
    site_id: str
    program_track: str
    applicant_statement: str
    status: str
    enrolled_on: Optional[str]
    eligibility_decided_by_user_id: Optional[str]
    completion_requested_at: Optional[str]
    reverted_completion_count: int


class RemedialActionPlan(_Versioned, total=False):
    vcp_enrollment_id: str
    site_id: str
    remedy_narrative: str
    basis_assessment_phase_id: str
    years_to_construction_start: int
    cost_lines: JsonList
    direct_cost_cents: int
    escalation_cents: int
    contingency_pct: float
    contingency_cents: int
    oversight_cents: int
    total_estimate_cents: int
    total_funding_need_cents: int
    status: str
    technical_review_state: str
    public_comment_state: str
    public_comment_count: int
    revision_round: int
    pinned_cleanup_goal_versions: JsonList
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]


class CostCapPolicy(_Versioned, total=False):
    remedial_action_plan_id: str
    insurer_party_id: str
    policy_reference: str
    term_years: int
    underwriting_estimate_cents: int
    attachment_point_cents: int
    buffer_layer_cents: int
    limit_cents: int
    rate_applied: float
    premium_cents: int
    status: str
    bound_at: Optional[str]


class SiteControl(_Versioned, total=False):
    site_id: str
    remedial_action_plan_id: str
    control_type: str
    control_class: str
    sub_area_code: str
    coverage_from: str
    coverage_to: str
    inspection_interval_days: int
    status: str
    last_certified_on: Optional[str]
    next_certification_due_on: str
    impaired_since: Optional[str]
    impairment_count: int


class FundingAward(_Versioned, total=False):
    site_id: str
    program_code: str
    funding_kind: str
    program_priority: int
    max_award_cents: int
    max_share_pct: float
    match_requirement_pct: float
    eligible_cost_categories: List[str]
    eligibility_documents: List[str]
    status: str
    decided_by_user_id: Optional[str]
    allocated_cents: int


class NoFurtherActionLetter(_Versioned, total=False):
    site_id: str
    vcp_enrollment_id: str
    requested_scope: str
    status: str
    issued_on: Optional[str]
    issued_by_user_id: Optional[str]
    controls_certified_count: int
    accepted_by_lender_user_id: Optional[str]
    lender_reference: Optional[str]
    revocation_reason: Optional[str]
    reissue_count: int


class MonitoringEvent(_Versioned, total=False):
    site_id: str
    laboratory_id: str
    cleanup_goal_id: str
    site_control_id: Optional[str]
    event_type: str
    monitoring_period_code: str
    sample_date: str
    window_start: str
    window_end: str
    status: str
    result_value_ugl: Optional[float]
    result_status: str
    control_condition: Optional[str]


class FundingAssembly(TypedDict, total=False):
    """Computed read; not a persisted row, so it carries no common properties."""

    site_id: str
    remedial_action_plan_id: Optional[str]
    total_funding_need_cents: int
    allocations: JsonList
    unfunded_gap_cents: int
    local_match_required_cents: int


class ComplianceSweepResult(TypedDict, total=False):
    """The six counters the ops-run checkpoint reports instead of an entity."""

    as_of_date: str
    swept_obligation_count: int
    at_risk_count: int
    lapsed_count: int
    stale_inquiry_count: int
    forfeited_protection_count: int
    frozen_site_count: int
