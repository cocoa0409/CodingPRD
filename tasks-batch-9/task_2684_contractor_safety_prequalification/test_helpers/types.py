"""Response shapes for the persisted entities.

`Worker` and `WorkerQualification` are immutable and therefore expose only
`id` and `created_at`; every other entity also carries `updated_at` and
`version`.
"""

from typing import Any, Dict, List, Optional, TypedDict


class ImmutableRecord(TypedDict):
    id: str
    created_at: str


class VersionedRecord(ImmutableRecord):
    updated_at: str
    version: int


class Client(VersionedRecord, total=False):
    legal_name: str
    industry_code: str
    grading_policy: str
    max_trir: float
    max_dart_rate: float
    max_emr: float
    max_citation_points: int
    weight_trir: float
    weight_dart: float
    weight_emr: float
    weight_citation: float
    conditional_band_pct: int
    requalification_interval_months: int
    audit_sample_rate_pct: int
    cascade_depth_limit: int
    required_coverage_types: List[str]


class Site(VersionedRecord, total=False):
    client_id: str
    site_code: str
    required_hazard_classes: List[str]
    min_grade: str
    granted_worker_count: int
    access_gate_status: str


class Contractor(VersionedRecord, total=False):
    legal_name: str
    scope_of_work: List[str]
    hazard_profile: List[str]
    employee_count: int
    status: str
    base_hazard_tier: int
    incident_review_flag: bool
    open_severe_incident_count: int
    open_deficiency_count: int
    verified_coverage_types: List[str]


class Worker(ImmutableRecord, total=False):
    contractor_id: str
    full_name: str
    employee_ref: str
    trade_code: str


class WorkerQualification(ImmutableRecord, total=False):
    worker_id: str
    qualification_code: str
    issued_date: str
    expiration_date: str
    training_provider: str
    evidence_ref: str


class Prequalification(VersionedRecord, total=False):
    contractor_id: str
    client_id: str
    cycle_year: int
    status: str
    statistics_verification_status: str
    document_review_status: str
    audit_state: str
    provisional_composite_score: Optional[float]
    final_composite_score: Optional[float]
    grade: Optional[str]
    effective_thresholds: Optional[Dict[str, Any]]
    deficiency_codes: List[str]
    graded_at: Optional[str]
    graded_by_user_id: Optional[str]
    expires_at: Optional[str]
    conditional_expires_at: Optional[str]
    audit_selected_at: Optional[str]
    audit_findings_count: int


class SafetyStatistic(VersionedRecord, total=False):
    prequalification_id: str
    reporting_year: int
    hours_worked: int
    recordable_incidents: int
    dart_cases: int
    fatalities: int
    emr: float
    citation_count_willful: int
    citation_count_serious: int
    citation_count_other: int
    source_document_ref: str
    trir: float
    dart_rate: float
    citation_points: int
    verification_status: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]


class WrittenProgram(VersionedRecord, total=False):
    prequalification_id: str
    program_type: str
    revision_date: str
    document_ref: str
    review_status: str
    is_required: bool
    reviewer_note: Optional[str]
    reviewed_by_user_id: Optional[str]


class ImprovementPlan(VersionedRecord, total=False):
    prequalification_id: str
    due_date: str
    milestone_count: int
    deficiency_codes: List[str]
    status: str
    evidence_ref: Optional[str]
    decided_by_user_id: Optional[str]
    closed_at: Optional[str]


class InsuranceCertificate(VersionedRecord, total=False):
    contractor_id: str
    coverage_type: str
    carrier_name: str
    each_occurrence_limit: int
    aggregate_limit: int
    effective_date: str
    expiration_date: str
    additional_insured: bool
    waiver_of_subrogation: bool
    verification_status: str
    lifecycle_status: str
    available_aggregate: int
    verified_by_user_id: Optional[str]


class SiteAccessGrant(VersionedRecord, total=False):
    worker_id: str
    site_id: str
    prequalification_id: str
    status: str
    granted_at: str
    expires_at: str
    qualification_snapshot: List[str]
    revocation_reason: Optional[str]
    revoked_at: Optional[str]


class IncidentReport(VersionedRecord, total=False):
    contractor_id: str
    site_id: str
    occurred_at: str
    severity: str
    osha_reportable: bool
    description: str
    review_status: str
    findings_note: Optional[str]
    closed_at: Optional[str]
    triggered_suspension_count: int


class Variance(VersionedRecord, total=False):
    prequalification_id: str
    requirement_code: str
    requested_value: float
    justification: str
    status: str
    expires_at: Optional[str]
    decided_by_user_id: Optional[str]


class SubcontractorLink(VersionedRecord, total=False):
    parent_contractor_id: str
    child_contractor_id: str
    prequalification_id: str
    scope_of_work: List[str]
    depth: int
    status: str
    flow_down_status: str


class RequalificationRunResult(TypedDict, total=False):
    expired_count: int
    expired_prequalification_ids: List[str]
    conditional_rejected_count: int
    conditional_rejected_prequalification_ids: List[str]
    overdue_plan_count: int
    lapsed_certificate_count: int


class AuditSamplingRunResult(TypedDict, total=False):
    selected_count: int
    selected_prequalification_ids: List[str]


class Scorecard(TypedDict, total=False):
    prequalification_id: str
    contractor_id: str
    client_id: str
    status: str
    grade: Optional[str]
    provisional_composite_score: Optional[float]
    final_composite_score: Optional[float]
    governing_reporting_year: Optional[int]
    hazard_tier: Optional[int]
    normalized_metrics: Optional[Dict[str, Any]]
    effective_thresholds: Optional[Dict[str, Any]]
    deficiency_codes: List[str]
    conditional_expires_at: Optional[str]
    expires_at: Optional[str]
