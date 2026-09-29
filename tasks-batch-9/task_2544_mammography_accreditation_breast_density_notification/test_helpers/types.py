"""Typed shapes for every entity the service exposes.

These are documentation-grade `TypedDict`s: they name the fields a response is
expected to carry so that a test reads as a contract rather than as a bag of
string keys.  Every declaration is ``total=False`` because the tests assert on
individual fields, never on exhaustive presence.

Note the deliberate asymmetry the PRD calls out: a `QualificationCredit`
carries only `id` and `created_at`, with no `updated_at` and no `version`,
while all thirteen other entities carry the full identity/timestamp set.
"""

from typing import Any, Dict, List, Optional, TypedDict

# Identity and timestamp fields carried by thirteen of the fourteen entities.
COMMON_FIELDS = ("id", "created_at", "updated_at", "version")

# The one exception.
CREDIT_ONLY_FIELDS = ("id", "created_at")


class StatePolicy(TypedDict, total=False):
    id: str
    state_code: str
    density_notice_rule: str
    lay_summary_max_reading_grade: int
    lay_summary_deadline_days: int
    supplemental_coverage_mandate: str
    required_notice_codes: List[str]
    supplemental_cost_share_waiver_threshold_cents: int
    followup_grace_days: int
    report_turnaround_days: int
    urgent_report_turnaround_days: int
    ce_grace_days: int
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict, total=False):
    id: str
    name: str
    state_policy_id: str
    accreditation_body: str
    supplemental_concurrent_capacity: int
    total_funded_cents: int
    prepaid_credit_cents: int
    fee_held_cents: int
    fee_consumed_cents: int
    compliance_posture: str
    open_notice_obligations: int
    last_compliance_run_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MammographyUnit(TypedDict, total=False):
    id: str
    facility_id: str
    manufacturer: str
    model_serial: str
    modality: str
    accreditation_expires_on: str
    accreditation_status: str
    operational_state: str
    survey_compliance: str
    last_passed_survey_end: Optional[str]
    reaccreditation_attempts_remaining: int
    total_images_acquired: int
    repeat_images_acquired: int
    image_based_repeat_rate_pct: Optional[float]
    patient_based_repeat_rate_pct: Optional[float]
    repeat_rate_flag: bool
    created_at: str
    updated_at: str
    version: int


class Personnel(TypedDict, total=False):
    id: str
    facility_id: str
    full_name: str
    role_type: str
    initial_qualification_on: str
    initial_training_hours: int
    initial_read_volume: int
    modality_certifications: List[str]
    qualification_status: str
    ce_status: str
    ce_hours_36mo: float
    volume_credit_24mo: int
    ce_deadline_at: Optional[str]
    last_qualification_review_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualificationCredit(TypedDict, total=False):
    """Immutable credit row — no `updated_at` and no `version`."""

    id: str
    personnel_id: str
    credit_type: str
    awarded_on: str
    ce_hours: Optional[float]
    exam_count: Optional[int]
    modality: Optional[str]
    source_note: Optional[str]
    created_at: str


class PhysicistSurvey(TypedDict, total=False):
    id: str
    unit_id: str
    physicist_id: str
    survey_type: str
    effective_start: str
    effective_end: str
    phantom_score: Optional[float]
    mean_glandular_dose_mgy: Optional[float]
    critical_deficiency_codes: List[str]
    outcome_note: Optional[str]
    status: str
    remediation_attempts: int
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentFailureEvent(TypedDict, total=False):
    id: str
    unit_id: str
    failure_code: str
    severity: str
    detected_at: str
    requires_post_repair_survey: bool
    status: str
    resolved_at: Optional[str]
    repair_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClinicalImageReview(TypedDict, total=False):
    id: str
    unit_id: str
    exam_ids: List[str]
    status: str
    attempt_number: int
    submitted_at: str
    reviewed_at: Optional[str]
    review_decision: Optional[str]
    deficiency_categories: List[str]
    reviewer_note: Optional[str]
    withdrawal_reason: Optional[str]
    fee_held_cents: int
    created_at: str
    updated_at: str
    version: int


class AnnualInspection(TypedDict, total=False):
    id: str
    facility_id: str
    inspection_date: str
    inspector_findings_level: str
    finding_codes: List[str]
    status: str
    corrective_action_due_at: Optional[str]
    closed_at: Optional[str]
    closure_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Exam(TypedDict, total=False):
    id: str
    unit_id: str
    technologist_id: str
    interpreting_physician_id: Optional[str]
    patient_ref: str
    patient_state_code: str
    exam_type: str
    performed_at: str
    original_image_count: int
    repeat_image_count: int
    birads_assessment: Optional[int]
    density_category: Optional[str]
    report_status: str
    notification_status: str
    follow_up_status: str
    recall_flag: bool
    biopsy_performed: bool
    pathology_result: Optional[str]
    amendment_count: int
    interpreted_at: Optional[str]
    interpreted_late: bool
    report_due_at: str
    notification_deadline_at: Optional[str]
    outcome_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepeatImagingRecord(TypedDict, total=False):
    id: str
    exam_id: str
    reason_code: str
    repeat_image_count: int
    equipment_failure_id: Optional[str]
    documented_at: str
    retracted: bool
    retraction_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NotificationLetter(TypedDict, total=False):
    id: str
    exam_id: str
    governing_state_code: str
    letter_type: str
    density_statement_code: str
    reading_grade_level: int
    required_notice_codes: List[str]
    dispatch_channel: str
    status: str
    generated_at: str
    deadline_at: str
    sent_at: Optional[str]
    undeliverable_reason: Optional[str]
    supersedes_letter_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplementalOrder(TypedDict, total=False):
    id: str
    exam_id: str
    modality: str
    recommendation_note: Optional[str]
    status: str
    coverage_outcome: str
    governing_state_code: Optional[str]
    allowed_amount_cents: Optional[int]
    covered_amount_cents: Optional[int]
    patient_responsibility_cents: Optional[int]
    coverage_tier: Optional[str]
    recommended_at: str
    followup_due_at: str
    appointment_start: Optional[str]
    appointment_end: Optional[str]
    completed_at: Optional[str]
    external_referral_note: Optional[str]
    completion_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RadiologistAuditCycle(TypedDict, total=False):
    id: str
    radiologist_id: str
    period_start: str
    period_end: str
    followup_window_days: int
    status: str
    variant_at_close: Optional[str]
    locked_at: Optional[str]
    screening_exam_count: Optional[int]
    recall_count: Optional[int]
    biopsy_count: Optional[int]
    cancer_count: Optional[int]
    excluded_exam_count: Optional[int]
    recall_rate_pct: Optional[float]
    ppv_pct: Optional[float]
    abnormal_interpretation_flag: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class AuditMetrics(TypedDict, total=False):
    """The nine-field read-only preview shape."""

    variant: str
    screening_exam_count: int
    recall_count: int
    biopsy_count: int
    cancer_count: int
    excluded_exam_count: int
    recall_rate_pct: Optional[float]
    ppv_pct: Optional[float]
    abnormal_interpretation_flag: bool


class ComplianceRunResult(TypedDict, total=False):
    """The nine fields a compliance run returns."""

    ran_at: str
    units_marked_reaccreditation_due: int
    units_survey_overdue: int
    exams_marked_delayed: int
    letters_marked_delivered: int
    orders_marked_lost: int
    personnel_moved_to_grace: int
    personnel_moved_to_deficient: int
    compliance_posture: str


class ClockReading(TypedDict, total=False):
    current_utc: str
    previous_utc: Optional[str]


JsonDict = Dict[str, Any]
