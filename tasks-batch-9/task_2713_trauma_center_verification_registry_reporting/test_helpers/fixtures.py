"""Composite setup helpers.

Every helper here drives the API through its own declared endpoints, so a test never
reaches behind the contract to seed state. Helpers read their results through
``get_success_data`` and return the parsed resource dictionaries.

The helpers are grouped by what they buy a test:

* readers and primitives — the smallest useful calls;
* state progression — one entity walked to a named state;
* entity hierarchy — a center with its children already wired up;
* lifecycle shortcuts — a whole chain in one call;
* accumulation targeting — cohorts and ledgers built to land on a threshold;
* finalisation — decided cycles and terminal centers.
"""

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .constants import CLOCK_EPOCH
from .types import (
    ActivityKind,
    CycleType,
    DeficiencyClass,
    DesignationLevel,
    Decision,
    ResponderRole,
    TierCode,
    TriageReviewStatus,
)
from .test_users import (
    ABSTRACTOR_1_USER_ID,
    DIRECTOR_1_USER_ID,
    REVIEWER_1_USER_ID,
    SURVEYOR_1,
    VALIDATOR_1_USER_ID,
    make_registry_abstractor_headers,
    make_registry_validator_headers,
    make_state_designation_officer_headers,
    make_system_admin_headers,
    make_trauma_medical_director_headers,
    make_trauma_program_manager_headers,
    make_verification_reviewer_headers,
)

# ─── Authority selection ──────────────────────────────────


def authority_headers(cycle_type: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Headers of the authority entitled to review a cycle of the given type."""
    if cycle_type == CycleType.STATE_DESIGNATION:
        return (
            make_state_designation_officer_headers(user_id)
            if user_id
            else make_state_designation_officer_headers()
        )
    return (
        make_verification_reviewer_headers(user_id)
        if user_id
        else make_verification_reviewer_headers()
    )


# ─── Readers ──────────────────────────────────────────────


def get_center(api, center_id: str) -> Dict[str, Any]:
    """Read one center back."""
    return get_success_data(api.get_trauma_center(center_id, make_system_admin_headers()))


def get_case(api, case_id: str) -> Dict[str, Any]:
    """Read one registry case back."""
    return get_success_data(api.get_registry_case(case_id, make_system_admin_headers()))


def get_cycle(api, cycle_id: str) -> Dict[str, Any]:
    """Read one verification cycle back."""
    return get_success_data(
        api.get_verification_cycle(cycle_id, make_system_admin_headers())
    )


def get_event(api, pi_event_id: str) -> Dict[str, Any]:
    """Read one PI event back."""
    return get_success_data(api.get_pi_event(pi_event_id, make_system_admin_headers()))


def get_readiness(
    api, cycle_id: str, variant: Optional[str] = None
) -> Dict[str, Any]:
    """Read a cycle's computed readiness score."""
    params = {"variant": variant} if variant else None
    return get_success_data(
        api.get_cycle_readiness(cycle_id, make_system_admin_headers(), params)
    )


def get_triage_rates(api, center_id: str, variant: Optional[str] = None) -> Dict[str, Any]:
    """Read a center's computed triage rates."""
    params = {"variant": variant} if variant else None
    return get_success_data(
        api.get_triage_rates(center_id, make_system_admin_headers(), params)
    )


def list_data(api_response) -> List[Dict[str, Any]]:
    """Parse a list response down to its data array."""
    return get_success_data(api_response)


def get_deficiency(api, cycle_id: str, deficiency_id: str) -> Dict[str, Any]:
    """Read one deficiency back through its cycle's list endpoint."""
    rows = get_success_data(
        api.list_criteria_deficiencies(cycle_id, make_system_admin_headers())
    )
    for row in rows:
        if row["id"] == deficiency_id:
            return row
    raise AssertionError(f"Deficiency {deficiency_id} not found on cycle {cycle_id}")


def get_abstraction(api, case_id: str, abstraction_id: str) -> Dict[str, Any]:
    """Read one abstraction record back through its case's list endpoint."""
    rows = get_success_data(api.list_abstractions(case_id, make_system_admin_headers()))
    for row in rows:
        if row["id"] == abstraction_id:
            return row
    raise AssertionError(f"Abstraction {abstraction_id} not found on case {case_id}")


def get_corrective_action(api, pi_event_id: str, action_id: str) -> Dict[str, Any]:
    """Read one corrective action back through its event's list endpoint."""
    rows = get_success_data(
        api.list_corrective_actions(pi_event_id, make_system_admin_headers())
    )
    for row in rows:
        if row["id"] == action_id:
            return row
    raise AssertionError(f"Corrective action {action_id} not found on event {pi_event_id}")


def get_outreach_activity(api, center_id: str, activity_id: str) -> Dict[str, Any]:
    """Read one outreach activity back through its center's list endpoint."""
    rows = get_success_data(
        api.list_outreach_activities(center_id, make_system_admin_headers())
    )
    for row in rows:
        if row["id"] == activity_id:
            return row
    raise AssertionError(f"Outreach activity {activity_id} not found on center {center_id}")


def get_agreement(api, center_id: str, agreement_id: str) -> Dict[str, Any]:
    """Read one referral agreement back through a party center's list endpoint."""
    rows = get_success_data(
        api.list_center_referral_agreements(center_id, make_system_admin_headers())
    )
    for row in rows:
        if row["id"] == agreement_id:
            return row
    raise AssertionError(f"Agreement {agreement_id} not found on center {center_id}")


def get_surveyor_booking(api, cycle_id: str, booking_id: str) -> Dict[str, Any]:
    """Read one surveyor booking back through its cycle's list endpoint."""
    rows = get_success_data(
        api.list_surveyor_bookings(cycle_id, make_system_admin_headers())
    )
    for row in rows:
        if row["id"] == booking_id:
            return row
    raise AssertionError(f"Booking {booking_id} not found on cycle {cycle_id}")


# ─── Primitives ───────────────────────────────────────────


def move_clock(api, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock and return the echoed value."""
    return get_success_data(
        api.set_clock(f.clock_payload(to_iso8601), make_system_admin_headers())
    )


def anchor_clock(api, to_iso8601: str = CLOCK_EPOCH) -> Dict[str, Any]:
    """Pin the logical clock explicitly, so a test never depends on start-up state."""
    return move_clock(api, to_iso8601)


def create_center(
    api,
    name: str = "Riverbend Trauma",
    state_code: str = "NE",
    designation_level: str = DesignationLevel.LEVEL_II,
    verification_cycle_start_date: str = "2026-01-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Register one trauma center."""
    payload = f.trauma_center_payload(
        name=name,
        state_code=state_code,
        designation_level=designation_level,
        verification_cycle_start_date=verification_cycle_start_date,
        **overrides,
    )
    return get_success_data(api.create_trauma_center(payload, make_system_admin_headers()))


def create_tier(
    api,
    center_id: str,
    tier_code: str = TierCode.TIER_1_FULL,
    surgeon_response_limit_minutes: int = 15,
    specialty_response_limit_minutes: int = 30,
    iss_threshold: int = 16,
    **overrides: Any,
) -> Dict[str, Any]:
    """Configure one activation criteria tier, acting as the center's manager."""
    payload = f.activation_tier_payload(
        tier_code=tier_code,
        surgeon_response_limit_minutes=surgeon_response_limit_minutes,
        specialty_response_limit_minutes=specialty_response_limit_minutes,
        iss_threshold=iss_threshold,
        **overrides,
    )
    return get_success_data(
        api.create_activation_tier(
            center_id, payload, make_trauma_program_manager_headers(center_id)
        )
    )


def create_case(
    api,
    center_id: str,
    activation_tier_id: str,
    mrn: str = "MRN-0001",
    arrival_at: str = "2026-07-15T08:00:00Z",
    injury_severity_score: int = 22,
    los_hours: float = 96.00,
    abstractor_user_id: str = ABSTRACTOR_1_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open one registry case, acting as an abstractor."""
    payload = f.registry_case_payload(
        center_id=center_id,
        activation_tier_id=activation_tier_id,
        mrn=mrn,
        arrival_at=arrival_at,
        injury_severity_score=injury_severity_score,
        los_hours=los_hours,
        **overrides,
    )
    return get_success_data(
        api.create_registry_case(
            payload, make_registry_abstractor_headers(abstractor_user_id)
        )
    )


def create_rule(api, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Declare one data dictionary rule."""
    return get_success_data(
        api.create_data_dictionary_rule(payload, make_system_admin_headers())
    )


def create_cycle(
    api,
    center_id: str,
    cycle_type: str = CycleType.NATIONAL_VERIFICATION,
    site_visit_date: str = "2026-10-15T13:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Open one verification cycle in PREP, acting as the center's manager."""
    payload = f.verification_cycle_payload(
        center_id=center_id,
        cycle_type=cycle_type,
        site_visit_date=site_visit_date,
        **overrides,
    )
    return get_success_data(
        api.create_verification_cycle(
            payload, make_trauma_program_manager_headers(center_id)
        )
    )


def create_pi_event(
    api,
    center_id: str,
    event_type: str = "TRANSFER_DELAY",
    severity: str = "MEDIUM",
    director_user_id: str = DIRECTOR_1_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open one PI event manually, acting as the medical director."""
    payload = f.pi_event_payload(
        center_id=center_id, event_type=event_type, severity=severity, **overrides
    )
    return get_success_data(
        api.create_pi_event(payload, make_trauma_medical_director_headers(director_user_id))
    )


def create_agreement(
    api,
    referring_center_id: str,
    receiving_center_id: str,
    effective_from: str = "2026-01-01T00:00:00Z",
    effective_to: str = "2027-01-01T00:00:00Z",
    guaranteed_acceptance_minutes: int = 30,
    **overrides: Any,
) -> Dict[str, Any]:
    """Draft one referral agreement, acting as the referring center's manager."""
    payload = f.referral_agreement_payload(
        referring_center_id=referring_center_id,
        receiving_center_id=receiving_center_id,
        effective_from=effective_from,
        effective_to=effective_to,
        guaranteed_acceptance_minutes=guaranteed_acceptance_minutes,
        **overrides,
    )
    return get_success_data(
        api.create_referral_agreement(
            payload, make_trauma_program_manager_headers(referring_center_id)
        )
    )


def activate_agreement(api, agreement: Dict[str, Any]) -> Dict[str, Any]:
    """Bring an agreement into force, acting as the guaranteeing receiving center."""
    return get_success_data(
        api.activate_referral_agreement(
            agreement["id"],
            make_trauma_program_manager_headers(agreement["receiving_center_id"]),
        )
    )


# ─── State progression: registry case and abstraction ─────


def submit_abstraction(
    api,
    case: Dict[str, Any],
    iss_abstracted: Any = 22,
    gcs_arrival: Any = 12,
    mechanism_code: Any = "FALL",
    ed_departure_at: Any = "2026-07-15T11:00:00Z",
    abstractor_user_id: str = ABSTRACTOR_1_USER_ID,
    expected_case_version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Submit one abstraction, reading the parent case version fresh when not supplied."""
    version = (
        expected_case_version
        if expected_case_version is not None
        else get_case(api, case["id"])["version"]
    )
    payload = f.abstraction_payload(
        expected_case_version=version,
        iss_abstracted=iss_abstracted,
        gcs_arrival=gcs_arrival,
        mechanism_code=mechanism_code,
        ed_departure_at=ed_departure_at,
        **overrides,
    )
    return get_success_data(
        api.create_abstraction(
            case["id"], payload, make_registry_abstractor_headers(abstractor_user_id)
        )
    )


def validate_abstraction(
    api, abstraction: Dict[str, Any], validator_user_id: str = VALIDATOR_1_USER_ID
) -> Dict[str, Any]:
    """Accept a submitted abstraction, acting as a validator who is not the submitter."""
    return get_success_data(
        api.validate_abstraction(
            abstraction["id"], make_registry_validator_headers(validator_user_id)
        )
    )


def reject_abstraction(
    api,
    abstraction: Dict[str, Any],
    rejection_reason: str = "Abstracted severity disagrees with the source chart.",
    validator_user_id: str = VALIDATOR_1_USER_ID,
) -> Dict[str, Any]:
    """Reject a submitted abstraction, reopening the case for resubmission."""
    return get_success_data(
        api.reject_abstraction(
            abstraction["id"],
            f.reject_abstraction_payload(rejection_reason),
            make_registry_validator_headers(validator_user_id),
        )
    )


def lock_case(api, case: Dict[str, Any]) -> Dict[str, Any]:
    """Lock a validated case, acting as the owning center's manager."""
    return get_success_data(
        api.lock_registry_case(
            case["id"], make_trauma_program_manager_headers(case["center_id"])
        )
    )


def triage_review(
    api,
    case: Dict[str, Any],
    triage_review_status: str = TriageReviewStatus.APPROPRIATE,
    director_user_id: str = DIRECTOR_1_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    """Adjudicate a case's triage decision, acting as the medical director."""
    return get_success_data(
        api.triage_review_case(
            case["id"],
            f.triage_review_payload(triage_review_status, **overrides),
            make_trauma_medical_director_headers(director_user_id),
        )
    )


def record_transfer_out(
    api, case: Dict[str, Any], receiving_center_id: str
) -> Dict[str, Any]:
    """Record a transfer-out, acting as the referring center's manager."""
    return get_success_data(
        api.record_transfer_out(
            case["id"],
            f.transfer_out_payload(receiving_center_id),
            make_trauma_program_manager_headers(case["center_id"]),
        )
    )


def rescind_transfer_out(
    api,
    case: Dict[str, Any],
    rescind_reason: str = "Receiving center refused the patient; the transfer never occurred.",
) -> Dict[str, Any]:
    """Rescind a recorded transfer-out, acting as the owning center's manager."""
    return get_success_data(
        api.rescind_transfer_out(
            case["id"],
            f.rescind_transfer_out_payload(rescind_reason),
            make_trauma_program_manager_headers(case["center_id"]),
        )
    )


def log_response(
    api,
    case: Dict[str, Any],
    responder_role: str = ResponderRole.SURGEON,
    responder_user_id: str = "u_surgeon_1",
    notified_at: str = "2026-07-15T08:00:00Z",
    arrived_at: Any = "2026-07-15T08:12:00Z",
    abstractor_user_id: str = ABSTRACTOR_1_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    """Document one responder against a case."""
    payload = f.response_log_payload(
        responder_role=responder_role,
        responder_user_id=responder_user_id,
        notified_at=notified_at,
        arrived_at=arrived_at,
        **overrides,
    )
    return get_success_data(
        api.create_response_log(
            case["id"], payload, make_registry_abstractor_headers(abstractor_user_id)
        )
    )


# ─── State progression: PI loop ───────────────────────────


def start_pi_review(
    api, event: Dict[str, Any], director_user_id: str = DIRECTOR_1_USER_ID
) -> Dict[str, Any]:
    """Move an event into multidisciplinary review."""
    return get_success_data(
        api.start_pi_review(
            event["id"], make_trauma_medical_director_headers(director_user_id)
        )
    )


def attach_action(
    api,
    event: Dict[str, Any],
    action_type: str = "EDUCATION",
    owner_user_id: str = "u_owner_1",
    due_at: str = "2026-09-01T00:00:00Z",
    director_user_id: str = DIRECTOR_1_USER_ID,
    **overrides: Any,
) -> Dict[str, Any]:
    """Attach one corrective action, advancing the event to ACTION_PLANNED."""
    payload = f.corrective_action_payload(
        action_type=action_type, owner_user_id=owner_user_id, due_at=due_at, **overrides
    )
    return get_success_data(
        api.create_corrective_action(
            event["id"], payload, make_trauma_medical_director_headers(director_user_id)
        )
    )


def complete_action(
    api,
    action: Dict[str, Any],
    completion_note: str = "Corrective action delivered and documented.",
    director_user_id: str = DIRECTOR_1_USER_ID,
) -> Dict[str, Any]:
    """Record completion of a corrective action."""
    return get_success_data(
        api.complete_corrective_action(
            action["id"],
            make_trauma_medical_director_headers(director_user_id),
            f.complete_action_payload(completion_note),
        )
    )


def verify_action(
    api, action: Dict[str, Any], reviewer_user_id: str = REVIEWER_1_USER_ID
) -> Dict[str, Any]:
    """Verify a completed corrective action, acting as someone other than its owner."""
    return get_success_data(
        api.verify_corrective_action(
            action["id"], make_verification_reviewer_headers(reviewer_user_id)
        )
    )


def close_loop(
    api,
    event: Dict[str, Any],
    loop_closure_note: str = "Loop closed: every corrective action verified.",
    director_user_id: str = DIRECTOR_1_USER_ID,
) -> Dict[str, Any]:
    """Document loop closure on an event whose actions are all verified."""
    return get_success_data(
        api.close_pi_loop(
            event["id"],
            f.close_loop_payload(loop_closure_note),
            make_trauma_medical_director_headers(director_user_id),
        )
    )


def reopen_loop(
    api,
    event: Dict[str, Any],
    reopen_reason: str = "Recurrence found in the following month's audit.",
    reviewer_user_id: str = REVIEWER_1_USER_ID,
) -> Dict[str, Any]:
    """Reopen a closed loop, acting as the verification reviewer."""
    return get_success_data(
        api.reopen_pi_event(
            event["id"],
            f.reopen_payload(reopen_reason),
            make_verification_reviewer_headers(reviewer_user_id),
        )
    )


# ─── State progression: verification cycle ────────────────


def book_surveyor(
    api,
    cycle: Dict[str, Any],
    surveyor_user_id: str = SURVEYOR_1,
    window_start: str = "2026-09-10T08:00:00Z",
    window_end: str = "2026-09-10T17:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Book a surveyor window, acting as the authority that matches the cycle type."""
    payload = f.surveyor_booking_payload(
        surveyor_user_id=surveyor_user_id,
        window_start=window_start,
        window_end=window_end,
        **overrides,
    )
    return get_success_data(
        api.create_surveyor_booking(
            cycle["id"], payload, authority_headers(cycle["cycle_type"])
        )
    )


def submit_cycle(api, cycle: Dict[str, Any]) -> Dict[str, Any]:
    """Submit a prepared cycle, acting as the owning center's manager."""
    return get_success_data(
        api.submit_verification_cycle(
            cycle["id"], make_trauma_program_manager_headers(cycle["center_id"])
        )
    )


def schedule_site_visit(
    api, cycle: Dict[str, Any], site_visit_date: Optional[str] = None
) -> Dict[str, Any]:
    """Confirm the site visit date of a submitted cycle."""
    payload = f.schedule_site_visit_payload(site_visit_date or cycle["site_visit_date"])
    return get_success_data(
        api.schedule_site_visit(
            cycle["id"], payload, authority_headers(cycle["cycle_type"])
        )
    )


def begin_review(api, cycle: Dict[str, Any]) -> Dict[str, Any]:
    """Open deliberation after the site visit."""
    return get_success_data(
        api.begin_cycle_review(cycle["id"], authority_headers(cycle["cycle_type"]))
    )


def decide_cycle(
    api,
    cycle: Dict[str, Any],
    decision: str = Decision.VERIFIED,
    decision_effective_date: str = "2026-11-01T00:00:00Z",
) -> Dict[str, Any]:
    """Render a decision on a cycle under review."""
    return get_success_data(
        api.decide_verification_cycle(
            cycle["id"],
            f.decide_payload(decision, decision_effective_date),
            authority_headers(cycle["cycle_type"]),
        )
    )


# ─── State progression: criteria deficiency ───────────────


def record_deficiency(
    api,
    cycle: Dict[str, Any],
    criterion_code: str = "CD-05-13",
    deficiency_class: str = DeficiencyClass.TYPE_II_MAJOR,
    remediation_due_at: str = "2026-09-30T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Record one criteria deficiency, acting as the matching reviewing authority."""
    payload = f.criteria_deficiency_payload(
        criterion_code=criterion_code,
        deficiency_class=deficiency_class,
        remediation_due_at=remediation_due_at,
        **overrides,
    )
    return get_success_data(
        api.create_criteria_deficiency(
            cycle["id"], payload, authority_headers(cycle["cycle_type"])
        )
    )


def submit_remediation(
    api,
    cycle: Dict[str, Any],
    deficiency: Dict[str, Any],
    remediation_note: str = "Remediation evidence attached for reviewer acceptance.",
    expected_cycle_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Submit a remediation packet, reading the parent cycle version fresh when needed."""
    version = (
        expected_cycle_version
        if expected_cycle_version is not None
        else get_cycle(api, cycle["id"])["version"]
    )
    return get_success_data(
        api.submit_remediation(
            deficiency["id"],
            f.remediation_payload(version, remediation_note),
            make_trauma_program_manager_headers(cycle["center_id"]),
        )
    )


def close_deficiency(
    api, cycle: Dict[str, Any], deficiency: Dict[str, Any]
) -> Dict[str, Any]:
    """Accept remediation and close a deficiency."""
    return get_success_data(
        api.close_criteria_deficiency(
            deficiency["id"], authority_headers(cycle["cycle_type"])
        )
    )


def escalate_deficiency(
    api,
    cycle: Dict[str, Any],
    deficiency: Dict[str, Any],
    escalation_reason: str = "Remediation evidence did not arrive before the deadline.",
) -> Dict[str, Any]:
    """Escalate an unremediated deficiency."""
    return get_success_data(
        api.escalate_criteria_deficiency(
            deficiency["id"],
            f.escalate_payload(escalation_reason),
            authority_headers(cycle["cycle_type"]),
        )
    )


# ─── State progression: outreach activity ─────────────────


def log_outreach(
    api,
    center_id: str,
    activity_kind: str = ActivityKind.INJURY_PREVENTION,
    event_date: str = "2026-06-14T00:00:00Z",
    credit_hours: float = 1.15,
    audience_count: int = 60,
    **overrides: Any,
) -> Dict[str, Any]:
    """Log one outreach activity, acting as the center's manager."""
    payload = f.outreach_activity_payload(
        activity_kind=activity_kind,
        event_date=event_date,
        credit_hours=credit_hours,
        audience_count=audience_count,
        **overrides,
    )
    return get_success_data(
        api.create_outreach_activity(
            center_id, payload, make_trauma_program_manager_headers(center_id)
        )
    )


def verify_outreach(
    api, activity: Dict[str, Any], director_user_id: str = DIRECTOR_1_USER_ID
) -> Dict[str, Any]:
    """Verify a logged outreach activity so it enters the credit ledger."""
    return get_success_data(
        api.verify_outreach_activity(
            activity["id"], make_trauma_medical_director_headers(director_user_id)
        )
    )


def reject_outreach(
    api,
    activity: Dict[str, Any],
    rejection_reason: str = "Attendance roster could not be produced for audit.",
    director_user_id: str = DIRECTOR_1_USER_ID,
) -> Dict[str, Any]:
    """Reject a logged or verified outreach activity, recomputing the ledger."""
    return get_success_data(
        api.reject_outreach_activity(
            activity["id"],
            f.reject_outreach_payload(rejection_reason),
            make_trauma_medical_director_headers(director_user_id),
        )
    )


# ─── Entity hierarchy ─────────────────────────────────────


def center_with_tier(
    api,
    name: str = "Riverbend Trauma",
    state_code: str = "NE",
    designation_level: str = DesignationLevel.LEVEL_II,
    tier_code: str = TierCode.TIER_1_FULL,
    surgeon_response_limit_minutes: int = 15,
    specialty_response_limit_minutes: int = 30,
    iss_threshold: int = 16,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A registered center with exactly one activation tier configured."""
    center = create_center(
        api, name=name, state_code=state_code, designation_level=designation_level
    )
    tier = create_tier(
        api,
        center["id"],
        tier_code=tier_code,
        surgeon_response_limit_minutes=surgeon_response_limit_minutes,
        specialty_response_limit_minutes=specialty_response_limit_minutes,
        iss_threshold=iss_threshold,
    )
    return center, tier


def center_with_all_tiers(
    api,
    name: str = "Riverbend Trauma",
    state_code: str = "NE",
    designation_level: str = DesignationLevel.LEVEL_I,
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """A registered center carrying all three activation tiers, keyed by tier code."""
    center = create_center(
        api, name=name, state_code=state_code, designation_level=designation_level
    )
    tiers = {
        TierCode.TIER_1_FULL: create_tier(
            api,
            center["id"],
            tier_code=TierCode.TIER_1_FULL,
            surgeon_response_limit_minutes=15,
            specialty_response_limit_minutes=30,
            iss_threshold=16,
        ),
        TierCode.TIER_2_MODIFIED: create_tier(
            api,
            center["id"],
            tier_code=TierCode.TIER_2_MODIFIED,
            surgeon_response_limit_minutes=30,
            specialty_response_limit_minutes=60,
            iss_threshold=9,
        ),
        TierCode.TIER_3_CONSULT: create_tier(
            api,
            center["id"],
            tier_code=TierCode.TIER_3_CONSULT,
            surgeon_response_limit_minutes=60,
            specialty_response_limit_minutes=120,
            iss_threshold=0,
        ),
    }
    return center, tiers


def referral_pair(
    api,
    referring_name: str = "Rockvale Trauma",
    receiving_name: str = "Metro Regional Trauma",
    state_code: str = "OH",
    effective_from: str = "2026-01-01T00:00:00Z",
    effective_to: str = "2027-01-01T00:00:00Z",
    activate: bool = True,
    tier_code: str = TierCode.TIER_1_FULL,
    surgeon_response_limit_minutes: int = 15,
    specialty_response_limit_minutes: int = 30,
    iss_threshold: int = 16,
) -> Dict[str, Any]:
    """Two centers on one directed pair, with a tier on the referring center.

    Returns ``{"referring", "receiving", "tier", "agreement"}``. The agreement is left
    DRAFT when ``activate`` is false, which is the shape a transfer-out gate test wants.
    """
    referring, tier = center_with_tier(
        api,
        name=referring_name,
        state_code=state_code,
        designation_level=DesignationLevel.LEVEL_III,
        tier_code=tier_code,
        surgeon_response_limit_minutes=surgeon_response_limit_minutes,
        specialty_response_limit_minutes=specialty_response_limit_minutes,
        iss_threshold=iss_threshold,
    )
    receiving = create_center(
        api,
        name=receiving_name,
        state_code=state_code,
        designation_level=DesignationLevel.LEVEL_I,
    )
    agreement = create_agreement(
        api,
        referring["id"],
        receiving["id"],
        effective_from=effective_from,
        effective_to=effective_to,
    )
    if activate:
        agreement = activate_agreement(api, agreement)
    return {
        "referring": referring,
        "receiving": receiving,
        "tier": tier,
        "agreement": agreement,
    }


# ─── Lifecycle shortcuts ──────────────────────────────────


def case_abstracted(
    api, center_id: str, tier_id: str, mrn: str = "MRN-0001", **case_kwargs: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A case walked to ABSTRACTED with one SUBMITTED abstraction record."""
    abstraction_kwargs = {
        key: case_kwargs.pop(key)
        for key in ("iss_abstracted", "gcs_arrival", "mechanism_code", "ed_departure_at")
        if key in case_kwargs
    }
    case = create_case(api, center_id, tier_id, mrn=mrn, **case_kwargs)
    abstraction = submit_abstraction(api, case, **abstraction_kwargs)
    return get_case(api, case["id"]), abstraction


def case_validated(
    api, center_id: str, tier_id: str, mrn: str = "MRN-0001", **case_kwargs: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A case walked to VALIDATED, its abstraction adjudicated by a second person."""
    case, abstraction = case_abstracted(api, center_id, tier_id, mrn=mrn, **case_kwargs)
    validate_abstraction(api, abstraction)
    return get_case(api, case["id"]), get_abstraction(api, case["id"], abstraction["id"])


def case_locked(
    api, center_id: str, tier_id: str, mrn: str = "MRN-0001", **case_kwargs: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A case walked all the way to LOCKED."""
    case, abstraction = case_validated(api, center_id, tier_id, mrn=mrn, **case_kwargs)
    lock_case(api, case)
    return get_case(api, case["id"]), get_abstraction(api, case["id"], abstraction["id"])


def pi_loop_at_action_planned(
    api,
    center_id: str,
    event_type: str = "TRANSFER_DELAY",
    severity: str = "MEDIUM",
    action_type: str = "EDUCATION",
    owner_user_id: str = "u_owner_1",
    due_at: str = "2026-09-01T00:00:00Z",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A manual PI event walked IDENTIFIED to ACTION_PLANNED with one open action."""
    event = create_pi_event(api, center_id, event_type=event_type, severity=severity)
    start_pi_review(api, event)
    action = attach_action(
        api, event, action_type=action_type, owner_user_id=owner_user_id, due_at=due_at
    )
    return get_event(api, event["id"]), action


def pi_loop_with_verified_action(
    api,
    center_id: str,
    event_type: str = "TRANSFER_DELAY",
    severity: str = "MEDIUM",
    action_type: str = "EDUCATION",
    owner_user_id: str = "u_owner_1",
    due_at: str = "2026-09-01T00:00:00Z",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A PI event at ACTION_PLANNED whose only corrective action is VERIFIED."""
    event, action = pi_loop_at_action_planned(
        api,
        center_id,
        event_type=event_type,
        severity=severity,
        action_type=action_type,
        owner_user_id=owner_user_id,
        due_at=due_at,
    )
    complete_action(api, action)
    verify_action(api, action)
    return get_event(api, event["id"]), get_corrective_action(api, event["id"], action["id"])


def pi_loop_closed(
    api,
    center_id: str,
    event_type: str = "TRANSFER_DELAY",
    severity: str = "MEDIUM",
    action_type: str = "EDUCATION",
    owner_user_id: str = "u_owner_1",
    due_at: str = "2026-09-01T00:00:00Z",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A PI event walked all the way to LOOP_CLOSED."""
    event, action = pi_loop_with_verified_action(
        api,
        center_id,
        event_type=event_type,
        severity=severity,
        action_type=action_type,
        owner_user_id=owner_user_id,
        due_at=due_at,
    )
    close_loop(api, event)
    return get_event(api, event["id"]), get_corrective_action(api, event["id"], action["id"])


def cycle_submitted(
    api,
    center_id: str,
    cycle_type: str = CycleType.NATIONAL_VERIFICATION,
    site_visit_date: str = "2026-10-15T13:00:00Z",
) -> Dict[str, Any]:
    """A cycle opened in PREP and submitted for review."""
    cycle = create_cycle(
        api, center_id, cycle_type=cycle_type, site_visit_date=site_visit_date
    )
    submit_cycle(api, cycle)
    return get_cycle(api, cycle["id"])


def cycle_under_review(
    api,
    center_id: str,
    cycle_type: str = CycleType.NATIONAL_VERIFICATION,
    site_visit_date: str = "2026-10-20T13:00:00Z",
    surveyor_user_id: str = SURVEYOR_1,
    window_start: str = "2026-10-20T08:00:00Z",
    window_end: str = "2026-10-20T17:00:00Z",
) -> Dict[str, Any]:
    """A cycle walked PREP to SUBMITTED to SITE_VISIT_SCHEDULED to UNDER_REVIEW.

    One surveyor booking is created while the cycle is SUBMITTED, which is what the
    scheduling and deliberation steps both require.
    """
    cycle = cycle_submitted(
        api, center_id, cycle_type=cycle_type, site_visit_date=site_visit_date
    )
    book_surveyor(
        api,
        cycle,
        surveyor_user_id=surveyor_user_id,
        window_start=window_start,
        window_end=window_end,
    )
    schedule_site_visit(api, cycle, site_visit_date)
    begin_review(api, cycle)
    return get_cycle(api, cycle["id"])


# ─── Accumulation and threshold targeting ─────────────────


def build_cases(
    api, center_id: str, specs: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Open a cohort of cases from a list of per-case specifications.

    Each spec carries ``activation_tier_id``, ``mrn``, ``arrival_at``,
    ``injury_severity_score`` and ``los_hours``; anything else is passed through.
    """
    cases = []
    for spec in specs:
        spec = dict(spec)
        tier_id = spec.pop("activation_tier_id")
        cases.append(create_case(api, center_id, tier_id, **spec))
    return cases


def record_deficiencies(
    api, cycle: Dict[str, Any], specs: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Record several deficiencies on one cycle, in the order supplied."""
    return [record_deficiency(api, cycle, **spec) for spec in specs]


def deficiencies_of_class(
    api,
    cycle: Dict[str, Any],
    criterion_codes: List[str],
    deficiency_class: str = DeficiencyClass.TYPE_I_CRITICAL,
    remediation_due_at: str = "2026-09-30T00:00:00Z",
) -> List[Dict[str, Any]]:
    """Record one deficiency of the same class per supplied criterion code."""
    return [
        record_deficiency(
            api,
            cycle,
            criterion_code=code,
            deficiency_class=deficiency_class,
            remediation_due_at=remediation_due_at,
        )
        for code in criterion_codes
    ]


def verified_outreach_ledger(
    api, center_id: str, specs: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Log and then verify a run of outreach activities, in the order supplied.

    Because each activity is quantized to the nearest quarter hour before it enters the
    ledger, the order of the calls is observable in the running total.
    """
    activities = []
    for spec in specs:
        activity = log_outreach(api, center_id, **spec)
        verify_outreach(api, activity)
        activities.append(get_outreach_activity(api, center_id, activity["id"]))
    return activities


def center_with_national_denial(
    api,
    name: str = "Stonebridge Trauma",
    state_code: str = "WV",
    site_visit_date: str = "2026-10-20T13:00:00Z",
) -> Dict[str, Any]:
    """A center whose national cycle was DENIED, so its posture is SUSPENDED.

    Returns ``{"center", "cycle"}`` with both re-read after the decision.
    """
    center = create_center(api, name=name, state_code=state_code)
    cycle = cycle_under_review(
        api,
        center["id"],
        cycle_type=CycleType.NATIONAL_VERIFICATION,
        site_visit_date=site_visit_date,
        window_start="2026-10-20T08:00:00Z",
        window_end="2026-10-20T17:00:00Z",
    )
    decide_cycle(api, cycle, decision=Decision.DENIED)
    return {"center": get_center(api, center["id"]), "cycle": get_cycle(api, cycle["id"])}
