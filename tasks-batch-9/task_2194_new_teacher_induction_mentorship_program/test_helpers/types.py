"""TypedDict shapes for the thirteen entities of the induction program.

Every stored row carries an ``id`` and a ``created_at``; almost every entity
additionally carries ``updated_at`` and ``version``.  The single exception is
``Milestone``, which is immutable configuration and therefore declares only
``id`` and ``created_at`` — that asymmetry is expressed by giving Milestone its
own base class.
"""

from typing import Any, Dict, List, Optional, TypedDict


class SystemFields(TypedDict):
    """Audit stamps carried by every mutable entity."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableSystemFields(TypedDict):
    """Audit stamps carried by immutable configuration rows."""

    id: str
    created_at: str


class Site(SystemFields, total=False):
    name: str
    site_code: str
    region_code: str
    status: str
    mentor_slot_cap: int
    active_match_count: int
    closed_at: Optional[str]
    reason: Optional[str]


class Mentor(SystemFields, total=False):
    site_id: str
    full_name: str
    subject_endorsements: List[str]
    caseload_cap: int
    certification_status: str
    certification_expires_on: Optional[str]
    suspension_reason: Optional[str]
    active_caseload_count: int
    training_hours_current_cycle: float
    training_modules_current_cycle: List[str]
    stipend_accrued_cents: int
    stipend_paid_cents: int
    stipend_clawed_back_cents: int
    verified_minutes_lifetime: int


class Cohort(SystemFields, total=False):
    name: str
    program_year: int
    region_code: str
    status: str
    seminar_sessions_required: int
    enrolled_novice_count: int
    closed_at: Optional[str]


class NoviceTeacher(SystemFields, total=False):
    site_id: str
    cohort_id: str
    full_name: str
    subject_area: str
    induction_year: int
    license_stage: str
    program_status: str
    license_advancement_status: str
    retention_outcome: str
    retention_observed_on: Optional[str]
    withdrawn_reason: Optional[str]
    verified_contact_minutes: int
    documented_observation_cycles: int
    credited_seminar_sessions: int
    attained_milestone_count: int
    readiness_index_live: float
    readiness_index_snapshot: float


class NoviceReadiness(TypedDict, total=False):
    """Computed readiness read keyed by novice id."""

    novice_id: str
    readiness_index_live: float
    readiness_index_snapshot: float
    contact_component: float
    observation_component: float
    seminar_component: float
    held_sessions: int
    excused_sessions: int
    seminar_denominator: int
    snapshot_source_attainment_id: Optional[str]
    meets_readiness_gate: bool


class MentorMatch(SystemFields, total=False):
    mentor_id: str
    novice_id: str
    match_status: str
    selection_mode: str
    subject_match_tier: str
    site_match: bool
    pinned_stipend_rate_cents_per_hour: Optional[int]
    verified_minutes_total: int
    accrued_stipend_cents: int
    activated_at: Optional[str]
    suspended_at: Optional[str]
    ended_at: Optional[str]
    end_reason: Optional[str]


class ContactLog(SystemFields, total=False):
    match_id: str
    contact_date: str
    minutes: int
    contact_type: str
    description: str
    verification_status: str
    credited_minutes: int
    stipend_cents: int
    resubmit_count: int
    rate_tier_at_verification: Optional[str]
    cert_multiplier_at_verification: Optional[float]
    submitted_by_user_id: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    dispute_reason: Optional[str]
    reject_reason: Optional[str]
    void_reason: Optional[str]


class ObservationCycle(SystemFields, total=False):
    match_id: str
    cycle_index: int
    window_start: str
    window_end: str
    phase: str
    feedback_review_status: str
    return_count: int
    narrative: Optional[str]
    growth_area_codes: Optional[List[str]]
    rubric_scores: Optional[Dict[str, int]]
    composite_rubric_score: Optional[float]
    observed_at: Optional[str]
    post_conference_at: Optional[str]
    documented_at: Optional[str]
    abandoned_at: Optional[str]
    return_reason: Optional[str]


class Milestone(ImmutableSystemFields, total=False):
    code: str
    title: str
    sequence_index: int
    required_contact_minutes: int
    required_observation_cycles: int
    required_credited_seminars: int
    license_stage_unlocked: str
    gates_license_recommendation: bool
    prerequisite_milestone_id: Optional[str]


class MilestoneAttainment(SystemFields, total=False):
    novice_id: str
    milestone_id: str
    status: str
    evidence_note: Optional[str]
    revocation_count: int
    snapshot_contact_minutes: Optional[int]
    snapshot_observation_cycles: Optional[int]
    snapshot_credited_seminars: Optional[int]
    snapshot_held_sessions: Optional[int]
    snapshot_excused_sessions: Optional[int]
    attained_on: Optional[str]
    attested_by_user_id: Optional[str]
    revoked_on: Optional[str]
    revoke_reason: Optional[str]


class SeminarSession(SystemFields, total=False):
    cohort_id: str
    session_index: int
    topic: str
    scheduled_start: str
    scheduled_end: str
    scheduled_minutes: int
    status: str
    credited_attendance_count: int
    held_at: Optional[str]
    cancelled_at: Optional[str]
    cancel_reason: Optional[str]


class SeminarAttendance(SystemFields, total=False):
    session_id: str
    novice_id: str
    attendance_status: str
    minutes_attended: int
    credit_ratio: float
    credited: bool
    recorded_by_user_id: str


class StipendDisbursement(SystemFields, total=False):
    mentor_id: str
    period_code: str
    period_start: str
    period_end: str
    status: str
    gross_cents: int
    adjustment_cents: int
    net_cents: int
    eligible_log_count: int
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    paid_at: Optional[str]
    payment_reference: Optional[str]
    clawed_back_at: Optional[str]
    clawback_reason: Optional[str]
    superseded_by_id: Optional[str]


class CompletionCertification(SystemFields, total=False):
    novice_id: str
    packet_status: str
    evidence_milestone_count: int
    base_score: float
    retention_bonus: float
    completion_score: float
    resubmission_count: int
    submitted_by_user_id: Optional[str]
    submitted_at: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    state_file_number: Optional[str]
    return_reason: Optional[str]
    withdrawn_reason: Optional[str]


AnyEntity = Dict[str, Any]
