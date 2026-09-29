"""Typed shapes for every resource and computed readout (PRD §2.5, §3).

PRD §2.5 splits the resources in two. Ten resources "all carry `updated_at`
and `version`"; three "are immutable once written and therefore carry only
`id` and `created_at` — they have no `updated_at` field and no `version`
field at all: `NurseLicense`, `NurseShift`, and `ComplianceAuditRecord`".
That split is reflected below by two different base shapes.
"""

from typing import Optional, TypedDict


class CreatedResource(TypedDict):
    """id and created_at only — the immutable-record shape of PRD §2.5."""

    id: str
    created_at: str


class VersionedResource(CreatedResource):
    """The mutable-resource shape of PRD §2.5."""

    updated_at: str
    version: int


# ── Reference data ─────────────────────────────────────────────────────────
class Practice(VersionedResource):
    name: str
    office_open_utc_hhmm: str
    office_close_utc_hhmm: str
    per_minute_rate_millicents: int
    weekend_is_after_hours: bool
    consent_recording_required: bool
    variance_review_threshold: int
    audit_period_start_utc: Optional[str]
    status: str
    compliance_posture: str
    open_callback_count: int
    open_variance_count: int
    escalated_callback_count: int
    billed_advice_minutes_total: int
    advice_fee_accrued_cents: int


class Patient(VersionedResource):
    practice_id: str
    full_name: str
    dob: str
    sex: Optional[str]
    pregnancy_status: str
    phone: Optional[str]
    mrn: Optional[str]


class SymptomProtocol(VersionedResource):
    code: str
    title: str
    base_severity: int
    min_age_years: int
    max_age_years: int
    pregnancy_sensitive: bool
    emergency_override: bool
    min_disposition_level: str
    infant_modifier_points: int
    status: str


# ── Nurses, licences, shifts, coverage ─────────────────────────────────────
class Nurse(VersionedResource):
    full_name: str
    seniority_level: int
    max_concurrent_calls: int
    high_risk_cap: int
    active_call_load: int
    pending_high_risk_count: int
    intake_eligibility: str


class NurseLicense(CreatedResource):
    """Immutable (PRD §2.5); `status` is derived from the clock, never stored."""

    nurse_id: str
    state_code: str
    license_number: str
    expires_on: str
    status: str


class NurseShift(CreatedResource):
    """Immutable (PRD §2.5); `status` is derived from the clock, never stored."""

    nurse_id: str
    start_utc: str
    end_utc: str
    scheduled_minutes: int
    status: str


class CoverageWindow(VersionedResource):
    practice_id: str
    start_utc: str
    end_utc: str
    coverage_kind: str
    status: str
    suspend_reason: Optional[str]


# ── The call and its clinical chain ────────────────────────────────────────
class TriageCall(VersionedResource):
    practice_id: str
    caller_name: str
    caller_phone: str
    caller_relationship: Optional[str]
    caller_state_code: str
    reason_text: Optional[str]
    status: str
    is_after_hours: bool
    patient_id: Optional[str]
    match_method: Optional[str]
    match_confidence_pct: Optional[int]
    consent_type: Optional[str]
    consent_given_by: Optional[str]
    recording_reference: Optional[str]
    consent_recorded_at: Optional[str]
    assigned_nurse_id: Optional[str]
    assigned_at: Optional[str]
    deferred_assignment_count: int
    requires_warm_transfer: bool
    warm_transfer_completed_at: Optional[str]
    handle_minutes: Optional[int]
    billable_minutes: int
    advice_fee_cents: int
    closed_at: Optional[str]
    reopen_count: int
    abandon_reason: Optional[str]


class ProtocolAssessment(VersionedResource):
    call_id: str
    protocol_id: str
    confirmation_mode: str
    stated_age_years: Optional[int]
    confirmed_pregnancy_status: Optional[str]
    red_flag_count: int
    age_years_used: int
    pregnancy_status_used: str
    age_modifier_points: int
    pregnancy_modifier_points: int
    red_flag_points: int
    acuity_score: int
    status: str


class Disposition(VersionedResource):
    call_id: str
    assessment_id: str
    recommended_level: str
    final_level: str
    is_override: bool
    override_reason_code: Optional[str]
    override_narrative: Optional[str]
    determined_by_nurse_id: str
    overridden_by_nurse_id: Optional[str]
    advice_status: str
    audit_status: str
    requires_callback: bool
    callback_verified_at: Optional[str]


class WarmTransfer(VersionedResource):
    call_id: str
    psap_center_code: str
    location_source: str
    location_address_line: str
    location_state_code: str
    location_lat: float
    location_lng: float
    callback_number: str
    status: str
    location_verified_by: Optional[str]
    location_confidence_pct: Optional[int]
    psap_incident_number: Optional[str]


class CallbackTask(VersionedResource):
    disposition_id: str
    practice_id: str
    assigned_nurse_id: str
    risk_class: str
    due_by_utc: str
    max_attempts: int
    attempt_count: int
    last_attempt_outcome: Optional[str]
    status: str
    patient_condition: Optional[str]
    advice_followed: Optional[bool]
    verifier_attestation: Optional[str]
    verified_by_nurse_id: Optional[str]
    verified_at: Optional[str]


class ComplianceAuditRecord(CreatedResource):
    """Immutable and one-per-disposition (PRD §2.5 and §3.10)."""

    disposition_id: str
    reported_outcome: str
    outcome_source: str
    outcome_observed_at: str
    outcome_ordinal: int
    disposition_level_ordinal: int
    variance_class: str
    variance_severity_points: int
    auditor_user_id: str


# ── Computed readouts (PRD §3.10) ──────────────────────────────────────────
class ComplianceSummary(TypedDict):
    audited_count: int
    concordant_count_strict: int
    concordant_count_band_tolerant: int
    concordance_rate_strict_pct: float
    concordance_rate_band_tolerant_pct: float
    undertriage_count: int
    overtriage_count: int
    variance_severity_points_total: int
    open_variance_count: int
    compliance_posture: str


class AfterHoursInvoice(TypedDict):
    advice_subtotal_cents: int
    billed_advice_minutes_total: int
    escalated_callback_count: int
    escalation_gross_cents: int
    coverage_credit_pct: int
    coverage_credit_cents: int
    invoice_total_cents: int


class StaffingAdequacy(TypedDict):
    state_code: str
    window_start_utc: str
    window_end_utc: str
    offered_call_count: int
    required_nurse_minutes: int
    scheduled_nurse_minutes: int
    licensed_nurse_count: int
    adequacy_ratio_pct: float
    staffing_posture: str


class ClockState(TypedDict):
    current_utc: str
