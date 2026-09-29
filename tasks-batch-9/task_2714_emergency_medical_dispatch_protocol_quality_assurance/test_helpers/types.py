"""TypedDict shapes for every entity the API returns.

Common fields (id, created_at, updated_at, version) are carried by every entity
except the score sheet, which the PRD declares as an immutable append-only
record carrying only id and created_at.
"""

from typing import Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class AuditProgram(CommonFields):
    name: str
    accreditation_body: str
    target_compliance_pct: float
    watch_floor_pct: float
    high_risk_target_pct: float
    review_deadline_days: int
    rebuttal_window_days: int
    max_rebuttal_rounds: int
    escalated_sample_floor: int
    hours_owed_restriction_threshold: float
    accreditation_status: str
    latest_compliance_pct: Optional[float]
    submitted_report_count: int
    sentinel_event_count: int


class ProtocolVersion(CommonFields):
    program_id: str
    protocol_family: str
    version_label: str
    effective_from: str
    effective_to: Optional[str]
    case_entry_weight: float
    key_questions_weight: float
    pre_arrival_weight: float
    final_coding_weight: float
    status: str
    approved_by_user_id: Optional[str]
    activated_at: Optional[str]
    superseded_at: Optional[str]


class ProtocolRollout(CommonFields):
    protocol_version_id: str
    scheduled_golive_at: str
    target_dispatcher_count: int
    required_training_hours: float
    trained_dispatcher_count: int
    training_status: str
    golive_status: str
    went_live_at: Optional[str]


class Dispatcher(CommonFields):
    program_id: str
    employee_code: str
    full_name: str
    hire_date: Optional[str]
    certified_protocol_version_id: Optional[str]
    certification_status: str
    certified_at: Optional[str]
    reviewed_case_count: int
    compliance_points_total: float
    compliance_pct: Optional[float]
    compliance_posture: str
    remediation_hours_owed: float
    sentinel_event_count: int
    dispatch_privilege: str


class CallRecord(CommonFields):
    dispatcher_id: str
    call_reference: str
    call_type: str
    received_at: str
    dispatched_determinant_code: str
    dispatched_priority_rank: int
    response_mode_assigned: str
    resource_assigned: str
    cardiac_arrest_confirmed: bool
    bystander_cpr_in_progress: bool
    status: str


class SamplingPeriod(CommonFields):
    program_id: str
    call_type: str
    period_start: str
    period_end: str
    sampling_mode: str
    target_sample_count: int
    selected_review_count: int
    finalized_review_count: int
    status: str
    closed_at: Optional[str]
    locked_at: Optional[str]


class Review(CommonFields):
    sampling_period_id: str
    call_record_id: str
    dispatcher_id: str
    protocol_version_id: str
    selection_mode: str
    selection_reason: str
    high_risk: bool
    status: str
    current_sheet_round: int
    provisional_composite_score: Optional[float]
    pre_penalty_composite_score: Optional[float]
    determinant_accuracy: Optional[str]
    penalty_points: Optional[float]
    final_composite_score: Optional[float]
    compliant: Optional[bool]
    rebuttal_round_count: int
    scored_at: Optional[str]
    finalized_at: Optional[str]
    voided_at: Optional[str]
    void_reason: Optional[str]


class ScoreSheet(TypedDict):
    """Append-only sheet: the PRD gives it only id and created_at."""

    id: str
    created_at: str
    review_id: str
    sheet_round: int
    case_entry_points_earned: int
    case_entry_points_possible: int
    key_questions_points_earned: int
    key_questions_points_possible: int
    pre_arrival_points_earned: int
    pre_arrival_points_possible: int
    final_coding_points_earned: int
    final_coding_points_possible: int
    case_entry_pct: float
    key_questions_pct: float
    pre_arrival_pct: float
    final_coding_pct: float
    provisional_composite_score: float
    reviewer_determinant_code: str
    reviewer_priority_rank: int
    reviewer_response_mode: str
    reviewer_resource: str
    response_mode_deviation: bool
    resource_deviation: bool
    determinant_accuracy: str
    reviewer_notes: Optional[str]
    submitted_by_user_id: str


class Rebuttal(CommonFields):
    review_id: str
    round_index: int
    grounds_category: str
    narrative: str
    status: str
    submitted_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_notes: Optional[str]


class HighRiskCaseReview(CommonFields):
    review_id: str
    outcome_category: str
    cardiac_arrest_recognized: Optional[bool]
    recognition_time_sec: Optional[int]
    time_to_first_compression_sec: Optional[int]
    dacpr_instructions_delivered: Optional[bool]
    compressions_coached: Optional[bool]
    compression_compliant: Optional[bool]
    dacpr_index: Optional[float]
    dacpr_pass: Optional[bool]
    classification: Optional[str]
    status: str
    signed_off_by_user_id: Optional[str]
    signed_off_at: Optional[str]
    director_notes: Optional[str]


class CoachingPlan(CommonFields):
    dispatcher_id: str
    source_review_id: Optional[str]
    origin: str
    severity: str
    severity_rank: int
    focus_area: str
    required_hours: float
    credited_hours: float
    status: str
    closure_reason: Optional[str]
    due_at: Optional[str]
    verified_at: Optional[str]


class RetrainingSession(CommonFields):
    coaching_plan_id: str
    protocol_version_id: str
    starts_at: str
    ends_at: str
    modality: str
    duration_hours: float
    status: str
    attendance_confirmed: Optional[bool]
    cancel_reason: Optional[str]
    completed_at: Optional[str]


class AccreditationReport(CommonFields):
    program_id: str
    window_start: str
    window_end: str
    variant: str
    review_count: int
    compliant_review_count: int
    dispatcher_count: int
    compliance_pct: Optional[float]
    high_risk_review_count: int
    high_risk_pass_count: int
    high_risk_compliance_pct: Optional[float]
    threshold_met: bool
    status: str
    submitted_to: Optional[str]
    submitted_at: Optional[str]
