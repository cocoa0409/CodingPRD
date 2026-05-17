"""Composite setup helpers — multi-step preambles that tests reuse.

The clinical workflow is long: anchor clock -> create Therapist with
ACTIVE license + ACTIVE credential -> (optional Supervisor +
SupervisionAssignment for PRE_LICENSED) -> create Patient (self-pay or
insured) -> schedule Appointment -> advance clock into check-in window
-> check-in -> create Session -> complete Session (auto-posts
BillingClaim). Most interesting test claims need the system in a
late-pipeline state, and several difficulty-design instances demand
cross-entity state combos that require dozens of API calls to
construct.

IDENTITY THREADING — PRD §2.1.

- Therapist is ENTITY-BACKED. Every Therapist-driven call whose
  success depends on owning the targeted resource MUST mint headers
  via make_therapist_headers(therapist["id"]) — never via the shared
  THERAPIST_FALLBACK_ID constant. Fixtures here remember the actual
  Therapist.id of the acting clinician and pass it through to
  ownership-gated calls (creating a session under their own
  appointment, completing that session, recording a crisis assessment,
  authoring a safety plan, scheduling their own appointments).

- Supervisor is ENTITY-BACKED. Every Supervisor-driven GET call uses
  make_supervisor_headers(supervisor["id"]).

Setup helpers use get_success_data (a lenient 2xx validator), so a
failed setup surfaces as "Setup failed" rather than a confusing test
assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CRISIS_LOOKBACK_DAYS,
    REQUIRED_HOURS_FOR_LICENSURE,
    TEST_DEFAULTS,
)
from .factories import (
    clock_advance_payload,
    create_appointment_payload,
    create_crisis_assessment_payload,
    create_insurance_plan_payload,
    create_patient_payload,
    create_safety_plan_payload,
    create_session_payload,
    create_state_license_payload,
    create_supervision_assignment_payload,
    create_supervisor_payload,
    create_therapist_payload,
    iso_anchor_offset,
    iso_midnight,
    parse_anchor,
    parse_iso,
    patch_patient_payload,
)
from .test_users import (
    TEST_USERS,
    make_supervisor_headers,
    make_therapist_headers,
)


# ===========================================================================
# Clock helpers — PRD §2.8.
# ===========================================================================
def anchor_clock() -> Dict[str, Any]:
    """Pin the deterministic clock to the test anchor.

    PRD §2.8: 'The clock is read via a read-only capability and
    advanced via an admin-only test-driving capability that accepts a
    target instant to in ISO 8601 UTC.'
    """
    resp = api_client.clock_advance(
        clock_advance_payload(to=TEST_DEFAULTS["CLOCK_ANCHOR"]),
        TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def advance_clock_to(iso_timestamp: str) -> Dict[str, Any]:
    """POST /practice/_clock/advance with an absolute target."""
    resp = api_client.clock_advance(
        clock_advance_payload(to=iso_timestamp),
        TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Therapists — PRD §3.1 / §3.2.
# ===========================================================================
def create_therapist(*,
                     supervision_track: str = "LICENSED",
                     psypact_enrolled: Optional[bool] = None,
                     full_name: str = "Dr. Test Therapist",
                     pricing_rack_90791_cents: Optional[int] = None,
                     pricing_rack_90834_cents: Optional[int] = None,
                     ) -> Dict[str, Any]:
    """POST /practice/therapists as PracticeAdmin."""
    payload = create_therapist_payload(
        supervision_track=supervision_track,
        psypact_enrolled=psypact_enrolled,
        full_name=full_name,
        pricing_rack_90791_cents=pricing_rack_90791_cents,
        pricing_rack_90834_cents=pricing_rack_90834_cents,
    )
    resp = api_client.create_therapist(
        payload, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def create_state_license(therapist_id: str, *,
                         state_code: str = "NY",
                         issued_on: Optional[str] = None,
                         expires_on: Optional[str] = None,
                         license_number: Optional[str] = None,
                         ) -> Dict[str, Any]:
    """POST /practice/therapists/{tid}/licenses as PracticeAdmin."""
    payload = create_state_license_payload(
        state_code=state_code,
        issued_on=issued_on,
        expires_on=expires_on,
        license_number=license_number,
    )
    resp = api_client.create_state_license(
        therapist_id, payload, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def verify_state_license(therapist_id: str, license_id: str
                         ) -> Dict[str, Any]:
    """POST /practice/therapists/{tid}/licenses/{id}/verify as
    PracticeAdmin. Transitions PENDING -> ACTIVE."""
    resp = api_client.verify_state_license(
        therapist_id, license_id, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def revoke_state_license(therapist_id: str, license_id: str
                         ) -> Dict[str, Any]:
    """POST /practice/therapists/{tid}/licenses/{id}/revoke as
    PracticeAdmin. Transitions ACTIVE -> REVOKED."""
    resp = api_client.revoke_state_license(
        therapist_id, license_id, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def activate_therapist(therapist_id: str) -> Dict[str, Any]:
    """POST /practice/therapists/{id}/activate as PracticeAdmin."""
    resp = api_client.activate_therapist(
        therapist_id, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def suspend_therapist(therapist_id: str) -> Dict[str, Any]:
    """POST /practice/therapists/{id}/suspend as PracticeAdmin."""
    resp = api_client.suspend_therapist(
        therapist_id, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def reinstate_therapist(therapist_id: str) -> Dict[str, Any]:
    """POST /practice/therapists/{id}/reinstate as PracticeAdmin."""
    resp = api_client.reinstate_therapist(
        therapist_id, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def re_get_therapist(therapist_id: str) -> Dict[str, Any]:
    """GET /practice/therapists/{id} as PracticeAdmin."""
    resp = api_client.get_therapist(
        therapist_id, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def setup_active_licensed_therapist(*,
                                    state_code: str = "NY",
                                    psypact_enrolled: bool = False,
                                    license_expires_on: Optional[
                                        str] = None,
                                    pricing_rack_90791_cents: Optional[
                                        int] = None,
                                    pricing_rack_90834_cents: Optional[
                                        int] = None,
                                    ) -> Tuple[Dict[str, Any],
                                               Dict[str, Any]]:
    """Build: Therapist (LICENSED) -> StateLicense PENDING -> verified to
    ACTIVE -> Therapist activated to ACTIVE.

    Returns (therapist, license).
    """
    therapist = create_therapist(
        supervision_track="LICENSED",
        psypact_enrolled=psypact_enrolled,
        pricing_rack_90791_cents=pricing_rack_90791_cents,
        pricing_rack_90834_cents=pricing_rack_90834_cents,
    )
    license_ = create_state_license(
        therapist["id"],
        state_code=state_code,
        expires_on=license_expires_on,
    )
    license_ = verify_state_license(therapist["id"], license_["id"])
    therapist = activate_therapist(therapist["id"])
    return therapist, license_


def setup_pre_licensed_therapist_with_supervision(
    *,
    state_code: str = "NY",
    psypact_enrolled: bool = False,
    license_expires_on: Optional[str] = None,
    pricing_rack_90791_cents: Optional[int] = None,
    pricing_rack_90834_cents: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any],
           Dict[str, Any], Dict[str, Any]]:
    """Build a PRE_LICENSED therapist who is permitted to run sessions:
    create therapist -> create + verify ACTIVE NY license -> create
    Supervisor -> create ACTIVE SupervisionAssignment.

    The therapist is left in credential_status=PROVISIONAL. PRD §3.6
    permits PROVISIONAL pre-licensed associates to check in and run
    sessions provided their supervision assignment is ACTIVE at the
    relevant moment (PRD §3.7).

    Returns (therapist, license, supervisor, assignment).
    """
    therapist = create_therapist(
        supervision_track="PRE_LICENSED",
        psypact_enrolled=psypact_enrolled,
        pricing_rack_90791_cents=pricing_rack_90791_cents,
        pricing_rack_90834_cents=pricing_rack_90834_cents,
    )
    license_ = create_state_license(
        therapist["id"],
        state_code=state_code,
        expires_on=license_expires_on,
    )
    license_ = verify_state_license(therapist["id"], license_["id"])
    supervisor = create_supervisor(home_state_code=state_code)
    assignment = create_supervision_assignment(
        therapist_id=therapist["id"],
        supervisor_id=supervisor["id"],
    )
    return therapist, license_, supervisor, assignment


# ===========================================================================
# Supervisors — PRD §3.3.
# ===========================================================================
def create_supervisor(*,
                      full_name: str = "Dr. Test Supervisor",
                      home_state_code: str = "NY",
                      active: Optional[bool] = None,
                      ) -> Dict[str, Any]:
    """POST /practice/supervisors as PracticeAdmin."""
    payload = create_supervisor_payload(
        full_name=full_name,
        home_state_code=home_state_code,
        active=active,
    )
    resp = api_client.create_supervisor(
        payload, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def create_supervision_assignment(*,
                                  therapist_id: str,
                                  supervisor_id: str,
                                  started_on: Optional[str] = None,
                                  ) -> Dict[str, Any]:
    """POST /practice/supervision-assignments as PracticeAdmin."""
    payload = create_supervision_assignment_payload(
        therapist_id=therapist_id,
        supervisor_id=supervisor_id,
        started_on=started_on,
    )
    resp = api_client.create_supervision_assignment(
        payload, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def terminate_supervision_assignment(assignment_id: str
                                     ) -> Dict[str, Any]:
    """POST /practice/supervision-assignments/{id}/terminate as
    PracticeAdmin."""
    resp = api_client.terminate_supervision_assignment(
        assignment_id, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Patients & insurance — PRD §3.4 / §3.5.
# ===========================================================================
def create_insurance_plan(*,
                          network_status: str = "IN_NETWORK",
                          contract_mode: str = "DEDUCTIBLE_FIRST",
                          allowed_amount_90791_cents: Optional[int] = None,
                          allowed_amount_90834_cents: Optional[int] = None,
                          copay_cents: Optional[int] = None,
                          payer_name: str = "Aetna",
                          ) -> Dict[str, Any]:
    """POST /practice/insurance-plans as PracticeAdmin."""
    payload = create_insurance_plan_payload(
        network_status=network_status,
        contract_mode=contract_mode,
        allowed_amount_90791_cents=allowed_amount_90791_cents,
        allowed_amount_90834_cents=allowed_amount_90834_cents,
        copay_cents=copay_cents,
        payer_name=payer_name,
    )
    resp = api_client.create_insurance_plan(
        payload, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def create_patient(*,
                   state_of_residence: str = "NY",
                   household_income_cents: int = 3_000_000,
                   household_size: int = 2,
                   insurance_plan_id: Optional[str] = None,
                   full_name: str = "Test Patient",
                   ) -> Dict[str, Any]:
    """POST /practice/patients as PracticeAdmin."""
    payload = create_patient_payload(
        state_of_residence=state_of_residence,
        household_income_cents=household_income_cents,
        household_size=household_size,
        insurance_plan_id=insurance_plan_id,
        full_name=full_name,
    )
    resp = api_client.create_patient(
        payload, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def patch_patient_deductible(patient_id: str,
                             deductible_remaining_cents: int,
                             ) -> Dict[str, Any]:
    """PATCH /practice/patients/{id} as PracticeAdmin — set the
    deductible to the supplied value. PRD §3.4 admits PATCH-set of
    deductible_remaining_cents for year-end resets."""
    payload = patch_patient_payload(
        deductible_remaining_cents=deductible_remaining_cents,
    )
    resp = api_client.patch_patient(
        patient_id, payload, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def re_get_patient(patient_id: str) -> Dict[str, Any]:
    """GET /practice/patients/{id} as PracticeAdmin."""
    resp = api_client.get_patient(
        patient_id, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Appointments — PRD §3.6.
# ===========================================================================
def schedule_appointment(therapist_id: str, patient_id: str, *,
                         cpt_code: str = "90834",
                         modality: str = "IN_PERSON",
                         patient_state_on_day: str = "NY",
                         scheduled_start: Optional[str] = None,
                         scheduled_end: Optional[str] = None,
                         ) -> Dict[str, Any]:
    """POST /practice/appointments as the acting therapist.

    PRD §2.1 / §3.6: Therapist may schedule; ownership applies to the
    therapist_id foreign key. We mint Therapist headers from the actual
    therapist's id so the call is acted as the owning clinician.
    """
    payload = create_appointment_payload(
        therapist_id=therapist_id,
        patient_id=patient_id,
        cpt_code=cpt_code,
        modality=modality,
        patient_state_on_day=patient_state_on_day,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    resp = api_client.create_appointment(
        payload, make_therapist_headers(therapist_id),
    )
    return get_success_data(resp)


def schedule_appointment_as_admin(therapist_id: str, patient_id: str, *,
                                  cpt_code: str = "90834",
                                  modality: str = "IN_PERSON",
                                  patient_state_on_day: str = "NY",
                                  scheduled_start: Optional[str] = None,
                                  scheduled_end: Optional[str] = None,
                                  ) -> Dict[str, Any]:
    """POST /practice/appointments as PracticeAdmin (opaque)."""
    payload = create_appointment_payload(
        therapist_id=therapist_id,
        patient_id=patient_id,
        cpt_code=cpt_code,
        modality=modality,
        patient_state_on_day=patient_state_on_day,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
    )
    resp = api_client.create_appointment(
        payload, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def checkin_appointment(appointment_id: str, therapist_id: str
                        ) -> Dict[str, Any]:
    """POST /practice/appointments/{id}/check-in as the acting
    therapist (ownership: therapist_id)."""
    resp = api_client.checkin_appointment(
        appointment_id, make_therapist_headers(therapist_id),
    )
    return get_success_data(resp)


def cancel_appointment(appointment_id: str, therapist_id: str
                       ) -> Dict[str, Any]:
    """POST /practice/appointments/{id}/cancel as the acting therapist."""
    resp = api_client.cancel_appointment(
        appointment_id, make_therapist_headers(therapist_id),
    )
    return get_success_data(resp)


def create_session(appointment_id: str, therapist_id: str, *,
                   actual_duration_minutes: int = 45,
                   ) -> Dict[str, Any]:
    """POST /practice/appointments/{id}/sessions as the acting therapist
    (PRD §4 lists this as Therapist-only)."""
    payload = create_session_payload(
        actual_duration_minutes=actual_duration_minutes,
    )
    resp = api_client.create_session(
        appointment_id, payload, make_therapist_headers(therapist_id),
    )
    return get_success_data(resp)


def complete_session(session_id: str, therapist_id: str) -> Dict[str, Any]:
    """POST /practice/sessions/{id}/complete as the acting therapist
    (PRD §4 lists this as Therapist-only)."""
    resp = api_client.complete_session(
        session_id, make_therapist_headers(therapist_id),
    )
    return get_success_data(resp)


def void_session(session_id: str) -> Dict[str, Any]:
    """POST /practice/sessions/{id}/void as PracticeAdmin."""
    resp = api_client.void_session(
        session_id, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def re_get_appointment(appointment_id: str) -> Dict[str, Any]:
    """GET /practice/appointments/{id} as PracticeAdmin."""
    resp = api_client.get_appointment(
        appointment_id, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def re_get_session(session_id: str) -> Dict[str, Any]:
    """GET /practice/sessions/{id} as PracticeAdmin."""
    resp = api_client.get_session(
        session_id, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


def re_get_claim(claim_id: str) -> Dict[str, Any]:
    """GET /practice/claims/{id} as PracticeAdmin."""
    resp = api_client.get_claim(
        claim_id, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Claim void — PRD §3.8.
# ===========================================================================
def void_claim(claim_id: str) -> Dict[str, Any]:
    """POST /practice/claims/{id}/void as PracticeAdmin."""
    resp = api_client.void_claim(
        claim_id, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Crisis assessments + safety plans — PRD §3.9.
# ===========================================================================
def create_crisis_assessment(patient_id: str, therapist_id: str, *,
                             si_score: int = 0,
                             pa_score: int = 0,
                             su_score: int = 0,
                             so_score: int = 0,
                             am_score: int = 0,
                             ) -> Dict[str, Any]:
    """POST /practice/patients/{pid}/crisis-assessments as the acting
    therapist. PRD §3.9 ties authorisation to a recent care
    relationship; we mint Therapist headers from the acting therapist's
    id so the ownership-gated call is acted as the owning clinician."""
    payload = create_crisis_assessment_payload(
        therapist_id=therapist_id,
        si_score=si_score,
        pa_score=pa_score,
        su_score=su_score,
        so_score=so_score,
        am_score=am_score,
    )
    resp = api_client.create_crisis_assessment(
        patient_id, payload, make_therapist_headers(therapist_id),
    )
    return get_success_data(resp)


def create_safety_plan(patient_id: str, therapist_id: str,
                       trigger_assessment_id: str, *,
                       support_contacts: Optional[
                           List[Dict[str, str]]] = None,
                       warning_signs: str = "Test warning signs.",
                       coping_strategies: str = "Test coping strategies.",
                       crisis_hotline: str = "988",
                       means_restriction_plan: str = (
                           "Remove access to means."
                       ),
                       ) -> Dict[str, Any]:
    """POST /practice/patients/{pid}/safety-plans as the acting
    therapist."""
    payload = create_safety_plan_payload(
        trigger_assessment_id=trigger_assessment_id,
        warning_signs=warning_signs,
        coping_strategies=coping_strategies,
        support_contacts=support_contacts,
        crisis_hotline=crisis_hotline,
        means_restriction_plan=means_restriction_plan,
    )
    resp = api_client.create_safety_plan(
        patient_id, payload, make_therapist_headers(therapist_id),
    )
    return get_success_data(resp)


def rescind_safety_plan(plan_id: str) -> Dict[str, Any]:
    """POST /practice/safety-plans/{id}/rescind as PracticeAdmin."""
    resp = api_client.rescind_safety_plan(
        plan_id, TEST_USERS["practice_admin_headers"],
    )
    return get_success_data(resp)


# ===========================================================================
# Multi-step composites — Tier 1 / 2: state progression + hierarchy.
# ===========================================================================
def setup_scheduled_appointment(*,
                                state_code: str = "NY",
                                cpt_code: str = "90834",
                                modality: str = "IN_PERSON",
                                patient_state_on_day: Optional[str] = None,
                                minutes_after_anchor_start: int = 120,
                                duration_minutes: int = 45,
                                pre_licensed: bool = False,
                                psypact_enrolled: bool = False,
                                insurance_plan: Optional[
                                    Dict[str, Any]] = None,
                                household_income_cents: int = 3_000_000,
                                household_size: int = 2,
                                deductible_remaining_cents: Optional[
                                    int] = None,
                                pricing_rack_90791_cents: Optional[
                                    int] = None,
                                pricing_rack_90834_cents: Optional[
                                    int] = None,
                                ) -> Dict[str, Any]:
    """Anchor clock -> active therapist (LICENSED or PRE_LICENSED with
    supervision) -> patient -> SCHEDULED appointment.

    Returns a dict {therapist, license, patient, appointment,
    supervisor?, assignment?, plan?}.
    """
    anchor_clock()
    result: Dict[str, Any] = {}
    if pre_licensed:
        therapist, license_, supervisor, assignment = (
            setup_pre_licensed_therapist_with_supervision(
                state_code=state_code,
                psypact_enrolled=psypact_enrolled,
                pricing_rack_90791_cents=pricing_rack_90791_cents,
                pricing_rack_90834_cents=pricing_rack_90834_cents,
            )
        )
        result["supervisor"] = supervisor
        result["assignment"] = assignment
    else:
        therapist, license_ = setup_active_licensed_therapist(
            state_code=state_code,
            psypact_enrolled=psypact_enrolled,
            pricing_rack_90791_cents=pricing_rack_90791_cents,
            pricing_rack_90834_cents=pricing_rack_90834_cents,
        )
    result["therapist"] = therapist
    result["license"] = license_

    insurance_plan_id = (
        insurance_plan["id"] if insurance_plan is not None else None
    )
    patient = create_patient(
        state_of_residence=state_code,
        household_income_cents=household_income_cents,
        household_size=household_size,
        insurance_plan_id=insurance_plan_id,
    )
    if deductible_remaining_cents is not None:
        patient = patch_patient_deductible(
            patient["id"], deductible_remaining_cents,
        )
    result["patient"] = patient
    if insurance_plan is not None:
        result["plan"] = insurance_plan

    if patient_state_on_day is None:
        patient_state_on_day = state_code
    sched_start = iso_anchor_offset(minutes=minutes_after_anchor_start)
    sched_end = iso_anchor_offset(
        minutes=minutes_after_anchor_start + duration_minutes,
    )
    appointment = schedule_appointment(
        therapist["id"], patient["id"],
        cpt_code=cpt_code,
        modality=modality,
        patient_state_on_day=patient_state_on_day,
        scheduled_start=sched_start,
        scheduled_end=sched_end,
    )
    result["appointment"] = appointment
    result["scheduled_start"] = sched_start
    result["scheduled_end"] = sched_end
    return result


def setup_checked_in_appointment(**kwargs: Any) -> Dict[str, Any]:
    """Build setup_scheduled_appointment, then advance clock into the
    check-in window and check the appointment in.

    Returns the same dict, with the checked-in appointment overwritten.
    """
    bundle = setup_scheduled_appointment(**kwargs)
    minutes_after = kwargs.get("minutes_after_anchor_start", 120)
    # Move clock 1 minute before scheduled_start (well inside the
    # [start-15min, start+30min] window — PRD §3.6).
    advance_clock_to(iso_anchor_offset(minutes=minutes_after - 1))
    bundle["appointment"] = checkin_appointment(
        bundle["appointment"]["id"], bundle["therapist"]["id"],
    )
    return bundle


def setup_in_progress_session(**kwargs: Any) -> Dict[str, Any]:
    """Build setup_checked_in_appointment, then POST the Session.

    Returns the bundle with `session` and `appointment` updated.
    """
    bundle = setup_checked_in_appointment(**kwargs)
    bundle["session"] = create_session(
        bundle["appointment"]["id"], bundle["therapist"]["id"],
        actual_duration_minutes=kwargs.get("actual_duration_minutes", 45),
    )
    return bundle


def setup_completed_session_and_claim(**kwargs: Any) -> Dict[str, Any]:
    """Build setup_in_progress_session, then complete the session.

    Returns the bundle with `session` updated to COMPLETED and `claim`
    set to the freshly auto-posted BillingClaim (looked up by listing
    claims filtered by patient_id).
    """
    bundle = setup_in_progress_session(**kwargs)
    bundle["session"] = complete_session(
        bundle["session"]["id"], bundle["therapist"]["id"],
    )
    bundle["appointment"] = re_get_appointment(bundle["appointment"]["id"])
    bundle["claim"] = _lookup_claim_for_appointment(
        bundle["appointment"]["id"], bundle["patient"]["id"],
    )
    bundle["patient"] = re_get_patient(bundle["patient"]["id"])
    bundle["therapist"] = re_get_therapist(bundle["therapist"]["id"])
    return bundle


def _lookup_claim_for_appointment(appointment_id: str, patient_id: str
                                  ) -> Dict[str, Any]:
    """List claims filtered by patient_id and pick the one whose
    appointment_id matches. Uses PracticeAdmin (full read access)."""
    resp = api_client.list_claims(
        TEST_USERS["practice_admin_headers"],
        params={"patient_id": patient_id},
    )
    envelope = get_success_data(resp)
    # /claims returns an array of claims; meta envelope flattens via
    # get_success_data, but get_success_data returns the data payload
    # (which may be a list directly).
    items = envelope if isinstance(envelope, list) else (
        envelope.get("data") or envelope.get("items") or envelope
    )
    if isinstance(items, dict):
        items = items.get("data", [])
    matches = [c for c in items if c.get("appointment_id") == appointment_id]
    assert len(matches) == 1, (
        f"Expected exactly one claim for appointment {appointment_id}, "
        f"found {len(matches)} (claims={items!r})"
    )
    return matches[0]


# ===========================================================================
# Crisis-assessment authorisation helpers — PRD §3.9.
# ===========================================================================
def _establish_prior_care_relationship(therapist_id: str, patient_id: str
                                       ) -> None:
    """Build, run, and COMPLETE one 90834 appointment for
    therapist+patient inside the prior 90 days so the assessment
    authorisation precondition is satisfied.

    PRD §3.9: 'the acting therapist has had a CHECKED_IN or COMPLETED
    appointment with this patient at any time in the prior ninety days
    ...'

    Side effects (a BillingClaim, supervision-hours increment, possibly
    a deductible decrement) are unavoidable but a fresh, fully-paid
    self-pay claim on a tier-100 patient is harmless for the downstream
    crisis-assessment scenarios.
    """
    # Schedule a CHECKED_IN appointment 5 minutes after current clock.
    sched_start = iso_anchor_offset(minutes=5)
    sched_end = iso_anchor_offset(minutes=50)
    appt = schedule_appointment(
        therapist_id, patient_id,
        cpt_code="90834", modality="IN_PERSON",
        patient_state_on_day="NY",
        scheduled_start=sched_start, scheduled_end=sched_end,
    )
    # Check-in window starts at sched_start-15m so the anchor moment is
    # already within it; check-in directly.
    checkin_appointment(appt["id"], therapist_id)


def setup_patient_with_recent_care(*,
                                   state_code: str = "NY",
                                   household_income_cents: int = 3_000_000,
                                   household_size: int = 2,
                                   insurance_plan: Optional[
                                       Dict[str, Any]] = None,
                                   pre_licensed: bool = False,
                                   pricing_rack_90834_cents: Optional[
                                       int] = None,
                                   ) -> Tuple[Dict[str, Any],
                                              Dict[str, Any],
                                              Dict[str, Any]]:
    """Anchor clock -> active therapist -> patient -> one CHECKED_IN
    appointment inside the prior 90 days (used purely to authorise
    subsequent crisis assessments / safety-plan postings by this
    therapist).

    Returns (therapist, patient, license).
    """
    anchor_clock()
    if pre_licensed:
        therapist, license_, _, _ = (
            setup_pre_licensed_therapist_with_supervision(
                state_code=state_code,
                pricing_rack_90834_cents=pricing_rack_90834_cents,
            )
        )
    else:
        therapist, license_ = setup_active_licensed_therapist(
            state_code=state_code,
            pricing_rack_90834_cents=pricing_rack_90834_cents,
        )
    insurance_plan_id = (
        insurance_plan["id"] if insurance_plan is not None else None
    )
    patient = create_patient(
        state_of_residence=state_code,
        household_income_cents=household_income_cents,
        household_size=household_size,
        insurance_plan_id=insurance_plan_id,
    )
    _establish_prior_care_relationship(therapist["id"], patient["id"])
    # After the helper, the patient has one CHECKED_IN appointment.
    # The clock has advanced ~5 minutes into the future. Re-anchor for
    # the downstream test so subsequent appointments scheduled relative
    # to the anchor remain in the future.
    anchor_clock()
    patient = re_get_patient(patient["id"])
    return therapist, patient, license_


def setup_high_risk_patient_blocked(**kwargs: Any
                                    ) -> Tuple[Dict[str, Any],
                                               Dict[str, Any],
                                               Dict[str, Any]]:
    """Build a patient flagged with safety_plan_required=true via a HIGH
    CrisisAssessment.

    PRD §3.9 inputs (si=3, pa=1, su=2, so=2, am=1) round-up to
    composite_score=23.56 (>= 23.55 threshold), producing risk_level=HIGH.

    Returns (therapist, patient, crisis_assessment).
    """
    therapist, patient, _ = setup_patient_with_recent_care(**kwargs)
    assessment = create_crisis_assessment(
        patient["id"], therapist["id"],
        si_score=3, pa_score=1, su_score=2, so_score=2, am_score=1,
    )
    patient = re_get_patient(patient["id"])
    return therapist, patient, assessment


# ===========================================================================
# Difficulty-design composites — Tier 4 / 5 setups for the priority
# queue in SCAFFOLD_DIFFICULTY_DESIGN.yaml. Each helper mints one of the
# pre-conditions that the difficulty index demands.
# ===========================================================================
def setup_two_in_network_plans_for_contract_mode_dual(
    *,
    allowed_90834_cents: int = 9_550,
    copay_cents: int = 2_500,
    deductible_remaining_cents: int = 20_000,
    rack_90834_cents: int = 15_000,
) -> Dict[str, Any]:
    """For difficulty rule 1, instance
    patient_responsibility_contract_mode_variants.

    Build: ACTIVE LICENSED therapist -> Plan A (DEDUCTIBLE_FIRST) +
    Plan B (COPAY_ONLY) with IDENTICAL allowed_90834 and copay ->
    Patient PA on A + Patient PB on B, both with
    deductible_remaining_cents=20_000. Returns bundle with both pairs
    plus the therapist.
    """
    anchor_clock()
    therapist, license_ = setup_active_licensed_therapist(
        pricing_rack_90834_cents=rack_90834_cents,
    )
    plan_a = create_insurance_plan(
        network_status="IN_NETWORK",
        contract_mode="DEDUCTIBLE_FIRST",
        allowed_amount_90834_cents=allowed_90834_cents,
        allowed_amount_90791_cents=allowed_90834_cents,
        copay_cents=copay_cents,
        payer_name="PlanA",
    )
    plan_b = create_insurance_plan(
        network_status="IN_NETWORK",
        contract_mode="COPAY_ONLY",
        allowed_amount_90834_cents=allowed_90834_cents,
        allowed_amount_90791_cents=allowed_90834_cents,
        copay_cents=copay_cents,
        payer_name="PlanB",
    )
    patient_a = create_patient(
        state_of_residence="NY",
        household_income_cents=3_000_000,
        household_size=2,
        insurance_plan_id=plan_a["id"],
        full_name="Patient A",
    )
    patient_a = patch_patient_deductible(
        patient_a["id"], deductible_remaining_cents,
    )
    patient_b = create_patient(
        state_of_residence="NY",
        household_income_cents=3_000_000,
        household_size=2,
        insurance_plan_id=plan_b["id"],
        full_name="Patient B",
    )
    patient_b = patch_patient_deductible(
        patient_b["id"], deductible_remaining_cents,
    )
    return {
        "therapist": therapist,
        "license": license_,
        "plan_a": plan_a,
        "plan_b": plan_b,
        "patient_a": patient_a,
        "patient_b": patient_b,
    }


def run_appointment_through_completion(therapist_id: str, patient_id: str,
                                       *,
                                       cpt_code: str = "90834",
                                       patient_state_on_day: str = "NY",
                                       actual_duration_minutes: int = 45,
                                       minutes_after_now: int = 60,
                                       ) -> Tuple[Dict[str, Any],
                                                  Dict[str, Any]]:
    """Schedule, check-in, create-session, complete one appointment for
    (therapist, patient). Returns (appointment, session) — both as their
    final post-completion states. Uses the current clock as 'now'."""
    sched_start = iso_anchor_offset(minutes=minutes_after_now)
    sched_end = iso_anchor_offset(
        minutes=minutes_after_now + actual_duration_minutes,
    )
    appt = schedule_appointment(
        therapist_id, patient_id,
        cpt_code=cpt_code,
        modality="IN_PERSON",
        patient_state_on_day=patient_state_on_day,
        scheduled_start=sched_start,
        scheduled_end=sched_end,
    )
    advance_clock_to(iso_anchor_offset(minutes=minutes_after_now - 1))
    checkin_appointment(appt["id"], therapist_id)
    session = create_session(
        appt["id"], therapist_id,
        actual_duration_minutes=actual_duration_minutes,
    )
    session = complete_session(session["id"], therapist_id)
    appt = re_get_appointment(appt["id"])
    return appt, session


def setup_pre_licensed_with_completed_session(
    *,
    rack_90834_cents: int = 10_000,
) -> Dict[str, Any]:
    """For difficulty rule 1, instance
    supervision_hours_accrual_forward_vs_reverse, and rule 9 instance
    supervision_hours_round_trip_preservation.

    Build PRE_LICENSED therapist (PROVISIONAL, supervision_hours=0.00,
    ACTIVE NY license, ACTIVE SupervisionAssignment) -> self-pay
    patient (household 2 / 30660.00 income -> tier 40) ->
    SCHEDULED+CHECKED_IN+IN_PROGRESS+COMPLETED 90834 session ->
    BillingClaim auto-posted (POSTED).
    """
    bundle = setup_scheduled_appointment(
        cpt_code="90834", modality="IN_PERSON",
        pre_licensed=True,
        household_income_cents=3_066_000, household_size=2,
        pricing_rack_90834_cents=rack_90834_cents,
    )
    bundle["appointment"] = checkin_after_anchor(
        bundle["appointment"]["id"], bundle["therapist"]["id"],
        minutes_after_anchor=120,
    )
    bundle["session"] = create_session(
        bundle["appointment"]["id"], bundle["therapist"]["id"],
    )
    bundle["session"] = complete_session(
        bundle["session"]["id"], bundle["therapist"]["id"],
    )
    bundle["appointment"] = re_get_appointment(bundle["appointment"]["id"])
    bundle["claim"] = _lookup_claim_for_appointment(
        bundle["appointment"]["id"], bundle["patient"]["id"],
    )
    bundle["therapist"] = re_get_therapist(bundle["therapist"]["id"])
    return bundle


def checkin_after_anchor(appointment_id: str, therapist_id: str,
                         *, minutes_after_anchor: int = 120
                         ) -> Dict[str, Any]:
    """Advance clock to minutes_after_anchor-1 minute and check the
    appointment in."""
    advance_clock_to(iso_anchor_offset(minutes=minutes_after_anchor - 1))
    return checkin_appointment(appointment_id, therapist_id)


def setup_deductible_first_partial_for_combinatorial(
    *,
    rack_90834_cents: int = 15_000,
    allowed_90834_cents: int = 9_550,
    copay_cents: int = 2_500,
    deductible_remaining_cents: int = 4_000,
) -> Dict[str, Any]:
    """For difficulty rule 2, instance
    patient_responsibility_three_input_branching.

    Build: ACTIVE LICENSED therapist -> Plan DF (DEDUCTIBLE_FIRST,
    allowed_90834=9550, copay=2500) -> Patient with
    deductible_remaining_cents=4000.
    """
    anchor_clock()
    therapist, license_ = setup_active_licensed_therapist(
        pricing_rack_90834_cents=rack_90834_cents,
    )
    plan = create_insurance_plan(
        network_status="IN_NETWORK",
        contract_mode="DEDUCTIBLE_FIRST",
        allowed_amount_90834_cents=allowed_90834_cents,
        allowed_amount_90791_cents=allowed_90834_cents,
        copay_cents=copay_cents,
        payer_name="PlanDF",
    )
    patient = create_patient(
        state_of_residence="NY",
        household_income_cents=3_000_000,
        household_size=2,
        insurance_plan_id=plan["id"],
        full_name="P partial",
    )
    patient = patch_patient_deductible(
        patient["id"], deductible_remaining_cents,
    )
    return {
        "therapist": therapist,
        "license": license_,
        "plan": plan,
        "patient": patient,
    }


def setup_therapist_with_scheduled_appointment_for_cycle(
) -> Dict[str, Any]:
    """For difficulty rule 3, instance therapist_credential_cycle.

    Build: ACTIVE LICENSED therapist (NY) -> one SCHEDULED 90834
    self-pay appointment in the future.
    """
    bundle = setup_scheduled_appointment(
        cpt_code="90834", modality="IN_PERSON",
        minutes_after_anchor_start=180,
    )
    return bundle


def setup_high_risk_assessment_then_appointment(
) -> Dict[str, Any]:
    """For difficulty rule 3, instance appointment_fork_join_to_held.

    Build LICENSED therapist + patient with recent CHECKED_IN history
    (so the therapist may post a crisis assessment), then schedule a
    future appointment that the HIGH assessment will subsequently HOLD.

    Returns {therapist, patient, appointment}.
    """
    therapist, patient, _ = setup_patient_with_recent_care()
    sched_start = iso_anchor_offset(days=2, hours=2)
    sched_end = iso_anchor_offset(days=2, hours=2, minutes=45)
    appointment = schedule_appointment(
        therapist["id"], patient["id"],
        cpt_code="90834", modality="IN_PERSON",
        patient_state_on_day="NY",
        scheduled_start=sched_start, scheduled_end=sched_end,
    )
    return {
        "therapist": therapist, "patient": patient,
        "appointment": appointment,
    }


def setup_deductible_first_for_depth3_chain(
    *,
    allowed_90834_cents: int = 8_000,
    copay_cents: int = 2_000,
    deductible_remaining_cents: int = 10_000,
    rack_90834_cents: int = 10_000,
) -> Dict[str, Any]:
    """For difficulty rule 4, instance session_complete_depth3_chain.

    Build PRE_LICENSED therapist (PROVISIONAL, ACTIVE supervision,
    ACTIVE NY license, supervision_hours=0.00) -> Plan
    DEDUCTIBLE_FIRST allowed=8000 -> Patient with
    deductible_remaining_cents=10000 -> SCHEDULED 90834 appt.
    """
    anchor_clock()
    therapist, license_, supervisor, assignment = (
        setup_pre_licensed_therapist_with_supervision(
            pricing_rack_90834_cents=rack_90834_cents,
        )
    )
    plan = create_insurance_plan(
        network_status="IN_NETWORK",
        contract_mode="DEDUCTIBLE_FIRST",
        allowed_amount_90834_cents=allowed_90834_cents,
        allowed_amount_90791_cents=allowed_90834_cents,
        copay_cents=copay_cents,
        payer_name="PlanD3",
    )
    patient = create_patient(
        state_of_residence="NY",
        household_income_cents=3_000_000,
        household_size=2,
        insurance_plan_id=plan["id"],
        full_name="Pch",
    )
    patient = patch_patient_deductible(
        patient["id"], deductible_remaining_cents,
    )
    sched_start = iso_anchor_offset(minutes=120)
    sched_end = iso_anchor_offset(minutes=165)
    appt = schedule_appointment(
        therapist["id"], patient["id"],
        cpt_code="90834", modality="IN_PERSON",
        patient_state_on_day="NY",
        scheduled_start=sched_start, scheduled_end=sched_end,
    )
    return {
        "therapist": therapist, "license": license_,
        "supervisor": supervisor, "assignment": assignment,
        "plan": plan, "patient": patient, "appointment": appt,
    }


def setup_license_expiry_for_depth2_chain(
) -> Dict[str, Any]:
    """For difficulty rule 4, instance license_expiry_depth2_clock_cascade.

    Build LICENSED therapist with EXACTLY ONE ACTIVE NY license
    expiring at 2026-06-01 -> self-pay Patient (NY) -> SCHEDULED 90834
    Appt at 2026-06-02T10:00 (status SCHEDULED).
    """
    anchor_clock()
    therapist, license_ = setup_active_licensed_therapist(
        license_expires_on=iso_midnight(2026, 6, 1),
    )
    patient = create_patient(state_of_residence="NY")
    sched_start = "2026-06-02T10:00:00.000Z"
    sched_end = "2026-06-02T10:45:00.000Z"
    appt = schedule_appointment(
        therapist["id"], patient["id"],
        cpt_code="90834", modality="IN_PERSON",
        patient_state_on_day="NY",
        scheduled_start=sched_start, scheduled_end=sched_end,
    )
    return {
        "therapist": therapist, "license": license_,
        "patient": patient, "appointment": appt,
    }


def setup_safety_vs_referential_conflict(
) -> Dict[str, Any]:
    """For difficulty rule 5, instance
    safety_vs_referential_license_conflict.

    Build LICENSED therapist with ACTIVE CA license ONLY (no NY
    license), psypact_enrolled=false -> Patient with recent CHECKED_IN
    history (so therapist may post HIGH crisis assessment) -> Post HIGH
    assessment (no future appointments yet so cascade has nothing to
    HOLD) -> SCHEDULE telehealth NY appointment AFTER the assessment ->
    advance clock into the check-in window.

    Returns {therapist, patient, assessment, appointment}.
    """
    anchor_clock()
    # Therapist with CA license only.
    therapist = create_therapist(
        supervision_track="LICENSED", psypact_enrolled=False,
    )
    ca_license = create_state_license(therapist["id"], state_code="CA")
    verify_state_license(therapist["id"], ca_license["id"])
    therapist = activate_therapist(therapist["id"])
    # Patient + prior CHECKED_IN encounter.
    patient = create_patient(state_of_residence="NY")
    # Schedule a CA appointment first (so therapist has license
    # coverage) and check it in to establish prior care.
    prior_start = iso_anchor_offset(minutes=5)
    prior_end = iso_anchor_offset(minutes=50)
    prior_appt = schedule_appointment(
        therapist["id"], patient["id"],
        cpt_code="90834", modality="IN_PERSON",
        patient_state_on_day="CA",
        scheduled_start=prior_start, scheduled_end=prior_end,
    )
    checkin_appointment(prior_appt["id"], therapist["id"])
    # Re-anchor clock so subsequent appointment times are in the future.
    anchor_clock()
    # Post HIGH crisis assessment (no future appts yet, so cascade is
    # vacuous).
    assessment = create_crisis_assessment(
        patient["id"], therapist["id"],
        si_score=3, pa_score=1, su_score=2, so_score=2, am_score=1,
    )
    patient = re_get_patient(patient["id"])
    # Now schedule a NY telehealth appointment. PRD §3.6 does not block
    # appointment creation on safety_plan_required nor cross-state
    # license — both fire at check-in.
    sched_start = iso_anchor_offset(minutes=120)
    sched_end = iso_anchor_offset(minutes=165)
    appt = schedule_appointment(
        therapist["id"], patient["id"],
        cpt_code="90834", modality="TELEHEALTH",
        patient_state_on_day="NY",
        scheduled_start=sched_start, scheduled_end=sched_end,
    )
    # Advance clock into the check-in window.
    advance_clock_to(iso_anchor_offset(minutes=119))
    return {
        "therapist": therapist, "patient": patient,
        "assessment": assessment, "appointment": appt,
    }


def setup_session_complete_state_vs_referential(
) -> Dict[str, Any]:
    """For difficulty rule 5, instance
    state_vs_referential_session_complete_conflict.

    Build LICENSED therapist (ACTIVE) -> Patient -> appointment
    CHECKED_IN -> Session IN_PROGRESS -> PracticeAdmin VOIDs the
    session (Session.status=VOIDED, Appointment.status=CANCELLED) ->
    PracticeAdmin SUSPENDs the therapist
    (credential_status=SUSPENDED).

    Returns {therapist, patient, session, appointment}.
    """
    bundle = setup_in_progress_session()
    # Void the session: Session.status=VOIDED, Appointment.status=CANCELLED.
    bundle["session"] = void_session(bundle["session"]["id"])
    bundle["appointment"] = re_get_appointment(bundle["appointment"]["id"])
    # Suspend the therapist.
    bundle["therapist"] = suspend_therapist(bundle["therapist"]["id"])
    return bundle


def setup_license_gap_vs_fiscal_at_checkin(
) -> Dict[str, Any]:
    """For difficulty rule 5, instance
    license_gap_vs_fiscal_amount_conflict.

    Build LICENSED therapist with ACTIVE CA license only (no NY),
    psypact_enrolled=false, rack_90834=12000 -> Patient (NY) ->
    schedule 90834 telehealth Appt with patient_state_on_day=NY ->
    advance clock into the check-in window.
    """
    anchor_clock()
    therapist = create_therapist(
        supervision_track="LICENSED", psypact_enrolled=False,
        pricing_rack_90834_cents=12_000,
    )
    ca_license = create_state_license(therapist["id"], state_code="CA")
    verify_state_license(therapist["id"], ca_license["id"])
    therapist = activate_therapist(therapist["id"])
    patient = create_patient(state_of_residence="NY")
    sched_start = iso_anchor_offset(minutes=60)
    sched_end = iso_anchor_offset(minutes=105)
    appt = schedule_appointment(
        therapist["id"], patient["id"],
        cpt_code="90834", modality="TELEHEALTH",
        patient_state_on_day="NY",
        scheduled_start=sched_start, scheduled_end=sched_end,
    )
    advance_clock_to(iso_anchor_offset(minutes=59))
    return {
        "therapist": therapist, "patient": patient,
        "appointment": appt,
    }


def setup_posted_claim_for_void_window(
    *,
    rack_90834_cents: int = 10_000,
    allowed_90834_cents: int = 9_550,
    copay_cents: int = 2_500,
    deductible_remaining_cents: int = 20_000,
    posted_at_iso: str = "2026-05-01T10:00:00.000Z",
) -> Dict[str, Any]:
    """For difficulty rule 6, instance
    void_window_seven_day_threshold_inclusive AND rule 9 instance
    deductible_round_trip_preservation.

    Build LICENSED therapist (NY, ACTIVE) -> in-network DEDUCTIBLE_FIRST
    plan -> Patient with deductible_remaining_cents=20000 -> advance
    clock to posted_at_iso -> schedule, check-in, create-session,
    complete 90834 appointment -> BillingClaim POSTED at exactly
    posted_at_iso.
    """
    anchor_clock()
    therapist, license_ = setup_active_licensed_therapist(
        pricing_rack_90834_cents=rack_90834_cents,
    )
    plan = create_insurance_plan(
        network_status="IN_NETWORK",
        contract_mode="DEDUCTIBLE_FIRST",
        allowed_amount_90834_cents=allowed_90834_cents,
        allowed_amount_90791_cents=allowed_90834_cents,
        copay_cents=copay_cents,
        payer_name="PlanV",
    )
    patient = create_patient(
        state_of_residence="NY",
        insurance_plan_id=plan["id"],
    )
    patient = patch_patient_deductible(
        patient["id"], deductible_remaining_cents,
    )
    # Advance clock so the posted_at is exactly the supplied moment.
    advance_clock_to(posted_at_iso)
    # Schedule, check-in, create-session, complete in one helper —
    # using current clock as "now".
    sched_start = _add_minutes(posted_at_iso, 5)
    sched_end = _add_minutes(posted_at_iso, 50)
    appt = schedule_appointment(
        therapist["id"], patient["id"],
        cpt_code="90834", modality="IN_PERSON",
        patient_state_on_day="NY",
        scheduled_start=sched_start, scheduled_end=sched_end,
    )
    # Advance the clock into the check-in window: 5 minutes after the
    # supplied posted_at_iso (still within [start-15m, start+30m]).
    advance_clock_to(_add_minutes(posted_at_iso, 4))
    checkin_appointment(appt["id"], therapist["id"])
    session = create_session(appt["id"], therapist["id"])
    # Snap the clock to the exact posted_at moment (well within window).
    advance_clock_to(posted_at_iso)
    session = complete_session(session["id"], therapist["id"])
    appt = re_get_appointment(appt["id"])
    claim = _lookup_claim_for_appointment(appt["id"], patient["id"])
    patient = re_get_patient(patient["id"])
    return {
        "therapist": therapist, "license": license_,
        "plan": plan, "patient": patient, "appointment": appt,
        "session": session, "claim": claim,
        "posted_at_iso": posted_at_iso,
    }


def _add_minutes(iso_ts: str, minutes: int) -> str:
    """Return ISO ts shifted by `minutes` minutes."""
    from datetime import timedelta
    dt = parse_iso(iso_ts) + timedelta(minutes=minutes)
    from .factories import iso_utc
    return iso_utc(dt)


def _add_seconds(iso_ts: str, seconds: int) -> str:
    from datetime import timedelta
    dt = parse_iso(iso_ts) + timedelta(seconds=seconds)
    from .factories import iso_utc
    return iso_utc(dt)


def setup_appointment_checkin_depends_on_credential(
) -> Dict[str, Any]:
    """For difficulty rule 7, instance
    appointment_checkin_depends_on_therapist_credential.

    Build LICENSED therapist (ACTIVE) -> Patient -> SCHEDULED 90834
    Appt in NY -> suspend therapist (cascade HOLDs Acd) -> advance
    clock into the check-in window.

    Returns {therapist, patient, appointment}.
    """
    bundle = setup_scheduled_appointment(
        cpt_code="90834", modality="IN_PERSON",
        patient_state_on_day="NY",
        minutes_after_anchor_start=120,
    )
    # Suspend therapist -> cascade HOLDs the appointment.
    bundle["therapist"] = suspend_therapist(bundle["therapist"]["id"])
    bundle["appointment"] = re_get_appointment(bundle["appointment"]["id"])
    # Advance clock into check-in window.
    advance_clock_to(iso_anchor_offset(minutes=119))
    return bundle


def setup_session_complete_depends_on_supervision(
) -> Dict[str, Any]:
    """For difficulty rule 7, instance
    session_complete_depends_on_supervision_assignment.

    Build PRE_LICENSED therapist (PROVISIONAL, ACTIVE NY license,
    ACTIVE SupervisionAssignment) -> Patient -> SCHEDULED 90834 NY
    Appt -> CHECKED_IN -> IN_PROGRESS Session -> terminate the
    SupervisionAssignment.

    Returns {therapist, supervisor, assignment, patient, appointment,
    session}.
    """
    bundle = setup_in_progress_session(pre_licensed=True)
    # Terminate the supervision assignment.
    bundle["assignment"] = terminate_supervision_assignment(
        bundle["assignment"]["id"],
    )
    return bundle


def setup_two_back_to_back_appointments_for_therapist_overlap(
) -> Dict[str, Any]:
    """For difficulty rule 8, instance therapist_double_booking_halfopen.

    Build LICENSED therapist + two patients + one base appointment
    09:00-10:00 (anchor-relative). Returns {therapist, patient_a,
    patient_b, base_appointment}.
    """
    anchor_clock()
    therapist, license_ = setup_active_licensed_therapist()
    patient_a = create_patient(full_name="Patient A", state_of_residence="NY")
    patient_b = create_patient(full_name="Patient B", state_of_residence="NY")
    base = schedule_appointment(
        therapist["id"], patient_a["id"],
        cpt_code="90834", modality="IN_PERSON",
        patient_state_on_day="NY",
        scheduled_start=iso_anchor_offset(hours=23),
        scheduled_end=iso_anchor_offset(hours=24),
    )
    return {
        "therapist": therapist, "license": license_,
        "patient_a": patient_a, "patient_b": patient_b,
        "base_appointment": base,
    }


def setup_two_therapists_one_patient_for_min_gap(
) -> Dict[str, Any]:
    """For difficulty rule 8, instance patient_min_gap_closed_with_buffer.

    Build two LICENSED therapists + one Patient + one base appointment
    for Ta at 09:00-10:00 (anchor-relative).
    """
    anchor_clock()
    therapist_a, license_a = setup_active_licensed_therapist()
    therapist_b, license_b = setup_active_licensed_therapist()
    patient = create_patient(state_of_residence="NY")
    base = schedule_appointment(
        therapist_a["id"], patient["id"],
        cpt_code="90834", modality="IN_PERSON",
        patient_state_on_day="NY",
        scheduled_start=iso_anchor_offset(hours=23),
        scheduled_end=iso_anchor_offset(hours=24),
    )
    return {
        "therapist_a": therapist_a, "therapist_b": therapist_b,
        "license_a": license_a, "license_b": license_b,
        "patient": patient, "base_appointment": base,
    }


def setup_safety_plan_ready(*,
                            assessment_factors: Tuple[
                                int, int, int, int, int] = (
                                3, 1, 2, 2, 1),
                            ) -> Dict[str, Any]:
    """For difficulty rule 6, instance
    safety_plan_empty_contacts_zero_check.

    Build LICENSED therapist + patient with recent CHECKED_IN history
    -> post HIGH crisis assessment. Returns {therapist, patient,
    assessment}.
    """
    therapist, patient, assessment = setup_high_risk_patient_blocked()
    return {
        "therapist": therapist, "patient": patient,
        "assessment": assessment,
    }


__all__ = [
    # Clock
    "anchor_clock",
    "advance_clock_to",
    # Therapist / license
    "create_therapist",
    "create_state_license",
    "verify_state_license",
    "revoke_state_license",
    "activate_therapist",
    "suspend_therapist",
    "reinstate_therapist",
    "re_get_therapist",
    "setup_active_licensed_therapist",
    "setup_pre_licensed_therapist_with_supervision",
    # Supervisor
    "create_supervisor",
    "create_supervision_assignment",
    "terminate_supervision_assignment",
    # Patient / insurance
    "create_insurance_plan",
    "create_patient",
    "patch_patient_deductible",
    "re_get_patient",
    # Appointment / session
    "schedule_appointment",
    "schedule_appointment_as_admin",
    "checkin_appointment",
    "cancel_appointment",
    "create_session",
    "complete_session",
    "void_session",
    "re_get_appointment",
    "re_get_session",
    "re_get_claim",
    "checkin_after_anchor",
    "run_appointment_through_completion",
    # Claim
    "void_claim",
    # Crisis / safety
    "create_crisis_assessment",
    "create_safety_plan",
    "rescind_safety_plan",
    # Composites — generic
    "setup_scheduled_appointment",
    "setup_checked_in_appointment",
    "setup_in_progress_session",
    "setup_completed_session_and_claim",
    "setup_patient_with_recent_care",
    "setup_high_risk_patient_blocked",
    # Composites — difficulty-design
    "setup_two_in_network_plans_for_contract_mode_dual",
    "setup_pre_licensed_with_completed_session",
    "setup_deductible_first_partial_for_combinatorial",
    "setup_therapist_with_scheduled_appointment_for_cycle",
    "setup_high_risk_assessment_then_appointment",
    "setup_deductible_first_for_depth3_chain",
    "setup_license_expiry_for_depth2_chain",
    "setup_safety_vs_referential_conflict",
    "setup_session_complete_state_vs_referential",
    "setup_license_gap_vs_fiscal_at_checkin",
    "setup_posted_claim_for_void_window",
    "setup_appointment_checkin_depends_on_credential",
    "setup_session_complete_depends_on_supervision",
    "setup_two_back_to_back_appointments_for_therapist_overlap",
    "setup_two_therapists_one_patient_for_min_gap",
    "setup_safety_plan_ready",
]
