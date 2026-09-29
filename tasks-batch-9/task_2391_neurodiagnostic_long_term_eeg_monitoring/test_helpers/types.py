"""
Shape declarations for the records this API returns.

These TypedDicts document the field vocabulary the tests assert against, so a
misspelled field name is visible at the point of use rather than only in a
failure message. Note the deliberate asymmetry in the common preamble: a
SafetyIntervention and a ConferenceVote expose only `id` and `created_at`, while
every other record type carries `id`, `created_at`, `updated_at` and `version`.
"""

from typing import Any, Dict, List, Optional, TypedDict


class RecordPreamble(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyPreamble(TypedDict):
    id: str
    created_at: str


class MonitoringUnit(RecordPreamble, total=False):
    name: str
    bed_count: int
    storage_quota_gb: float
    storage_used_gb: float
    storage_pressure_pct: float
    posture: str
    active_study_count: int
    coverage_capacity: int
    beds_available: int
    late_response_count: int
    retention_sweep_index: int


class Bed(RecordPreamble, total=False):
    unit_id: str
    label: str
    status: str
    current_admission_id: Optional[str]
    released_at: Optional[str]
    turnover_clear_at: Optional[str]


class TechnologistShift(RecordPreamble, total=False):
    unit_id: str
    technologist_user_id: str
    starts_at: str
    ends_at: str
    max_concurrent_studies: int
    state: str
    assigned_study_count: int


class Patient(RecordPreamble, total=False):
    mrn: str
    display_name: str
    risk_tier: str


class AuthorizationRequest(RecordPreamble, total=False):
    patient_id: str
    requested_setting: str
    requested_days: int
    status: str
    authorized_setting: Optional[str]
    authorized_days: int
    days_reserved: int
    days_consumed: int
    days_available: int
    resubmission_count: int
    payer_note: Optional[str]


class Admission(RecordPreamble, total=False):
    patient_id: str
    authorization_id: str
    unit_id: str
    setting: str
    scheduled_admit_at: str
    target_event_count: int
    planned_days: int
    clinical_state: str
    authorization_state: str
    admitted_at: Optional[str]
    discharged_at: Optional[str]
    planned_discharge_at: Optional[str]
    bed_id: Optional[str]
    disposition: Optional[str]
    weighted_event_count: float
    capture_adequacy_index: float
    capture_adequacy_index_prospective: float
    projected_daily_yield: float
    deficit_weighted: float
    elapsed_monitored_days: float
    extension_count: int
    last_extension_granted_days: int
    last_extension_outcome: Optional[str]


class CaptureSummary(TypedDict, total=False):
    adequacy_retrospective: float
    adequacy_prospective: float
    weighted_event_count: float
    projected_daily_yield: float
    deficit_weighted: float
    elapsed_monitored_days: float


class TaperPlan(RecordPreamble, total=False):
    admission_id: str
    total_steps: int
    current_step: int
    status: str
    hold_reason: Optional[str]


class Study(RecordPreamble, total=False):
    admission_id: str
    channel_count: int
    modality: str
    acquisition_state: str
    data_state: str
    acquired_minutes: int
    stored_gb: float
    closed_segment_count: int
    impedance_fail_count: int
    shift_id: Optional[str]
    current_segment_started_at: Optional[str]
    completed_at: Optional[str]
    last_impedance_kohm: Optional[float]
    export_hold_reason: Optional[str]


class SeizureAlert(RecordPreamble, total=False):
    study_id: str
    source: str
    detected_at: str
    triage_state: str
    response_state: str
    response_deadline_minutes: int
    responded_at: Optional[str]
    latency_minutes: Optional[int]
    adjudicated_at: Optional[str]
    classification: Optional[str]


class SafetyIntervention(AppendOnlyPreamble, total=False):
    alert_id: str
    interventions: List[str]
    injury_observed: bool
    rescue_med_given: bool
    nurse_user_id: str
    recorded_at: str


class EventMarking(RecordPreamble, total=False):
    study_id: str
    alert_id: Optional[str]
    onset_at: str
    event_class: str
    duration_seconds: int
    taper_step_at_onset: int
    weight: float
    status: str
    adjudicated_at: Optional[str]
    retraction_reason: Optional[str]


class ReviewReport(RecordPreamble, total=False):
    study_id: str
    status: str
    localization: Optional[str]
    prelim_issued_at: Optional[str]
    final_issued_at: Optional[str]
    prelim_author_user_id: Optional[str]
    final_author_user_id: Optional[str]
    turnaround_calendar_hours: Optional[float]
    turnaround_coverage_hours: Optional[float]
    sla_breached: bool
    addendum_count: int
    addendum_reason: Optional[str]


class ExportPackage(RecordPreamble, total=False):
    study_id: str
    include_video: bool
    supersedes_export_id: Optional[str]
    status: str
    package_gb: float
    built_at: Optional[str]
    delivered_at: Optional[str]
    recipient_center: Optional[str]
    retention_expires_at: Optional[str]
    blocked_reason: Optional[str]
    revocation_reason: Optional[str]


class ConferenceCase(RecordPreamble, total=False):
    admission_id: str
    export_id: str
    status: str
    presenter_user_id: Optional[str]
    decision_at: Optional[str]
    defer_round: int
    eligible_vote_count: int
    candidate_votes: int
    non_candidate_votes: int
    defer_votes: int
    distinct_specialty_count: int
    quorum_met: bool


class ConferenceVote(AppendOnlyPreamble, total=False):
    case_id: str
    specialty: str
    vote: str
    rationale: Optional[str]
    voter_user_id: str
    round_index: int
    counted: bool


# Convenience aliases for loosely typed helper returns.
Payload = Dict[str, Any]
Record = Dict[str, Any]
