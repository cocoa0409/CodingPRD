"""Shapes of the resources this API returns.

Ten resources carry the common properties ``id``, ``created_at``,
``updated_at`` and ``version``.  Three of them — device quality events,
maneuvers and custody events — are append-only evidence rows that carry only
``id`` and ``created_at``: they have no ``updated_at`` and no ``version``,
which is why they do not inherit from ``MutableRecord``.
"""

from typing import Any, Dict, List, Optional, TypedDict


class ResponseMeta(TypedDict, total=False):
    api_request_id: str
    api_request_timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class Envelope(TypedDict, total=False):
    meta: ResponseMeta
    response_type: str
    data: Any


class ErrorPayload(TypedDict):
    error_id: str
    message: str


class MutableRecord(TypedDict):
    """Common properties of every resource that can be updated in place."""

    id: str
    created_at: str
    updated_at: str
    version: int


class EvidenceRecord(TypedDict):
    """Common properties of the append-only evidence rows."""

    id: str
    created_at: str


class Device(MutableRecord, total=False):
    device_code: str
    modality: str
    status: str
    last_calibration_at: Optional[str]
    last_calibration_error_pct: Optional[float]
    last_biologic_control_date: Optional[str]
    consecutive_biologic_failures: int
    last_session_end_at: Optional[str]
    current_filter_serial: Optional[str]
    sessions_since_filter_change: int
    quarantined_at: Optional[str]
    quarantine_reason: Optional[str]
    quarantine_trigger_staff_id: Optional[str]


class DeviceQualityEvent(EvidenceRecord, total=False):
    device_id: str
    event_type: str
    performed_by_staff_id: str
    subject_staff_id: Optional[str]
    measured_volume_l: Optional[float]
    ambient_temp_c: Optional[int]
    barometric_pressure_kpa: Optional[float]
    measured_fev1_l: Optional[float]
    measured_fvc_l: Optional[float]
    filter_serial: Optional[str]
    dwell_minutes: Optional[int]
    btps_factor: Optional[float]
    corrected_volume_l: Optional[float]
    error_pct: Optional[float]
    deviation_pct: Optional[float]
    deviation_variant: Optional[str]
    rolling_mean_fev1_l: Optional[float]
    outcome: str
    failure_reason: Optional[str]
    performed_at: str
    note: Optional[str]


class Staff(MutableRecord, total=False):
    employee_code: str
    full_name: str
    role_type: str
    credential: str
    competency_expires_on: str
    credentialed_modalities: List[str]
    status: str
    max_concurrent_reports: int
    is_biologic_control: bool
    baseline_fev1_l: Optional[float]
    baseline_fvc_l: Optional[float]
    baseline_established_on: Optional[str]
    open_report_count: int


class Patient(MutableRecord, total=False):
    mrn: str
    full_name: str
    birth_date: str
    sex: str
    height_cm: float
    weight_kg: float
    smoking_status: str
    age_years: int
    completed_order_count: int


class ReferenceEquationSet(MutableRecord, total=False):
    equation_code: str
    modality_scope: List[str]
    sex_scope: str
    applicable_age_min: int
    applicable_age_max: int
    lln_percentile: float
    ratio_lln: float
    a_fev1: float
    b_fev1: float
    c_fev1: float
    a_fvc: float
    b_fvc: float
    c_fvc: float
    rsd_frac: float
    bd_criterion: str
    status: str


class RescueMedicationLot(MutableRecord, total=False):
    lot_number: str
    drug: str
    doses_at_receipt: int
    doses_remaining: int
    doses_reserved: int
    expires_on: str
    status: str


class TestOrder(MutableRecord, total=False):
    patient_id: str
    ordering_staff_id: str
    indication_code: str
    requested_modalities: List[str]
    test_context: str
    bronchodilator_requested: bool
    challenge_type: str
    current_medication_classes: List[str]
    status: str
    rejection_reason: Optional[str]
    hold_release_at: Optional[str]
    abort_count: int
    cancellation_reason: Optional[str]


class MedicationHold(MutableRecord, total=False):
    order_id: str
    medication_class: str
    required_hold_hours: int
    instructed_at: str
    release_at: str
    attestation_result: Optional[str]
    attested_at: Optional[str]
    status: str


class TestSession(MutableRecord, total=False):
    order_id: str
    device_id: str
    technologist_staff_id: str
    reference_equation_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    session_status: str
    custody_status: str
    reference_equation_code: str
    predicted_fev1_l: float
    predicted_fvc_l: float
    lln_fev1_l: float
    ratio_lln: float
    best_fev1_l: Optional[float]
    best_fvc_l: Optional[float]
    best_fev1_post_l: Optional[float]
    acceptable_maneuver_count: int
    repeatability_delta_ml: Optional[int]
    fvc_repeatability_delta_ml: Optional[int]
    quality_grade: str
    fev1_pct_predicted: Optional[float]
    fvc_pct_predicted: Optional[float]
    fev1_fvc_ratio: Optional[float]
    bd_response_pct: Optional[float]
    bd_response_ml: Optional[int]
    bd_response_variant: Optional[str]
    bd_response_positive: Optional[bool]
    rejection_round: int
    abort_reason: Optional[str]
    turnaround_minutes: Optional[int]
    technologist_comment: Optional[str]


class Maneuver(EvidenceRecord, total=False):
    session_id: str
    maneuver_index: int
    phase: str
    fvc_l: float
    fev1_l: float
    pef_l_s: float
    back_extrapolated_volume_ml: int
    expiratory_time_s: float
    plateau_reached: bool
    cough_in_first_second: bool
    glottic_closure: bool
    acceptability: str
    bev_limit_ml: int
    rejection_reasons: List[str]
    coaching_note: Optional[str]
    performed_at: str


class ChallengeRun(MutableRecord, total=False):
    session_id: str
    rescue_lot_id: str
    agent: str
    baseline_fev1_l: float
    status: str
    current_step_index: int
    cumulative_dose_units: float
    last_step_dose_units: Optional[float]
    last_step_drop_pct: Optional[float]
    max_fev1_drop_pct: Optional[float]
    pc20_dose_units: Optional[float]
    rescue_doses_administered: int
    stop_reason: Optional[str]
    abort_reason: Optional[str]


class InterpretationReport(MutableRecord, total=False):
    session_id: str
    interpreter_staff_id: str
    assigned_at: str
    queue_load_pct: float
    load_tier: str
    sla_minutes: int
    due_at: str
    signed_at: Optional[str]
    turnaround_minutes: Optional[int]
    sla_breached: Optional[bool]
    pattern: Optional[str]
    severity: Optional[str]
    reference_equation_code: str
    template_version: str
    clinical_comment: Optional[str]
    amendment_count: int
    amendment_reason: Optional[str]
    superseded_by_report_id: Optional[str]
    status: str


class CustodyEvent(EvidenceRecord, total=False):
    session_id: str
    event_type: str
    actor_user_id: str
    actor_role: str
    seal_serial: Optional[str]
    id_document_type: Optional[str]
    note: Optional[str]
    performed_at: str


Json = Dict[str, Any]
