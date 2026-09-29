"""TypedDict shapes for the payloads described in PRD §3.

Two resources are deliberately write-once and carry **only** `id` and
`created_at`: the ApplicabilityDetermination and the PublicComment. Their
TypedDicts therefore omit `updated_at` and `version` entirely -- every other
resource carries the full common-field quartet.

All shapes are `total=False` so that a test can compare against the subset of
keys it actually cares about without the type checker complaining.
"""

from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Envelope (PRD §2.3)
# ---------------------------------------------------------------------------


class ResponseMeta(TypedDict, total=False):
    api_request_id: str
    api_request_timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class ErrorData(TypedDict, total=False):
    error_id: str
    message: str


class Envelope(TypedDict, total=False):
    meta: ResponseMeta
    response_type: str
    data: Any


class ClockState(TypedDict, total=False):
    current_utc: str


# ---------------------------------------------------------------------------
# Screening (PRD §3.1)
# ---------------------------------------------------------------------------


class ScreeningArea(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    area_code: str
    county: str
    population: int
    limited_english_pct: float
    required_translation_languages: List[str]
    translation_required: bool
    baseline_load_tpy: float
    permitted_load_tpy: float
    pollution_component_statewide: float
    health_component_statewide: float
    demographic_component_statewide: float
    ej_screen_score_statewide: float
    ej_screen_score_county: float
    designation: str
    data_status: str
    active_indicator_count: int
    enforcement_burden_points: int
    open_plan_count: int
    open_complaint_count: int


class BurdenIndicator(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    screening_area_id: str
    indicator_code: str
    category: str
    raw_value: float
    statewide_percentile: float
    county_percentile: float
    vintage_year: int
    status: str
    superseded_indicator_id: Optional[str]
    area_version_after: int


# ---------------------------------------------------------------------------
# Facilities and applications (PRD §3.2)
# ---------------------------------------------------------------------------


class Facility(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    screening_area_id: str
    name: str
    facility_type: str
    distance_to_area_centroid_m: int
    existing_load_tpy: float
    compliance_status: str
    confirmed_violation_count: int


class PermitApplication(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    facility_id: str
    permit_type: str
    proposed_emissions_tpy: float
    proposed_operating_hours_per_year: int
    prior_application_id: Optional[str]
    status: str
    review_track: str
    revision_round: int
    screening_stale_flag: bool
    pre_mitigation_index: float
    total_mitigation_credit_tpy: float
    residual_impact_index: float
    approved_net_emissions_tpy: float


class ApplicabilityDetermination(TypedDict, total=False):
    """Write-once: carries only `id` and `created_at` from the common fields."""

    id: str
    created_at: str
    permit_application_id: str
    result: str
    trigger_codes: List[str]
    area_designation_snapshot: str
    ej_screen_score_snapshot: float
    revision_round: int
    determined_by_user_id: str
    application_version_after: int


# ---------------------------------------------------------------------------
# Cumulative impact assessments (PRD §3.3)
# ---------------------------------------------------------------------------


class CumulativeImpactAssessment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    permit_application_id: str
    method: str
    status: str
    baseline_burden_score: float
    proposed_increment_pct: float
    dispersion_factor: Optional[float]
    receptor_distance_m: Optional[int]
    exposure_factor: float
    cumulative_impact_index: float
    disproportionate_flag: bool
    data_confidence: str
    author_user_id: str
    qa_user_id: Optional[str]
    note: Optional[str]
    application_version_after: int


# ---------------------------------------------------------------------------
# Participation plans, meetings, comments (PRD §3.4, §3.5)
# ---------------------------------------------------------------------------


class ParticipationPlan(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    permit_application_id: str
    status: str
    required_comment_days: int
    granted_extension_days: int
    comment_start_date: Optional[str]
    comment_end_date: Optional[str]
    translated_languages: List[str]
    materials_translated: bool
    meeting_count: int
    comment_count: int
    adequacy_status: str
    deficiency_codes: List[str]


class Venue(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    address: str
    capacity: int
    transit_accessible: bool
    ada_accessible: bool
    interpretation_capable: bool
    status: str
    booked_meeting_count: int


class PublicMeeting(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    participation_plan_id: str
    venue_id: str
    starts_at: str
    ends_at: str
    interpretation_languages: List[str]
    accessibility_verified: bool
    status: str


class PublicComment(TypedDict, total=False):
    """Write-once: carries only `id` and `created_at` from the common fields."""

    id: str
    created_at: str
    participation_plan_id: str
    submitter_name: str
    language: str
    body: str
    requires_response: bool
    in_required_language: bool


# ---------------------------------------------------------------------------
# Conditions and decisions (PRD §3.6, §3.7)
# ---------------------------------------------------------------------------


class PermitCondition(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    permit_application_id: str
    condition_type: str
    reduction_tpy: float
    enforceable: bool
    monitoring_frequency: Optional[str]
    benefit_value_usd: Optional[float]
    credit_tpy: float
    status: str
    application_version_after: int


class PermitDecision(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    permit_application_id: str
    disposition: str
    denial_basis: Optional[str]
    status: str
    approved_net_emissions_tpy: float
    residual_index_at_decision: float
    community_benefit_base_usd: Optional[float]
    community_benefit_surcharge_usd: Optional[float]
    community_benefit_total_usd: Optional[float]
    decided_by_user_id: str
    reason: Optional[str]


# ---------------------------------------------------------------------------
# Complaints and inspections (PRD §3.8)
# ---------------------------------------------------------------------------


class CommunityComplaint(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    screening_area_id: str
    facility_id: Optional[str]
    complaint_type: str
    severity: str
    description: str
    submitter_language: str
    status: str
    priority_score: float
    priority_tier: str
    reopen_count: int
    dismissal_reason: Optional[str]
    resolution: Optional[str]


class Inspection(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    community_complaint_id: str
    facility_id: Optional[str]
    inspector_user_id: str
    scheduled_date: str
    status: str
    finding: Optional[str]
    notes: Optional[str]
    priority_score_at_assignment: float


# ---------------------------------------------------------------------------
# Program evaluation (PRD §3.9)
# ---------------------------------------------------------------------------


class ProgramEvaluation(TypedDict, total=False):
    basis: str
    period_start: str
    period_end: str
    total_decided: int
    issued_count: int
    denied_count: int
    denial_rate: float
    mean_residual_index: float
    total_mitigation_credit_tpy: float
    total_community_benefit_usd: float
    mean_comment_days: float


# ---------------------------------------------------------------------------
# Composite fixture payloads
# ---------------------------------------------------------------------------

# Fixtures hand tests a plain dict of ids and version counters rather than a
# rigid object, so that each test can pick out only the handles it needs.
FixtureState = Dict[str, Any]
