"""One sitting, two independent state axes; and the access-code batch's
re-enterable ACTIVE/DEPLETED inventory loop."""
from test_helpers import (
    TEST_USERS,
    add_candidate,
    add_proctor,
    assign_code,
    check_in_session,
    factories as f,
    file_incident,
    finalize_report,
    get_success_data,
    purchase_batch,
    resolve_incident,
    schedule_session,
    setup_landscape,
    setup_sitting,
    start_session,
    submit_session,
    take_incident_into_review,
    validate_success,
)

_SECURITY_ADMIN = TEST_USERS["security_admin_headers"]


def _axes(api, session_id, headers):
    session = get_success_data(api.get_exam_session(session_id, headers))
    return session["session_status"], session["proctoring_status"]


def test_attaching_a_proctor_moves_only_the_proctoring_axis(api):
    """A sitting created without a proctor sits at PENDING_ASSIGNMENT, and the
    later attachment advances that axis while session_status stays SCHEDULED.

    PRD: "Its `proctoring_status` is `ASSIGNED` when a `proctor_id` was supplied
    and `PENDING_ASSIGNMENT` when it was not."

    PRD: "`proctoring_status` moves `PENDING_ASSIGNMENT → ASSIGNED` for a sitting
    that never had a proctor"

    Design: Difficulty/non_linear_state_machine/exam_session_parallel_dimensions_evolve_independently
    """
    env = setup_sitting(stage="SCHEDULED", with_proctor=False)
    session = env["session"]
    assert (session["session_status"], session["proctoring_status"]) == (
        "SCHEDULED", "PENDING_ASSIGNMENT")
    assert session["proctor_id"] is None

    attached = get_success_data(api.assign_session_proctor(
        session["id"], {"proctor_id": env["proctor"]["id"]}, env["provider_headers"]))

    assert (attached["session_status"], attached["proctoring_status"]) == (
        "SCHEDULED", "ASSIGNED")
    assert attached["proctor_id"] == env["proctor"]["id"]
    assert get_success_data(api.get_proctor(
        env["proctor"]["id"], env["admin_headers"]))["reserved_minutes"] == 120


def test_the_two_session_axes_advance_one_at_a_time_through_delivery(api):
    """Check-in moves the delivery axis alone; submission then moves both; and
    finalization lands the pair at CLOSED/CLEARED.

    PRD: "On success the sitting moves `SCHEDULED → CHECKED_IN`, both
    `identity_verified_at` and `checked_in_at` are set to the logical clock, and
    the presented `id_document_type`, `id_document_expires_on` and
    `biometric_match_score` are recorded on the sitting."

    PRD: "The sitting moves `IN_PROGRESS → SUBMITTED` with `submitted_at` set to
    the logical clock, and its `proctoring_status` moves `ASSIGNED → ATTESTED`"

    Design: Difficulty/non_linear_state_machine/exam_session_parallel_dimensions_evolve_independently
    """
    env = setup_sitting(stage="SCHEDULED", with_proctor=False)
    session = env["session"]
    proctor, admin = env["proctor"], env["admin_headers"]
    get_success_data(api.assign_session_proctor(
        session["id"], {"proctor_id": proctor["id"]}, env["provider_headers"]))

    checked_in = check_in_session(env, session, proctor)
    assert (checked_in["session_status"], checked_in["proctoring_status"]) == (
        "CHECKED_IN", "ASSIGNED")

    started = start_session(env, checked_in, proctor)
    assert (started["session_status"], started["proctoring_status"]) == (
        "IN_PROGRESS", "ASSIGNED")

    report = submit_session(env, started, proctor, scored_correct_count=60)
    assert _axes(api, session["id"], admin) == ("SUBMITTED", "ATTESTED")

    finalize_report(env, report, admin_headers=TEST_USERS["scoring_admin_headers"])
    assert _axes(api, session["id"], admin) == ("CLOSED", "CLEARED")


def test_proctoring_axis_still_cycles_after_the_delivery_axis_is_terminal(api):
    """A CLOSED sitting is dragged back into review and cleared again, so the
    proctoring axis completes a cycle the delivery axis never sees.

    PRD: "On success the incident moves `OPEN → UNDER_REVIEW` and the sitting's
    `proctoring_status` moves `ATTESTED → INCIDENT_UNDER_REVIEW` or `CLEARED →
    INCIDENT_UNDER_REVIEW`."

    PRD: "The incident moves `UNDER_REVIEW → DISMISSED` and the sitting's
    `proctoring_status` moves `INCIDENT_UNDER_REVIEW → CLEARED`."

    Design: Difficulty/non_linear_state_machine/exam_session_parallel_dimensions_evolve_independently
    """
    env = setup_sitting(stage="CLOSED", scored_correct_count=60,
                        scoring_admin_headers=TEST_USERS["scoring_admin_headers"])
    admin = env["admin_headers"]
    assert _axes(api, env["session"]["id"], admin) == ("CLOSED", "CLEARED")

    incident = file_incident(env, env["session"], env["proctor"], severity="MINOR")
    incident = take_incident_into_review(env, incident, admin_headers=_SECURITY_ADMIN)
    assert incident["status"] == "UNDER_REVIEW"
    assert _axes(api, env["session"]["id"], admin) == ("CLOSED", "INCIDENT_UNDER_REVIEW")

    dismissed = resolve_incident(env, incident, outcome="DISMISS",
                                 admin_headers=_SECURITY_ADMIN)
    assert dismissed["status"] == "DISMISSED"
    assert _axes(api, env["session"]["id"], admin) == ("CLOSED", "CLEARED")

    assert get_success_data(api.get_score_report(
        env["score_report"]["id"], admin))["status"] == "FINAL"
    proctor = get_success_data(api.get_proctor(env["proctor"]["id"], admin))
    assert proctor["substantiated_incident_weight_total"] == 0
    assert proctor["registration_status"] == "REGISTERED"


def test_batch_status_loops_depleted_active_depleted_as_one_code_moves(api):
    """A single-unit batch is depleted by an assignment, reopened by the
    cancellation cascade, then depleted again by a second assignment.

    PRD: "When `available_count` reaches zero the batch itself flips `ACTIVE →
    DEPLETED`, and a further assignment attempt then answers `ERR_BATCH_DEPLETED`."

    PRD: "And that counter change flips the batch `DEPLETED → ACTIVE` whenever
    `available_count` becomes greater than zero, making the batch assignable
    again."

    Design: Difficulty/non_linear_state_machine/access_code_batch_depleted_active_cycle_reenters
    """
    env = setup_landscape()
    candidate = add_candidate(env)
    proctor = add_proctor(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}])
    assert (batch["status"], batch["available_count"]) == ("ACTIVE", 1)

    code, batch = assign_code(env, batch, candidate)
    assert batch["status"] == "DEPLETED"
    assert (batch["available_count"], batch["assigned_count"]) == (0, 1)

    session = schedule_session(env, candidate, code, "2026-09-10T09:00:00Z",
                               proctor=proctor)
    cancelled = get_success_data(api.cancel_exam_session(
        session["id"], f.create_cancellation_payload(
            reason="Candidate rescheduled to a later cohort"),
        env["provider_headers"]))
    assert (cancelled["session_status"], cancelled["proctoring_status"]) == (
        "CANCELLED", "CLEARED")

    reopened = get_success_data(api.get_access_code_batch(
        batch["id"], env["provider_headers"]))
    assert reopened["status"] == "ACTIVE"
    assert (reopened["available_count"], reopened["assigned_count"]) == (1, 0)

    code_again, refreshed = assign_code(env, reopened, candidate)
    assert refreshed["status"] == "DEPLETED"
    assert (refreshed["available_count"], refreshed["assigned_count"]) == (0, 1)
    assert refreshed["quantity_purchased"] == 1
    assert refreshed["consumed_count"] == 0
    assert refreshed["voided_count"] == 0


def test_the_released_code_is_the_same_row_reassigned_with_a_release_counter(api):
    """Release and reassignment reuse one code row, and the release is counted.

    PRD: "The redeemed access code moves `ASSIGNED → AVAILABLE` with its
    `candidate_id` and `assigned_at` cleared to null and its
    `assignment_release_count` grown by one."

    Design: Difficulty/non_linear_state_machine/access_code_batch_depleted_active_cycle_reenters
    """
    env = setup_landscape()
    candidate = add_candidate(env)
    proctor = add_proctor(env)
    batch = purchase_batch(env, line_items=[{"bundle_type": "EXAM_ONLY", "quantity": 1}])
    code, batch = assign_code(env, batch, candidate)
    assert code["status"] == "ASSIGNED"
    assert code["assignment_release_count"] == 0

    session = schedule_session(env, candidate, code, "2026-09-10T09:00:00Z",
                               proctor=proctor)
    validate_success(api.cancel_exam_session(
        session["id"], f.create_cancellation_payload(), env["provider_headers"]))

    released = get_success_data(api.get_access_code(code["id"], env["provider_headers"]))
    assert released["status"] == "AVAILABLE"
    assert released["candidate_id"] is None
    assert released["assigned_at"] is None
    assert released["assignment_release_count"] == 1

    refreshed = get_success_data(api.get_access_code_batch(
        batch["id"], env["provider_headers"]))
    code_again, _ = assign_code(env, refreshed, candidate)
    assert code_again["id"] == code["id"]
    assert code_again["status"] == "ASSIGNED"
    assert code_again["assignment_release_count"] == 1
