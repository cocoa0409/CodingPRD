"""TypedDict shapes for the fifteen entities this contract exposes.

All fifteen carry the shared envelope (``id``, ``created_at``, ``updated_at``,
``version``), so every shape extends :class:`CommonFields`. These are documentation
and editor aids for the test suite; they are structural only and are never used
for runtime validation.
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - Python 3.8+
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Client(CommonFields, total=False):
    full_name: str
    preferred_language_code: str
    country_of_birth_code: str
    a_number: Optional[str]
    date_of_birth: str
    household_size: int
    annual_household_income_cents: int
    fpl_percent: float
    confidentiality_consent_scope: str
    interpreter_required: bool
    open_matter_count: int
    status: str


class ProgramCapacityCycle(CommonFields, total=False):
    cycle_label: str
    period_start_date: str
    period_end_date: str
    total_case_slots: int
    reserved_detained_slots: int
    general_slots_consumed: int
    detained_slots_consumed: int
    available_slot_count: int
    waitlisted_count: int
    utilization_ratio: float
    capacity_posture: str
    posture_override_until_utc: Optional[str]
    checkpoint_epoch: int
    last_checkpoint_utc: Optional[str]


class DetentionFacility(CommonFields, total=False):
    name: str
    jurisdiction_code: str
    visit_lead_time_hours: int
    max_daily_visit_slots: int
    expedited_filing_days: int
    access_credential_required: bool
    status: str


class OrganizationRecognition(CommonFields, total=False):
    recognition_number: str
    effective_date: str
    expiry_date: str
    authorized_forums: List[str]
    status: str
    conditional_reason_code: Optional[str]
    suspended_accreditation_count: int
    lapsed_at_utc: Optional[str]


class Representative(CommonFields, total=False):
    full_name: str
    rep_type: str
    bar_number: Optional[str]
    languages: List[str]
    max_case_load: int
    max_supervisees: int
    weekly_capacity_hours: float
    active_case_load: int
    supervisee_count: int
    supervision_required: bool
    authorization_status: str
    facility_access_credential_expires_on: Optional[str]
    status: str


class Accreditation(CommonFields, total=False):
    representative_id: str
    recognition_id: str
    approved_by_representative_id: Optional[str]
    accreditation_type: str
    requested_forums: List[str]
    authorized_forums: List[str]
    status: str
    effective_date: Optional[str]
    expiry_date: Optional[str]
    renewal_round: int
    decision_reason_code: Optional[str]


class IntakeScreening(CommonFields, total=False):
    client_id: str
    cycle_id: str
    screener_representative_id: Optional[str]
    decided_by_representative_id: Optional[str]
    facility_id: Optional[str]
    case_type: str
    detained: bool
    statutory_deadline_date: Optional[str]
    one_year_bar_applies: Optional[bool]
    prior_removal_order: Optional[bool]
    unaccompanied_minor: Optional[bool]
    legal_eligibility_verdict: Optional[str]
    urgency_score: Optional[float]
    urgency_tier: Optional[str]
    urgency_variant_applied: Optional[str]
    urgency_anchor_date: Optional[str]
    status: str
    decision_reason_code: Optional[str]
    referral_partner_code: Optional[str]
    waitlist_rank: Optional[int]
    waitlist_expires_at_utc: Optional[str]
    screened_at_utc: Optional[str]
    decided_at_utc: Optional[str]


class CaseMatter(CommonFields, total=False):
    client_id: str
    intake_id: str
    cycle_id: str
    principal_matter_id: Optional[str]
    facility_id: Optional[str]
    case_type: str
    forum: str
    detained: bool
    representation_status: str
    filing_status: str
    slot_pool_consumed: str
    statutory_deadline_date: Optional[str]
    expedited_deadline_date: Optional[str]
    effective_filing_deadline_date: Optional[str]
    readiness_index_weighted: float
    readiness_ready_strict: bool
    evidence_blocking_count: int
    readiness_gate_applied: str
    interpretation_cost_cents: int
    direct_hours_logged: float
    supervision_hours_logged: float
    coverage_gap_flag: bool
    outcome: Optional[str]
    outcome_recorded_at_utc: Optional[str]
    closed_at_utc: Optional[str]


class CaseAssignment(CommonFields, total=False):
    matter_id: str
    representative_id: str
    supervision_link_id: Optional[str]
    role_on_case: str
    status: str
    supervision_source: str
    direct_hours_logged: float
    supervision_hours_logged: float
    assigned_at_utc: Optional[str]
    activated_at_utc: Optional[str]
    released_at_utc: Optional[str]
    release_reason_code: Optional[str]


class EvidenceItem(CommonFields, total=False):
    matter_id: str
    item_type: str
    tier: str
    weight_points: int
    source_language_code: str
    requires_translation: bool
    status: str
    due_date: Optional[str]
    received_at_utc: Optional[str]
    verified_at_utc: Optional[str]
    rejection_round: int
    disposition_reason_code: Optional[str]


class Declaration(CommonFields, total=False):
    matter_id: str
    preparer_assignment_id: str
    reviewer_assignment_id: Optional[str]
    readback_session_id: Optional[str]
    language_code: str
    word_count: int
    status: str
    revision_round: int
    readback_completed: bool
    revision_reason_code: Optional[str]
    certified_at_utc: Optional[str]


class InterpretationSession(CommonFields, total=False):
    matter_id: str
    interpreter_representative_id: Optional[str]
    language_code: str
    interpreter_source: str
    purpose: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    actual_minutes: Optional[int]
    billed_minutes: int
    billable_cents: int
    status: str
    closure_reason_code: Optional[str]


class CalendarEvent(CommonFields, total=False):
    matter_id: str
    facility_id: Optional[str]
    assigned_representative_id: Optional[str]
    continued_from_event_id: Optional[str]
    event_type: str
    starts_at_utc: str
    ends_at_utc: str
    location_code: str
    travel_buffer_minutes: int
    status: str
    reschedule_count: int
    coverage_gap_flag: bool
    client_conflict_waived: bool


class InformedDecision(CommonFields, total=False):
    matter_id: str
    counseled_by_assignment_id: str
    readback_session_id: Optional[str]
    decision_type: str
    risks_disclosed: List[str]
    alternatives_disclosed: List[str]
    counseling_language_code: str
    language_match_verified: bool
    status: str
    acknowledged_at_utc: Optional[str]
    superseded_by_decision_id: Optional[str]
    revocation_reason_code: Optional[str]


class GrantReport(CommonFields, total=False):
    cycle_id: str
    grant_code: str
    period_start_date: str
    period_end_date: str
    disclosure_level: str
    status: str
    cases_served_count: int
    outcomes_summary: Dict[str, Any]
    consent_verified_count: int
    suppressed_case_count: int
    base_reimbursable_cents: int
    supervision_surcharge_cents: int
    total_reimbursable_cents: int
    allocated_line_total_cents: int
    rounding_remainder_cents: int
    amendment_round: int
    generated_at_utc: Optional[str]
    submitted_at_utc: Optional[str]
