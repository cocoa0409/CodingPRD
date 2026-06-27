"""Session / escalation / appointment / report state-machine behaviour.

Covers the escalation fork-join (uphold vs dismiss), the session pause/resume and
review-held cycles, and the idempotent / invalid-transition / precondition /
terminal-lockdown rejections across appointments, sessions, and reports.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    api_client,
    make_proctor_headers,
    make_review_officer_headers,
    make_candidate_headers,
    setup_under_review_escalation,
    setup_session_with_open_escalation,
    create_active_session,
    create_completed_session,
    setup_catalog,
    create_appointment,
    set_clock,
    build_terminal_session_with_score,
    deliver_report,
    create_decide_payload,
    create_candidate,
    create_proctor,
    raise_flag,
    get_session,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def test_escalation_uphold_voids_session_and_consumes_appointment(api):
    """PRD §3.6: "A `UPHELD` verdict sets the escalation's `verdict` to `UPHELD`, moves
    it to `UPHELD`, and drives the held session from `REVIEW_HELD` to `VOIDED` with a
    `void_reason` of `ESCALATION_UPHELD`; the underlying appointment is driven to
    `CONSUMED`, the triggering incident flag is resolved to `RESOLVED`, and the
    proctor's `active_session_count` and `load_factor` are recomputed."

    Design: Difficulty/non_linear_state_machine/escalation_fork_join_uphold_vs_dismiss_divergent_side_effects
    """
    ctx = setup_under_review_escalation(flag_kind="SECOND_FACE", flag_severity="MAJOR")
    res = api.decide_escalation(
        ctx["escalation"]["id"],
        create_decide_payload("UPHELD", ctx["escalation_version"]),
        make_review_officer_headers(ctx["officer"]["id"]))
    validate_success(res, 200)

    session = get_session(ctx["session"]["id"], ctx["opener"]["id"])
    assert session["status"] == "VOIDED"
    assert session["void_reason"] == "ESCALATION_UPHELD"
    appt = validate_success(api.get_appointment(ctx["appointment"]["id"], COORD), 200)
    assert appt["status"] == "CONSUMED"


def test_escalation_dismiss_returns_session_to_active(api):
    """PRD §3.6: "A `DISMISSED` verdict sets the escalation's `verdict` to `DISMISSED`,
    moves it to `DISMISSED`, and releases the session from `REVIEW_HELD` back to
    `ACTIVE` (provided no other escalation on that session is still open or under
    review); the triggering incident flag is resolved to `RESOLVED` and the session's
    `integrity_score` is recomputed now that the cleared flag no longer counts."

    Design: Difficulty/non_linear_state_machine/escalation_fork_join_uphold_vs_dismiss_divergent_side_effects
    """
    ctx = setup_under_review_escalation(flag_kind="GAZE_OFF_SCREEN", flag_severity="MINOR")
    res = api.decide_escalation(
        ctx["escalation"]["id"],
        create_decide_payload("DISMISSED", ctx["escalation_version"]),
        make_review_officer_headers(ctx["officer"]["id"]))
    decided = validate_success(res, 200)
    assert decided["status"] == "DISMISSED"

    session = get_session(ctx["session"]["id"], ctx["opener"]["id"])
    assert session["status"] == "ACTIVE"


def test_session_cycles_active_paused_active_then_review_held_back_to_active(api):
    """PRD §3.4: "the proctor pauses an `ACTIVE` session, moving it to `PAUSED`" and
    "The proctor resumes a `PAUSED` session back to `ACTIVE`." PRD §3.6: "releases the
    session from `REVIEW_HELD` back to `ACTIVE` (provided no other escalation on that
    session is still open or under review)".

    Design: Difficulty/non_linear_state_machine/session_paused_resume_cycle_then_review_held_return
    """
    cat = setup_catalog(monitoring_mode="LIVE", lockdown_required=False)
    opener = cat["proctor"]
    officer = create_proctor(cat["institution"]["id"], full_name="Review Officer")
    set_clock("2026-07-01T09:00:00Z")
    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"],
                              opener["id"], "2026-07-01T09:00:00Z")
    session = validate_success(
        api.check_in(appt["id"], make_candidate_headers(cat["candidate"]["id"])), 201)

    paused = validate_success(api.pause_session(session["id"], make_proctor_headers(opener["id"])), 200)
    assert paused["status"] == "PAUSED"
    resumed = validate_success(api.resume_session(session["id"], make_proctor_headers(opener["id"])), 200)
    assert resumed["status"] == "ACTIVE"

    flag = raise_flag(session["id"], opener["id"], "GAZE_OFF_SCREEN", "MINOR")
    esc = validate_success(api.create_escalation(
        {"session_id": session["id"], "incident_flag_id": flag["id"]},
        make_proctor_headers(opener["id"])), 201)
    claimed = validate_success(api.claim_escalation(
        esc["id"], make_review_officer_headers(officer["id"])), 200)
    decided = validate_success(api.decide_escalation(
        esc["id"], create_decide_payload("DISMISSED", claimed["version"]),
        make_review_officer_headers(officer["id"])), 200)
    assert decided["status"] == "DISMISSED"

    final = get_session(session["id"], opener["id"])
    assert final["status"] == "ACTIVE", "session returns to ACTIVE a second time after dismiss"


def test_session_revisits_active_can_be_paused_again_after_dismiss(api):
    """PRD §3.4: "the proctor pauses an `ACTIVE` session, moving it to `PAUSED`". PRD
    §3.6: "releases the session from `REVIEW_HELD` back to `ACTIVE` (provided no other
    escalation on that session is still open or under review)".

    Design: Difficulty/non_linear_state_machine/session_paused_resume_cycle_then_review_held_return
    """
    ctx = setup_under_review_escalation(flag_kind="GAZE_OFF_SCREEN", flag_severity="MINOR")
    validate_success(api.decide_escalation(
        ctx["escalation"]["id"],
        create_decide_payload("DISMISSED", ctx["escalation_version"]),
        make_review_officer_headers(ctx["officer"]["id"])), 200)
    # The session is genuinely ACTIVE again: a fresh pause must succeed.
    paused = validate_success(
        api.pause_session(ctx["session"]["id"], make_proctor_headers(ctx["opener"]["id"])), 200)
    assert paused["status"] == "PAUSED", "session re-entered ACTIVE and can be paused again"


def test_resume_active_session_rejected_invalid_state(api):
    """PRD §3.4: "The proctor resumes a `PAUSED` session back to `ACTIVE`." PRD §3.4:
    "Any transition requested against a session that is not in the required state is
    rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/resume_non_paused_session_returns_invalid_state
    """
    ctx = create_active_session(monitoring_mode="LIVE")
    res = api.resume_session(ctx["session"]["id"], make_proctor_headers(ctx["proctor"]["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_complete_blocked_while_escalation_open(api):
    """PRD §3.4: "a session may only be completed from `ACTIVE` and only when no
    escalation on it is still `OPEN` or `UNDER_REVIEW`." PRD §3.4: "Any transition
    requested against a session that is not in the required state is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complete_blocked_while_escalation_open
    """
    ctx = setup_session_with_open_escalation(flag_kind="SECOND_FACE", flag_severity="MAJOR")
    res = api.complete_session(ctx["session"]["id"], make_proctor_headers(ctx["opener"]["id"]))
    validate_error(res, "ERR_INVALID_STATE")


def test_checkin_before_scheduled_start_rejected(api):
    """PRD §3.3: "The logical clock must have reached or passed the appointment's
    `scheduled_start_utc`; a check-in attempted before that instant is rejected with
    `ERR_CHECKIN_TOO_EARLY`." PRD §2.4: "The server's logical clock starts at
    `2026-01-01T00:00:00Z`; before any clock-setting call is made the clock reads
    exactly this default".

    Design: Corner/state_machines/checkin_before_scheduled_start_rejected
    """
    # Clock is deliberately left at the 2026-01-01 startup default; appointment is at
    # 2026-07-01, so check-in is too early.
    cat = setup_catalog(monitoring_mode="LIVE", lockdown_required=False)
    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"],
                              cat["proctor"]["id"], "2026-07-01T09:00:00Z")
    res = api.check_in(appt["id"], make_candidate_headers(cat["candidate"]["id"]))
    validate_error(res, "ERR_CHECKIN_TOO_EARLY")


def test_cancel_already_cancelled_appointment_invalid_state(api):
    """PRD §3.3: "A `SchedulingCoordinator` may cancel an appointment that is either
    `SCHEDULED` or `CHECKED_IN`, moving it to `CANCELLED`."

    Design: Corner/state_machines/cancel_already_cancelled_appointment_returns_invalid_state
    """
    cat = setup_catalog(lockdown_required=False)
    appt = create_appointment(cat["exam"]["id"], cat["candidate"]["id"],
                              cat["proctor"]["id"], "2026-07-01T09:00:00Z")
    validate_success(api.cancel_appointment(appt["id"], COORD), 200)
    res = api.cancel_appointment(appt["id"], COORD)
    validate_error(res, "ERR_INVALID_STATE")


def test_deliver_already_delivered_report_invalid_state(api):
    """PRD §3.7: "Delivery moves the report from `DRAFT` to `DELIVERED`". PRD §3.7:
    "A freshly drafted report opens with `status` `DRAFT`; its `status` is one of
    `DRAFT` or `DELIVERED`".

    Design: Corner/state_machines/deliver_already_delivered_report_returns_invalid_state
    """
    cat = setup_catalog(monitoring_mode="LIVE", lockdown_required=False)
    inst, proctor, cand, exam = (cat["institution"], cat["proctor"],
                                 cat["candidate"], cat["exam"])
    _, sess = build_terminal_session_with_score(
        inst["id"], exam["id"], cand["id"], proctor["id"], [],
        "2026-07-01T09:00:00Z")
    report = deliver_report(inst["id"], cand["id"], exam["id"], [sess["id"]])
    res = api.deliver_integrity_report(report["id"], COORD)
    validate_error(res, "ERR_INVALID_STATE")
