"""Render-time gates, completion co-sign gate, supervision-hour variants, promotion.

Queue A (Difficulty): cross_entity_state_dependency, boundary_precision_check,
dual_variant_calc (supervision hours), priority_pair_validation_conflict (hold vs license).
Queue B (Corner): validations (telehealth, promotion, hold), boundary fpl.
"""
from test_helpers import (
    api_client, validate_error, get_success_data,
    create_independent_therapist, create_licensed_associate, create_associate_therapist,
    create_patient, schedule_appointment, render_appointment, sign_note_for,
    set_clock, make_therapist_headers, create_crisis_assessment,
    TEST_USERS, ApiErrorId,
)

CD = TEST_USERS["clinical_director_headers"]
FD = TEST_USERS["front_desk_headers"]


def test_render_blocked_by_expired_license():
    """PRD §3.6: "The clinician must hold a state license in ACTIVE status whose
    state_code equals the patient's location_state_code, failing which the render is
    rejected with ERR_NO_ACTIVE_LICENSE_IN_STATE"
    PRD §2.8: "A license is considered to have lapsed to EXPIRED once the server's
    current UTC clock reaches or passes its expires_on instant; this lapse is evaluated
    whenever a license-gated operation reads the license, so an expired license
    silently stops satisfying licensure preconditions for new sessions."

    Design: Difficulty/cross_entity_state_dependency/render_blocked_by_expired_license_appointment_vs_statelicense
    """
    set_clock("2026-06-08T00:00:00Z")
    therapist = create_associate_therapist(full_name="Dr Exp")
    get_success_data(api_client.create_state_license(
        {"therapist_id": therapist["id"], "state_code": "CA", "license_number": "LE",
         "expires_on": "2026-06-09T00:00:00Z"}, CD))
    patient = create_patient()
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-08T08:00:00Z", payment_path="SELF_PAY")
    set_clock("2026-06-10T08:00:00Z")
    resp = api_client.render_appointment(appt["id"], make_therapist_headers(therapist["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_LICENSE_IN_STATE.value)


def test_render_blocked_by_revoked_license():
    """PRD §3.6: "The clinician must hold a state license in ACTIVE status whose
    state_code equals the patient's location_state_code, failing which the render is
    rejected with ERR_NO_ACTIVE_LICENSE_IN_STATE"
    PRD §3.1: "A director may revoke an active license at any time, an action that
    drives its status to REVOKED."

    Design: Difficulty/cross_entity_state_dependency/render_blocked_by_expired_license_appointment_vs_statelicense
    """
    set_clock("2026-06-08T12:00:00Z")
    therapist = create_associate_therapist(full_name="Dr Rev")
    lic = get_success_data(api_client.create_state_license(
        {"therapist_id": therapist["id"], "state_code": "CA", "license_number": "LREV",
         "expires_on": "2030-01-01T00:00:00Z"}, CD))
    patient = create_patient()
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-08T08:00:00Z", payment_path="SELF_PAY")
    get_success_data(api_client.revoke_state_license(lic["id"], CD))
    resp = api_client.render_appointment(appt["id"], make_therapist_headers(therapist["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_LICENSE_IN_STATE.value)


def test_complete_blocked_when_supervised_therapist_note_only_signed():
    """PRD §3.6: "Completion requires that a clinical note for the appointment already
    exist in SIGNED or CO_SIGNED status; moreover, if the rendering clinician still
    requires supervision, the note must be CO_SIGNED rather than merely SIGNED, failing
    which completion is rejected with ERR_COSIGN_REQUIRED."

    Design: Difficulty/cross_entity_state_dependency/complete_blocked_by_supervised_therapist_note_not_cosigned
    """
    set_clock("2026-06-11T12:00:00Z")
    # Independent supervisor (so that the associate's supervisor link is valid).
    create_independent_therapist(full_name="Sup2", license_number="LSP")
    associate = create_licensed_associate(full_name="Assoc2", license_number="LA2")
    patient = create_patient()
    appt = schedule_appointment(
        associate["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-11T08:00:00Z", payment_path="SELF_PAY")
    render_appointment(appt["id"], associate["id"])
    sign_note_for(appt["id"], associate["id"])  # SIGNED, not CO_SIGNED
    resp = api_client.complete_appointment(appt["id"], make_therapist_headers(associate["id"]))
    validate_error(resp, ApiErrorId.ERR_COSIGN_REQUIRED.value)


def test_complete_allowed_when_supervised_note_cosigned():
    """PRD §3.6: "if the rendering clinician still requires supervision, the note must
    be CO_SIGNED rather than merely SIGNED, failing which completion is rejected with
    ERR_COSIGN_REQUIRED."
    PRD §3.6: "Completing a rendered session advances it from RENDERED to COMPLETED and
    is performed by the rendering clinician."

    Design: Difficulty/cross_entity_state_dependency/complete_blocked_by_supervised_therapist_note_not_cosigned
    """
    set_clock("2026-06-11T12:00:00Z")
    supervisor = create_independent_therapist(full_name="Sup2b", license_number="LSP2")
    associate = create_licensed_associate(
        full_name="Assoc2b", license_number="LA2b", supervisor_id=supervisor["id"])
    patient = create_patient()
    appt = schedule_appointment(
        associate["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-11T08:00:00Z", payment_path="SELF_PAY")
    render_appointment(appt["id"], associate["id"])
    note = sign_note_for(appt["id"], associate["id"])
    get_success_data(api_client.cosign_clinical_note(
        note["id"], make_therapist_headers(supervisor["id"])))
    completed = get_success_data(api_client.complete_appointment(
        appt["id"], make_therapist_headers(associate["id"])))
    assert completed["status"] == "COMPLETED"


def test_supervision_verified_vs_projected_hours_diverge():
    """PRD §3.2: "The projected direct hours sum the session length over all of this
    clinician's appointments in SCHEDULED, RENDERED, or COMPLETED status, dividing
    total minutes by sixty and rounding to two decimal places"
    PRD §3.2: "The verified direct hours are stricter: they sum session length only
    over appointments that have reached COMPLETED and whose clinical note is CO_SIGNED,
    again as minutes over sixty rounded to two decimals."

    Design: Difficulty/dual_variant_calc/supervision_hours_verified_vs_projected
    """
    set_clock("2026-06-02T12:00:00Z")
    supervisor = create_independent_therapist(full_name="Sup", license_number="LS")
    associate = create_licensed_associate(
        full_name="Assoc", license_number="LA", supervisor_id=supervisor["id"])
    patient = create_patient()
    # One COMPLETED+CO_SIGNED 0.75h and one still-SCHEDULED 0.75h.
    ap1 = schedule_appointment(
        associate["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-02T08:00:00Z", payment_path="SELF_PAY")
    schedule_appointment(
        associate["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-09T08:00:00Z", payment_path="SELF_PAY")
    render_appointment(ap1["id"], associate["id"])
    note = sign_note_for(ap1["id"], associate["id"])
    get_success_data(api_client.cosign_clinical_note(
        note["id"], make_therapist_headers(supervisor["id"])))
    get_success_data(api_client.complete_appointment(
        ap1["id"], make_therapist_headers(associate["id"])))
    t = get_success_data(api_client.get_therapist(associate["id"], CD))
    assert t["verified_direct_hours"] == 0.75
    assert t["projected_direct_hours"] == 1.50


def test_supervision_verified_hours_only_count_cosigned():
    """PRD §3.2: "The verified direct hours are stricter: they sum session length only
    over appointments that have reached COMPLETED and whose clinical note is CO_SIGNED,
    again as minutes over sixty rounded to two decimals."

    Design: Difficulty/dual_variant_calc/supervision_hours_verified_vs_projected
    """
    set_clock("2026-06-02T12:00:00Z")
    supervisor = create_independent_therapist(full_name="Sup", license_number="LS")
    associate = create_licensed_associate(
        full_name="Assoc", license_number="LA", supervisor_id=supervisor["id"])
    patient = create_patient()
    ap1 = schedule_appointment(
        associate["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-02T08:00:00Z", payment_path="SELF_PAY")
    render_appointment(ap1["id"], associate["id"])
    note = sign_note_for(ap1["id"], associate["id"])
    get_success_data(api_client.cosign_clinical_note(
        note["id"], make_therapist_headers(supervisor["id"])))
    get_success_data(api_client.complete_appointment(
        ap1["id"], make_therapist_headers(associate["id"])))
    t = get_success_data(api_client.get_therapist(associate["id"], CD))
    assert t["verified_direct_hours"] == 0.75


def test_sliding_fee_band_boundary_150_percent_inclusive():
    """PRD §2.10: "The multiplier is then assigned by band, where each band's upper
    boundary is inclusive: a percentage at or below 150 yields a multiplier of 0.20;
    above 150 and at or below 200 yields 0.40"
    PRD §2.10: "The patient's fpl_percent is their annual household income divided by
    that poverty line, multiplied by 100, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/sliding_fee_band_boundary_150_percent_inclusive
    """
    # income 22590 / FPL 15060 (household 1) = 150.00% -> 0.20 band
    patient = create_patient(income=22590, household=1)
    assert patient["fpl_percent"] == 150.00
    assert patient["sliding_fee_multiplier"] == 0.20


def test_sliding_fee_band_just_above_150_percent():
    """PRD §2.10: "a percentage at or below 150 yields a multiplier of 0.20; above 150
    and at or below 200 yields 0.40; above 200 and at or below 250 yields 0.60"

    Design: Difficulty/boundary_precision_check/sliding_fee_band_boundary_150_percent_inclusive
    """
    # income 22591 / FPL 15060 = 150.01% -> next band 0.40
    patient = create_patient(income=22591, household=1)
    assert patient["fpl_percent"] == 150.01
    assert patient["sliding_fee_multiplier"] == 0.40


def test_fresh_therapist_has_zero_supervision_and_direct_hours():
    """PRD §3.1: "Every new clinician begins life in ASSOCIATE standing and requiring
    supervision; the computed credential and hour fields — credential_status,
    requires_supervision, verified_direct_hours, projected_direct_hours, and
    verified_supervision_hours — are all managed by the system rather than supplied by
    the caller."

    Design: Difficulty/boundary_precision_check/empty_supervision_logs_yield_zero_supervision_hours
    """
    t = create_associate_therapist(full_name="Dr Z")
    fetched = get_success_data(api_client.get_therapist(t["id"], CD))
    assert fetched["verified_supervision_hours"] == 0
    assert fetched["verified_direct_hours"] == 0


def test_empty_supervision_logs_yield_zero_supervision_hours_on_read():
    """PRD §3.2: "acceptance moves the log to ACCEPTED and recomputes the supervisee's
    verified_supervision_hours as the sum of the hours across that clinician's accepted
    logs, rounded to two decimals."

    Design: Difficulty/boundary_precision_check/empty_supervision_logs_yield_zero_supervision_hours
    """
    t = create_associate_therapist(full_name="Dr Z2")
    fetched = get_success_data(api_client.get_therapist(t["id"], CD))
    assert fetched["verified_supervision_hours"] == 0


def test_hold_gate_beats_license_gate_on_render():
    """PRD §3.9: "Only then are state-machine preconditions evaluated ... followed by
    the domain safety and referential gates: the crisis safety-plan gate
    (ERR_SAFETY_PLAN_REQUIRED), the clinical-hold gate (ERR_PATIENT_ON_HOLD), the
    active-license gate (ERR_NO_ACTIVE_LICENSE_IN_STATE), the telehealth gate
    (ERR_TELEHEALTH_NOT_AUTHORIZED)"

    Design: Difficulty/priority_pair_validation_conflict/hold_gate_beats_license_gate_on_render
    """
    set_clock("2026-06-07T12:00:00Z")
    # Therapist with NO license in patient's state (NY); patient placed on hold.
    therapist = create_associate_therapist(full_name="Dr P")
    patient = create_patient(state_code="NY")
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-07T08:00:00Z", payment_path="SELF_PAY")
    create_crisis_assessment(patient["id"], therapist["id"],
                             ideation=3, plan=3, means=3, prior=3)  # HIGH -> hold
    resp = api_client.render_appointment(appt["id"], make_therapist_headers(therapist["id"]))
    validate_error(resp, ApiErrorId.ERR_PATIENT_ON_HOLD.value)


def test_hold_gate_precedes_license_gate_revealed_after_resolve():
    """PRD §3.9: "the domain safety and referential gates: the crisis safety-plan gate
    (ERR_SAFETY_PLAN_REQUIRED), the clinical-hold gate (ERR_PATIENT_ON_HOLD), the
    active-license gate (ERR_NO_ACTIVE_LICENSE_IN_STATE), the telehealth gate
    (ERR_TELEHEALTH_NOT_AUTHORIZED)"

    Design: Difficulty/priority_pair_validation_conflict/hold_gate_beats_license_gate_on_render
    """
    set_clock("2026-06-07T12:00:00Z")
    # Therapist has no license in patient's state (NY) AND patient is on hold.
    therapist = create_associate_therapist(full_name="Dr P2")
    patient = create_patient(state_code="NY")
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-07T08:00:00Z", payment_path="SELF_PAY")
    ca = create_crisis_assessment(patient["id"], therapist["id"],
                                  ideation=3, plan=3, means=3, prior=3)  # HIGH -> hold
    # While both violations stand, the hold gate (lower priority number) wins.
    resp1 = api_client.render_appointment(appt["id"], make_therapist_headers(therapist["id"]))
    validate_error(resp1, ApiErrorId.ERR_PATIENT_ON_HOLD.value)
    # Lift the hold; now only the license violation remains and surfaces.
    get_success_data(api_client.create_safety_plan(
        {"crisis_assessment_id": ca["id"], "warning_signs": "w",
         "coping_strategies": "c", "emergency_contacts": ["988"]},
        make_therapist_headers(therapist["id"])))
    get_success_data(api_client.resolve_crisis_assessment(
        ca["id"], make_therapist_headers(therapist["id"])))
    resp2 = api_client.render_appointment(appt["id"], make_therapist_headers(therapist["id"]))
    validate_error(resp2, ApiErrorId.ERR_NO_ACTIVE_LICENSE_IN_STATE.value)


def test_telehealth_render_not_authorized_rejected():
    """PRD §3.6: "if the session's modality is TELEHEALTH, that matching license's
    telehealth_authorized flag must be true, failing which it is rejected with
    ERR_TELEHEALTH_NOT_AUTHORIZED."

    Design: Corner/validations/telehealth_render_not_authorized_rejected
    """
    set_clock("2026-07-09T12:00:00Z")
    therapist = create_associate_therapist(full_name="Dr TH")
    get_success_data(api_client.create_state_license(
        {"therapist_id": therapist["id"], "state_code": "CA", "license_number": "LTh",
         "expires_on": "2030-01-01T00:00:00Z", "telehealth_authorized": False}, CD))
    patient = create_patient()
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        modality="TELEHEALTH", start_at="2026-07-09T08:00:00Z", payment_path="SELF_PAY")
    resp = api_client.render_appointment(appt["id"], make_therapist_headers(therapist["id"]))
    validate_error(resp, ApiErrorId.ERR_TELEHEALTH_NOT_AUTHORIZED.value)


def test_promotion_not_eligible_insufficient_hours():
    """PRD §3.3: "Moving from ASSOCIATE to SUPERVISED_PRACTICE requires verified direct
    hours of at least 1,500"
    PRD §3.3: "A promotion whose hour, supervision-ratio, or license thresholds are
    unmet is rejected with ERR_PROMOTION_NOT_ELIGIBLE."

    Design: Corner/validations/promotion_not_eligible_insufficient_hours
    """
    associate = create_associate_therapist(full_name="Assoc3")
    resp = api_client.promote_therapist(
        associate["id"], {"expected_therapist_version": associate["version"]}, CD)
    validate_error(resp, ApiErrorId.ERR_PROMOTION_NOT_ELIGIBLE.value)


def test_patient_on_hold_render_blocked_with_license_present():
    """PRD §3.6: "The patient must not be on a clinical hold; rendering against a
    patient whose status is ON_CLINICAL_HOLD is rejected with ERR_PATIENT_ON_HOLD."

    Design: Corner/validations/patient_on_hold_render_blocked_only
    """
    set_clock("2026-07-11T12:00:00Z")
    therapist = create_independent_therapist(full_name="Dr Ho", license_number="LHo")
    patient = create_patient()
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-07-11T08:00:00Z", payment_path="SELF_PAY")
    create_crisis_assessment(patient["id"], therapist["id"],
                             ideation=3, plan=3, means=3, prior=3)  # HIGH -> hold
    resp = api_client.render_appointment(appt["id"], make_therapist_headers(therapist["id"]))
    validate_error(resp, ApiErrorId.ERR_PATIENT_ON_HOLD.value)


def test_render_future_appointment_before_start_returns_invalid_state():
    """PRD §3.6: "A render is gated by a sequence of conditions. The session's start_at
    must be at or before the server's current UTC clock."

    Design: Corner/state_machines/render_future_appointment_before_start_returns_invalid_state
    """
    set_clock("2026-07-01T06:00:00Z")
    therapist = create_associate_therapist(full_name="Dr Fut")
    get_success_data(api_client.create_state_license(
        {"therapist_id": therapist["id"], "state_code": "CA", "license_number": "LF",
         "expires_on": "2030-01-01T00:00:00Z"}, CD))
    patient = create_patient()
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-07-01T08:00:00Z", payment_path="SELF_PAY")
    resp = api_client.render_appointment(appt["id"], make_therapist_headers(therapist["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_suspend_therapist_cascades_cancel_scheduled_appointments():
    """PRD §3.3: "Suspending a clinician moves them to SUSPENDED, increments their
    version by one, and cascades a cancellation across all of that clinician's
    appointments currently in SCHEDULED status, driving each to CANCELLED."

    Design: Corner/state_machines/suspend_therapist_cascades_cancel_scheduled_appointments
    """
    therapist = create_associate_therapist(full_name="Dr Susp")
    patient = create_patient()
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-07-04T08:00:00Z", payment_path="SELF_PAY")
    suspended = get_success_data(api_client.suspend_therapist(
        therapist["id"], {"expected_therapist_version": therapist["version"]}, CD))
    assert suspended["credential_status"] == "SUSPENDED"
    appt_after = get_success_data(api_client.get_appointment(appt["id"], CD))
    assert appt_after["status"] == "CANCELLED"
