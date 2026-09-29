"""TypedDict shapes for every resource the API returns.

Most rows carry `id`, `created_at`, `updated_at` and `version`. Evidence items
and change-log entries are historical facts and carry only `id` and
`created_at`, so their shapes deliberately omit the other two.
"""

from typing import Any, Dict, List, Optional, TypedDict


class ResponseMeta(TypedDict, total=False):
    api_request_id: str
    api_request_timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class ErrorPayload(TypedDict):
    error_id: str
    message: str


class Assessor(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    certification_expires_at: str
    qa_qualified: bool
    status: str
    certification_status: str
    lead_engagement_count: int
    created_at: str
    updated_at: str
    version: int


class AsvVendor(TypedDict, total=False):
    id: str
    name: str
    approval_expires_at: str
    approval_status: str
    effective_approval: str
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict, total=False):
    id: str
    client_legal_name: str
    merchant_level: str
    assessment_year: int
    acquirer_name: str
    fieldwork_start_date: str
    fieldwork_end_date: str
    approved_budget_amount: float
    lead_assessor_id: str
    qa_reviewer_id: Optional[str]
    status: str
    posture: str
    scope_locked: bool
    attested_at: Optional[str]
    reassessment_due_date: Optional[str]
    next_assessment_start_date: Optional[str]
    active_sampling_plan_id: Optional[str]
    active_plan_stale: bool
    cde_component_count: int
    connected_component_count: int
    out_of_scope_component_count: int
    in_scope_component_count: int
    total_component_count: int
    unvalidated_segment_count: int
    open_gap_count: int
    unmet_requirement_count: int
    accepted_ccw_count: int
    applicable_requirement_count: int
    estimated_hours: int
    assessment_fee_total: float
    as_found_compliance_percentage: float
    as_attested_compliance_percentage: float
    quarterly_scan_compliant: bool
    scope_affecting_change_count: int
    reassessment_required: bool
    created_at: str
    updated_at: str
    version: int


class EngagementSummary(TypedDict, total=False):
    engagement_id: str
    posture: str
    cde_component_count: int
    connected_component_count: int
    out_of_scope_component_count: int
    total_component_count: int
    open_gap_count: int
    unvalidated_segment_count: int
    accepted_ccw_count: int
    estimated_hours: int
    assessment_fee_total: float
    as_found_compliance_percentage: float
    as_attested_compliance_percentage: float
    quarterly_scan_compliant: bool
    scope_affecting_change_count: int
    reassessment_required: bool


class NetworkSegment(TypedDict, total=False):
    id: str
    engagement_id: str
    name: str
    segment_class: str
    effective_class: str
    parent_segment_id: Optional[str]
    segmentation_status: str
    test_method: Optional[str]
    planned_date: Optional[str]
    revalidation_round: int
    last_validated_at: Optional[str]
    scope_expanded_by_failure: bool
    created_at: str
    updated_at: str
    version: int


class SystemComponent(TypedDict, total=False):
    id: str
    engagement_id: str
    segment_id: str
    hostname: str
    component_type: str
    function_class: str
    stores_chd: bool
    facility_name: str
    facility_type: str
    declared_scope_class: str
    scope_class: str
    in_sample: bool
    sampling_stratum: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SamplingPlan(TypedDict, total=False):
    id: str
    engagement_id: str
    plan_variant: str
    justification_text: str
    status: str
    eligible_component_count: int
    component_sample_size: int
    stratum_allocations: Dict[str, int]
    coverage_ratio: float
    facility_population_count: int
    facility_sample_size: int
    sampled_facility_names: List[str]
    estimated_hours: int
    base_amount: float
    surcharge_amount: float
    subtotal_amount: float
    volume_discount_rate: float
    discount_amount: float
    assessment_fee_total: float
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RequirementAssessment(TypedDict, total=False):
    id: str
    engagement_id: str
    requirement_ref: str
    requirement_family: str
    testing_procedure_count: int
    applicability: str
    test_status: str
    remediation_status: str
    risk_points: int
    conclusion_rationale: Optional[str]
    reopen_count: int
    evidence_item_count: int
    evidence_type_coverage: List[str]
    evidence_completeness: bool
    testing_assessor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    """Evidence is append-only: it carries id and created_at and nothing else."""

    id: str
    requirement_assessment_id: str
    engagement_id: str
    evidence_type: str
    procedure_ref: str
    sufficiency: str
    component_id: Optional[str]
    interviewee_name: Optional[str]
    interviewee_title: Optional[str]
    note: Optional[str]
    collector_assessor_id: str
    collected_at: str
    created_at: str


class CompensatingControlWorksheet(TypedDict, total=False):
    id: str
    requirement_assessment_id: str
    engagement_id: str
    constraint_text: str
    objective_text: str
    identified_risk_text: str
    control_refs: List[str]
    monitoring_interval_days: int
    validation_text: str
    maintenance_text: str
    status: str
    control_depth_points: int
    monitoring_factor: int
    risk_offset_points: int
    rigor_score: float
    thin_control_capped: bool
    reviewer_note: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationItem(TypedDict, total=False):
    id: str
    engagement_id: str
    requirement_assessment_id: Optional[str]
    source: str
    source_scan_finding_id: Optional[str]
    gap_description: str
    severity: str
    status: str
    owner_reference: Optional[str]
    due_date: Optional[str]
    retest_count: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RocReport(TypedDict, total=False):
    id: str
    engagement_id: str
    roc_version_label: str
    status: str
    applicable_requirement_count: int
    in_place_count: int
    ccw_covered_count: int
    not_in_place_count: int
    as_found_compliance_percentage: float
    as_attested_compliance_percentage: float
    compliance_result: str
    revision_count: int
    qa_decision_note: Optional[str]
    attestation_signature_name: Optional[str]
    attesting_assessor_id: Optional[str]
    attested_at: Optional[str]
    submitted_to: Optional[str]
    submission_reference: Optional[str]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScanCycle(TypedDict, total=False):
    id: str
    engagement_id: str
    quarter_label: str
    asv_vendor_id: str
    window_start: str
    window_end: str
    status: str
    scan_completed_at: Optional[str]
    attestation_of_scan_compliance: bool
    raw_high_finding_count: int
    accepted_false_positive_count: int
    effective_high_finding_count: int
    open_dispute_count: int
    created_at: str
    updated_at: str
    version: int


class ScanFinding(TypedDict, total=False):
    id: str
    scan_cycle_id: str
    component_id: str
    plugin_reference: str
    cvss_score: float
    severity_class: str
    dispute_status: str
    dispute_rationale: Optional[str]
    decision_note: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeLogEntry(TypedDict, total=False):
    """Change-log entries are historical: id and created_at only."""

    id: str
    engagement_id: str
    change_type: str
    description: str
    affects_scope: bool
    component_id: Optional[str]
    recorded_at: str
    triggers_reassessment: bool
    created_at: str


class ClockState(TypedDict):
    current_utc: str


JsonDict = Dict[str, Any]
