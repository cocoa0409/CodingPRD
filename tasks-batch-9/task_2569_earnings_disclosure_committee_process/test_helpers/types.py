"""Typed shapes of every record the API returns.

Every persisted record carries the same four common properties — ``id``,
``created_at``, ``updated_at`` and ``version`` — so each shape below extends
``CommonRecord``. These are documentation-grade aliases used to keep the test
bodies readable; they are not validated at runtime.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonRecord(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Charter(CommonRecord, total=False):
    name: str
    version_label: str
    min_quorum_count: int
    required_functions: List[str]
    status: str
    superseded_by_charter_id: Optional[str]
    adopted_at_utc: Optional[str]
    active_voting_member_count: int
    covered_functions: List[str]


class CommitteeMember(CommonRecord, total=False):
    charter_id: str
    full_name: str
    function: str
    is_officer: bool
    voting: bool
    status: str


class ReportingCycle(CommonRecord, total=False):
    charter_id: str
    fiscal_period_label: str
    form_type: str
    period_end_date: str
    filer_status: str
    materiality_base_amount: float
    internal_buffer_days: int
    statutory_deadline_utc: str
    internal_target_utc: str
    status: str
    restatement_stage: str
    min_slack_days_calendar: int
    min_slack_days_business: int
    total_assigned_scope_weight: float
    certification_coverage_pct: float
    open_material_event_count: int
    unresolved_deficiency_weight: float


class ReadinessDashboard(TypedDict, total=False):
    cycle_id: str
    cycle_status: str
    restatement_stage: str
    statutory_deadline_utc: str
    internal_target_utc: str
    min_slack_days_calendar: int
    min_slack_days_business: int
    total_assigned_scope_weight: float
    certification_coverage_pct: float
    open_material_event_count: int
    unresolved_deficiency_weight: float
    missing_milestone_kinds: List[str]
    unsigned_cert_types: List[str]
    blocking_error_ids: List[str]
    filing_ready_eligible: bool


class Milestone(CommonRecord, total=False):
    cycle_id: str
    kind: str
    planned_start_utc: str
    planned_end_utc: str
    actual_start_utc: Optional[str]
    actual_end_utc: Optional[str]
    status: str
    slack_calendar_days: int
    slack_business_days: int


class SubCertificationRequest(CommonRecord, total=False):
    cycle_id: str
    member_id: str
    scope_area: str
    due_utc: str
    prep_window_start_utc: str
    scope_weight: float
    status: str
    exception_severity: str
    exception_note: Optional[str]
    submitted_utc: Optional[str]


class OfficerCertification(CommonRecord, total=False):
    cycle_id: str
    officer_member_id: str
    cert_type: str
    status: str
    attestation_text: Optional[str]
    signed_utc: Optional[str]
    coverage_pct_at_signing: Optional[float]


class DraftDocument(CommonRecord, total=False):
    cycle_id: str
    doc_type: str
    title: str
    author_member_id: str
    safe_harbor_present: bool
    status: str
    revision_round: int
    change_note: Optional[str]
    tie_out_status: str
    tie_out_total_variance_bp: int
    tie_out_tier_multiplier: float
    measure_gate_status: str
    qa_gate_status: str


class TieOutItem(CommonRecord, total=False):
    document_id: str
    line_label: str
    reported_value: float
    source_record_value: float
    tolerance_bp: int
    preparer_member_id: str
    reviewer_member_id: Optional[str]
    review_decision: Optional[str]
    raw_variance_bp: int
    effective_tolerance_bp: int
    status: str


class AdjustedMeasure(CommonRecord, total=False):
    document_id: str
    measure_label: str
    adjusted_value: float
    comparable_gaap_value: float
    reconciliation_items: List[Dict[str, Any]]
    adjusted_prominence_index: int
    gaap_prominence_index: int
    reconciliation_sum: Optional[float]
    reconciliation_gap: Optional[float]
    prominence_ok: Optional[bool]
    status: str


class QuestionItem(CommonRecord, total=False):
    script_document_id: str
    question_text: str
    topic: str
    risk_tier: str
    requires_safe_harbor: bool
    status: str
    clearance_note: Optional[str]


class MaterialEvent(CommonRecord, total=False):
    cycle_id: str
    category: str
    occurred_utc: str
    discovered_utc: str
    magnitude_amount: float
    description: str
    severity_score: float
    assessment_status: str
    determination_note: Optional[str]
    linked_document_id: Optional[str]
    current_report_deadline_utc: Optional[str]


class Filing(CommonRecord, total=False):
    cycle_id: str
    document_id: str
    amends_filing_id: Optional[str]
    form_type: str
    sequence_number: int
    accession_label: str
    filed_utc: str
    late_flag: bool
    status: str


class PostFilingCorrection(CommonRecord, total=False):
    filing_id: str
    description: str
    error_amount: float
    current_period_pretax_income: float
    prior_period_pretax_income: float
    cumulative_prior_uncorrected_amount: float
    method: Optional[str]
    materiality_pct: Optional[float]
    classification: Optional[str]
    status: str


class ControlDeficiency(CommonRecord, total=False):
    correction_id: str
    likelihood_pct: float
    magnitude_amount: float
    compensating_control_present: bool
    severity_score: float
    severity: str
    deficiency_weight: float
    remediation_note: Optional[str]
    status: str
