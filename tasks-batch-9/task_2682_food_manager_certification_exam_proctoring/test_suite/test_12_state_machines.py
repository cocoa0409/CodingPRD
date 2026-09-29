"""Declared transitions, their side effects, and the undeclared ones that must be
refused without leaving a trace."""
from test_helpers import (
    TEST_USERS,
    add_candidate,
    add_proctor,
    assign_code,
    factories as f,
    file_incident,
    finalize_report,
    get_success_data,
    purchase_batch,
    resolve_incident,
    schedule_session,
    set_clock,
    setup_landscape,
    setup_sitting,
    submit_session,
    take_incident_into_review,
    validate_error,
    validate_paginated,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_ALT_ADMIN = TEST_USERS["platform_admin_alt_headers"]
_SCORING_ADMIN = TEST_USERS["scoring_admin_headers"]
_SECURITY_ADMIN = TEST_USERS["security_admin_headers"]


def test_a_new_sitting_lands_on_both_declared_initial_states(api):
    """Created without a proctor, the sitting opens SCHEDULED on the delivery axis
    and PENDING_ASSIGNMENT on the proctoring axis, with every later stamp null.

    PRD: "On success the sitting is created with `session_status` `SCHEDULED` and
    `reschedule_count` at zero."

    PRD: "The identity fields `id_document_type`, `id_document_expires_on` and
    `biometric_match_score` are all null at this point, `proctor_attestation` is
    false, and `identity_verified_at`, `checked_in_at`, `started_at` and
    `submitted_at` are all null."

    Design: Corner/state_machines/new_sitting_starts_scheduled_and_pending_assignment
    """
    env = setup_landscape(testing_site={"seat_count": 2})
    candidate = add_candidate(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}])
    code, batch = assign_code(env, batch, candidate)

    session = schedule_session(env, candidate, code, "2026-09-10T09:00:00Z")

    assert session["session_status"] == "SCHEDULED"
    assert session["proctoring_status"] == "PENDING_ASSIGNMENT"
    assert session["proctor_id"] is None
    assert session["accommodation_request_id"] is None
    assert session["reschedule_count"] == 0
    assert session["version"] == 1
    assert session["identity_verified_at"] is None
    assert session["checked_in_at"] is None
    assert session["started_at"] is None
    assert session["submitted_at"] is None
    assert session["allowed_minutes"] == 120
    assert session["scheduled_end_at"] == "2026-09-10T11:00:00Z"
    assert get_success_data(api.get_testing_site(
        env["testing_site"]["id"], env["admin_headers"]))["reserved_seat_minutes"] == 120
    _, meta = validate_paginated(api.list_proctors(env["admin_headers"]))
    assert meta["total_count"] == 0


def test_opening_an_accommodation_review_decides_nothing_by_itself(api):
    """The first hop only moves REQUESTED to UNDER_REVIEW; the decision hop is what
    writes the granted multiplier, which may be less than was asked for.

    PRD: "Taking a request into review moves `REQUESTED → UNDER_REVIEW` and records
    the reviewing operator's `X-User-ID` in `reviewed_by_user_id`; attempting it on
    a request that is not `REQUESTED` answers `ERR_ACCOMMODATION_STATE_INVALID`
    (HTTP 409), and the same code answers a decision on a request that is not
    `UNDER_REVIEW`."

    PRD: "When `approved_multiplier` is supplied it must be less than or equal to
    `requested_multiplier` and greater than or equal to 1.0 — an operator may grant
    less than was asked for but never more."

    Design: Corner/state_machines/accommodation_review_open_then_approve_records_multiplier_and_reviewer
    """
    env = setup_landscape(with_site=False)
    candidate = add_candidate(env)

    request = get_success_data(api.create_accommodation_request(
        f.create_accommodation_request_payload(
            candidate["id"], accommodation_type="EXTRA_TIME",
            requested_multiplier=1.75, documentation_ref="DOC-ADA-118"),
        env["provider_headers"]), 201)
    assert request["status"] == "REQUESTED"
    assert request["approved_multiplier"] is None
    assert request["reviewed_by_user_id"] is None

    opened = get_success_data(api.open_accommodation_review(request["id"], _ALT_ADMIN))
    assert opened["status"] == "UNDER_REVIEW"
    assert opened["approved_multiplier"] is None

    decided = get_success_data(api.review_accommodation(
        request["id"], f.create_accommodation_review_payload(
            "APPROVE", approved_multiplier=1.5,
            decision_reason="Documentation supports 1.5x only"), _ALT_ADMIN))

    assert decided["status"] == "APPROVED"
    assert float(decided["approved_multiplier"]) == 1.5
    assert decided["reviewed_by_user_id"] == "admin-ops-2"
    assert decided["decision_reason"] == "Documentation supports 1.5x only"
    assert float(decided["requested_multiplier"]) == 1.75


def test_releasing_the_exam_before_check_in_is_an_undeclared_transition(api):
    """IN_PROGRESS is reachable only from CHECKED_IN, and the refusal leaves
    started_at null so the later legal release still records the real instant.

    PRD: "Releasing the exam takes no body at all. It requires the sitting to be
    `CHECKED_IN` with a non-null `identity_verified_at`, and moves `session_status`
    `CHECKED_IN → IN_PROGRESS` with `started_at` set to the logical clock."

    PRD: "Submission is only valid from `IN_PROGRESS`, and any other
    `session_status` answers `ERR_SESSION_STATE_INVALID`."

    Design: Corner/state_machines/start_before_check_in_is_rejected_as_session_state_invalid
    """
    env = setup_sitting(stage="SCHEDULED")
    admin, session = env["admin_headers"], env["session"]
    set_clock("2026-09-10T08:45:00Z", admin)

    premature = api.start_exam_session(session["id"], env["proctor_headers"])

    validate_error(premature, "ERR_SESSION_STATE_INVALID", 409)
    unchanged = get_success_data(api.get_exam_session(session["id"], admin))
    assert unchanged["session_status"] == "SCHEDULED"
    assert unchanged["started_at"] is None
    assert unchanged["checked_in_at"] is None

    checked_in = get_success_data(api.check_in_exam_session(
        session["id"], f.create_check_in_payload(), env["proctor_headers"]))
    assert checked_in["session_status"] == "CHECKED_IN"

    started = get_success_data(api.start_exam_session(
        session["id"], env["proctor_headers"]))
    assert started["session_status"] == "IN_PROGRESS"
    assert started["started_at"] == "2026-09-10T08:45:00Z"


def test_a_second_cancellation_is_refused_and_repeats_no_release(api):
    """CANCELLED is terminal, and the refusal must not double-release the code or
    the two reservations.

    PRD: "Cancelling a sitting supplies a `reason` and is permitted while the
    sitting's `session_status` is either `SCHEDULED` or `CHECKED_IN`."

    PRD: "The redeemed access code moves `ASSIGNED → AVAILABLE` with its
    `candidate_id` and `assigned_at` cleared to null and its
    `assignment_release_count` grown by one."

    Design: Corner/state_machines/second_cancellation_of_a_cancelled_sitting_is_rejected
    """
    env = setup_sitting(stage="SCHEDULED")
    admin, session = env["admin_headers"], env["session"]
    first = get_success_data(api.cancel_exam_session(
        session["id"], f.create_cancellation_payload("Candidate withdrew"),
        env["provider_headers"]))
    assert (first["session_status"], first["proctoring_status"]) == ("CANCELLED", "CLEARED")

    second = api.cancel_exam_session(
        session["id"],
        f.create_cancellation_payload("Duplicate withdrawal notice from the same office"),
        env["provider_headers"])

    validate_error(second, "ERR_SESSION_STATE_INVALID", 409)
    code = get_success_data(api.get_access_code(
        env["access_code"]["id"], env["provider_headers"]))
    assert code["assignment_release_count"] == 1
    assert code["status"] == "AVAILABLE"
    batch = get_success_data(api.get_access_code_batch(
        env["batch"]["id"], env["provider_headers"]))
    assert (batch["available_count"], batch["assigned_count"]) == (1, 0)
    assert batch["status"] == "ACTIVE"
    assert (batch["available_count"] + batch["assigned_count"] + batch["consumed_count"]
            + batch["voided_count"]) == batch["quantity_purchased"] == 1
    assert get_success_data(api.get_proctor(
        env["proctor"]["id"], admin))["reserved_minutes"] == 0
    assert get_success_data(api.get_testing_site(
        env["testing_site"]["id"], admin))["reserved_seat_minutes"] == 0


def test_the_registration_decision_only_ever_leaves_pending_once(api):
    """Replaying APPROVE, and flipping to REJECT afterwards, are both refused and
    the proctor's row is untouched.

    PRD: "Adjudicating a registration that is not `PENDING` is rejected with
    `ERR_PROCTOR_STATE_INVALID` (HTTP 409), and the same code answers an audit
    opening on a proctor that is not `REGISTERED`, an audit closure on a proctor
    that is not `UNDER_AUDIT`, and a reinstatement of a proctor that is not
    `SUSPENDED`."

    PRD: "`REJECT` advances `PENDING → REJECTED`, which is terminal: a rejected
    proctor can never be assigned to a sitting."

    Design: Corner/state_machines/repeated_registration_decision_on_registered_proctor_is_rejected
    """
    env = setup_landscape(with_site=False)
    proctor = add_proctor(env, registered=False)
    approved = get_success_data(api.decide_proctor_registration(
        proctor["id"], f.create_registration_decision_payload("APPROVE"), _ALT_ADMIN))
    assert approved["registration_status"] == "REGISTERED"

    replayed = api.decide_proctor_registration(
        proctor["id"], f.create_registration_decision_payload("APPROVE"), _ALT_ADMIN)
    late_reject = api.decide_proctor_registration(
        proctor["id"],
        f.create_registration_decision_payload("REJECT", decision_note="Second thoughts"),
        _ALT_ADMIN)

    validate_error(replayed, "ERR_PROCTOR_STATE_INVALID", 409)
    validate_error(late_reject, "ERR_PROCTOR_STATE_INVALID", 409)
    after = get_success_data(api.get_proctor(proctor["id"], env["admin_headers"]))
    assert after["registration_status"] == "REGISTERED"
    assert after["version"] == approved["version"]


def test_reinstatement_is_gated_on_suspension_not_on_being_inactive(api):
    """The same reinstatement body is refused on a REGISTERED proctor and accepted
    once a real suspension has happened.

    PRD: "Reinstatement runs the opposite way but is deliberately not symmetric:
    supplying a `remediation_ref` moves `SUSPENDED → REGISTERED` and clears
    `suspended_reason` back to null, but sittings already left in
    `PENDING_REPROCTOR` are **not** auto-reassigned."

    PRD: "On `SUSPEND` the registration moves `UNDER_AUDIT → SUSPENDED` with
    `suspended_reason` `AUDIT_FAILURE`."

    Design: Corner/state_machines/reinstatement_of_a_registered_proctor_is_rejected
    """
    env = setup_landscape(with_site=False)
    proctor = add_proctor(env)
    payload = f.create_reinstatement_payload(remediation_ref="REM-2026-77")

    wrong_state = api.reinstate_proctor(proctor["id"], payload, _ALT_ADMIN)

    validate_error(wrong_state, "ERR_PROCTOR_STATE_INVALID", 409)
    assert get_success_data(api.get_proctor(
        proctor["id"], _ALT_ADMIN))["registration_status"] == "REGISTERED"

    under_audit = get_success_data(api.open_proctor_audit(
        proctor["id"], f.create_audit_open_payload(
            audit_reason="Roster paperwork complaint"), _ALT_ADMIN))
    assert under_audit["registration_status"] == "UNDER_AUDIT"

    suspended = get_success_data(api.close_proctor_audit(
        proctor["id"], f.create_audit_close_payload(
            outcome="SUSPEND", audit_note="Paperwork missing"), _ALT_ADMIN))
    assert suspended["registration_status"] == "SUSPENDED"
    assert suspended["suspended_reason"] == "AUDIT_FAILURE"
    assert float(suspended["risk_score"]) == 0.00

    reinstated = get_success_data(api.reinstate_proctor(
        proctor["id"], payload, _ALT_ADMIN))
    assert reinstated["registration_status"] == "REGISTERED"
    assert reinstated["suspended_reason"] is None


def test_submission_lands_six_effects_and_holds_the_interval(api):
    """One call stamps the sitting, attests the other axis, consumes the code,
    counts the proctor's session and mints a PROVISIONAL report — while the
    reservations stay held.

    PRD: "The redeemed code moves `ASSIGNED → CONSUMED` with `consumed_at` set to
    the logical clock, which drops the batch's `assigned_count` by one and lifts its
    `consumed_count` by one."

    PRD: "The proctor's `proctored_session_count` grows by one — but their
    `reserved_minutes` is deliberately **not** released here; the interval stays
    held until the score is finalized."

    PRD: "`voided_item_count` and `voided_correct_count` are both zero until
    finalization, `final_scaled_score` and `pass_flag` are both null,
    `finalized_by_user_id` and `released_at` are null."

    Design: Corner/state_machines/submission_side_effects_consume_code_and_attest_the_sitting
    """
    env = setup_sitting(stage="IN_PROGRESS")
    admin = env["admin_headers"]

    report = submit_session(env, env["session"], env["proctor"],
                            scored_correct_count=60, pretest_correct_count=4)

    assert report["status"] == "PROVISIONAL"
    assert report["raw_correct_count"] == 60
    assert report["pretest_correct_count"] == 4
    assert report["provisional_scaled_score"] == 75
    assert report["effective_cut_score"] == 70
    assert report["final_scaled_score"] is None
    assert report["pass_flag"] is None
    assert report["released_at"] is None

    session = get_success_data(api.get_exam_session(env["session"]["id"], admin))
    assert session["session_status"] == "SUBMITTED"
    assert session["submitted_at"] == "2026-09-10T09:00:00Z"
    assert session["proctoring_status"] == "ATTESTED"

    code = get_success_data(api.get_access_code(
        env["access_code"]["id"], env["provider_headers"]))
    assert code["status"] == "CONSUMED"
    assert code["consumed_at"] == "2026-09-10T09:00:00Z"
    batch = get_success_data(api.get_access_code_batch(
        env["batch"]["id"], env["provider_headers"]))
    assert (batch["available_count"], batch["assigned_count"],
            batch["consumed_count"], batch["voided_count"]) == (0, 0, 1, 0)

    proctor = get_success_data(api.get_proctor(env["proctor"]["id"], admin))
    assert proctor["proctored_session_count"] == 1
    assert proctor["reserved_minutes"] == 120
    assert get_success_data(api.get_testing_site(
        env["testing_site"]["id"], admin))["reserved_seat_minutes"] == 120


def test_check_in_is_guarded_by_the_other_dimension_not_by_its_own(api):
    """With nobody attached the check-in fails on the proctoring axis, and attaching
    a proctor both flips that axis and reserves the minutes.

    PRD: "A sitting whose `proctoring_status` is `PENDING_ASSIGNMENT` or
    `PENDING_REPROCTOR` has nobody to run it, and check-in, release and submission
    are all rejected with `ERR_SESSION_PROCTOR_UNASSIGNED` (HTTP 409) in that
    case."

    PRD: "The newly attached proctor's `reserved_minutes` grows by the sitting's
    `allowed_minutes` and, when a proctor is being replaced rather than added, the
    outgoing proctor's `reserved_minutes` falls by the same figure."

    Design: Corner/state_machines/check_in_is_guarded_until_a_proctor_is_attached
    """
    env = setup_sitting(stage="SCHEDULED", with_proctor=False)
    admin, session, proctor = env["admin_headers"], env["session"], env["proctor"]
    set_clock("2026-09-10T08:45:00Z", admin)
    assert get_success_data(api.get_proctor(proctor["id"], admin))["reserved_minutes"] == 0

    unassigned = api.check_in_exam_session(
        session["id"], f.create_check_in_payload(), env["proctor_headers"])

    validate_error(unassigned, "ERR_SESSION_PROCTOR_UNASSIGNED", 409)
    assert get_success_data(api.get_exam_session(
        session["id"], admin))["session_status"] == "SCHEDULED"

    attached = get_success_data(api.assign_session_proctor(
        session["id"], {"proctor_id": proctor["id"]}, env["provider_headers"]))
    assert attached["proctoring_status"] == "ASSIGNED"
    assert attached["proctor_id"] == proctor["id"]
    assert get_success_data(api.get_proctor(proctor["id"], admin))["reserved_minutes"] == 120

    checked_in = get_success_data(api.check_in_exam_session(
        session["id"], f.create_check_in_payload(), env["proctor_headers"]))
    assert checked_in["session_status"] == "CHECKED_IN"
    assert checked_in["checked_in_at"] == "2026-09-10T08:45:00Z"
    assert checked_in["identity_verified_at"] == "2026-09-10T08:45:00Z"


def test_the_expiry_sweep_keeps_the_expired_code_instead_of_restocking_it(api):
    """Phase one cascades batch to codes to sitting, and the cancelled sitting's
    code stays EXPIRED rather than returning to the pool.

    PRD: "Every batch whose `status` is `ACTIVE` or `DEPLETED` and whose
    `expires_at` falls strictly before `run_epoch` moves to `EXPIRED`."

    PRD: "An `ASSIGNED` code held by a sitting that is already `CHECKED_IN` or
    `IN_PROGRESS` is left alone — a candidate mid-exam is not disconnected by a
    sweep — whereas a `SCHEDULED` sitting holding an expired code is moved to
    `CANCELLED` without the code being returned to the batch."

    PRD: "No refund of any kind is posted for an expiry; only a deliberate void
    refunds money."

    Design: Corner/state_machines/compliance_run_expires_batch_and_cascades_down_to_codes_and_sitting
    """
    env = setup_landscape(testing_site={"seat_count": 2})
    admin = env["admin_headers"]
    candidate = add_candidate(env)
    proctor = add_proctor(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 2}],
                           expires_at="2026-09-05T00:00:00Z")
    code, batch = assign_code(env, batch, candidate)
    session = schedule_session(env, candidate, code, "2026-09-10T09:00:00Z",
                               proctor=proctor)
    set_clock("2026-09-06T00:00:00Z", admin)

    summary = get_success_data(api.create_compliance_run(admin), 201)

    assert summary["run_epoch"] == "2026-09-06T00:00:00Z"
    assert summary["batches_expired_count"] == 1
    assert summary["certificates_expired_count"] == 0
    assert summary["registrations_delinquent_count"] == 0
    assert summary["reminder_notices_sent_count"] == 0
    assert summary["notified_certificate_ids"] == []

    swept = get_success_data(api.get_access_code_batch(batch["id"], env["provider_headers"]))
    assert swept["status"] == "EXPIRED"
    assert (swept["available_count"], swept["assigned_count"],
            swept["consumed_count"], swept["voided_count"]) == (0, 0, 0, 2)
    _, meta = validate_paginated(api.list_access_codes(
        env["provider_headers"], params={"batch_id": batch["id"], "status": "EXPIRED"}))
    assert meta["total_count"] == 2
    assert get_success_data(api.get_exam_session(
        session["id"], admin))["session_status"] == "CANCELLED"
    assert get_success_data(api.get_access_code(
        code["id"], env["provider_headers"]))["status"] == "EXPIRED"
    assert get_success_data(api.get_training_provider(
        env["provider"]["id"], admin))["credit_balance_cents"] == 492476


def test_finalization_clears_the_proctoring_axis_only_when_nothing_is_pending(api):
    """An OPEN incident holds the ATTESTED axis in place through finalization; the
    later dismissal is what clears it, and the reservations release either way.

    PRD: "The sitting's `proctoring_status` moves `ATTESTED → CLEARED`, but only
    when no security incident on that sitting has a `status` of `OPEN` or
    `UNDER_REVIEW`; when an unresolved incident exists the `proctoring_status` stays
    `ATTESTED`."

    PRD: "And the sitting's interval is released here rather than at submission: the
    site's `reserved_seat_minutes` and the assigned proctor's `reserved_minutes`
    each fall by the sitting's `allowed_minutes`."

    PRD: "Only `SUBSTANTIATED` incidents contribute weight; incidents still `OPEN`
    or `UNDER_REVIEW`, and incidents that were `DISMISSED`, contribute nothing."

    Design: Corner/state_machines/finalization_clears_the_sitting_only_when_no_incident_is_pending
    """
    env = setup_sitting(stage="IN_PROGRESS")
    admin = env["admin_headers"]
    set_clock("2026-09-10T10:30:00Z", admin)
    report = submit_session(env, env["session"], env["proctor"],
                            scored_correct_count=60, pretest_correct_count=4)
    incident = file_incident(
        env, env["session"], env["proctor"], severity="MINOR",
        category="PROHIBITED_MATERIAL",
        narrative="Powered-off phone found in a jacket on the candidate's chair")
    assert incident["status"] == "OPEN"
    assert incident["severity_weight"] == 1

    final = finalize_report(env, report, admin_headers=_SCORING_ADMIN)

    assert final["status"] == "FINAL"
    assert final["final_scaled_score"] == 75
    assert final["pass_flag"] is True
    assert final["finalized_by_user_id"] == "admin-scoring-1"
    assert final["released_at"] == "2026-09-10T10:30:00Z"
    held = get_success_data(api.get_exam_session(env["session"]["id"], admin))
    assert held["session_status"] == "CLOSED"
    assert held["proctoring_status"] == "ATTESTED"
    assert get_success_data(api.get_proctor(
        env["proctor"]["id"], admin))["reserved_minutes"] == 0
    assert get_success_data(api.get_testing_site(
        env["testing_site"]["id"], admin))["reserved_seat_minutes"] == 0

    reviewed = take_incident_into_review(env, incident, admin_headers=_SECURITY_ADMIN)
    assert reviewed["status"] == "UNDER_REVIEW"
    assert get_success_data(api.get_exam_session(
        env["session"]["id"], admin))["proctoring_status"] == "INCIDENT_UNDER_REVIEW"

    dismissed = resolve_incident(
        env, incident, outcome="DISMISS", admin_headers=_SECURITY_ADMIN,
        resolution_note="Phone powered off and never handled during the exam")
    assert dismissed["status"] == "DISMISSED"
    assert get_success_data(api.get_exam_session(
        env["session"]["id"], admin))["proctoring_status"] == "CLEARED"
    assert get_success_data(api.get_score_report(
        report["id"], admin))["status"] == "FINAL"
    _, certificates_meta = validate_paginated(api.list_certificates(
        admin, params={"candidate_id": env["candidate"]["id"]}))
    assert certificates_meta["total_count"] == 0
    proctor = get_success_data(api.get_proctor(env["proctor"]["id"], admin))
    assert proctor["substantiated_incident_weight_total"] == 0
    assert float(proctor["risk_score"]) == 0.00
