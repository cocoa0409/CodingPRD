"""Lifecycle edges of a representation case.

These tests exercise the moments where a row's state changes shape: the state a
freshly created row is born in, the supervisor training loop and its pass mark,
the poll-session closing that carries a round and its case forward, the terminal
states that refuse every further action, and the objection that pushes a case
into and back out of its objection phase.
"""
from test_helpers import (
    BOARD,
    DIRECTOR,
    REQUIRED_TRAINING_MODULES,
    TRAINER,
    UNION,
    ApiErrorId,
    api_client,
    assert_absent,
    assert_instant_equals,
    assert_instants_equal,
    close_poll_session,
    close_session_payload,
    create_approved_message,
    create_campaign_communication_payload,
    create_objection_payload,
    create_supervisor_payload,
    create_voter_list_payload,
    file_objection,
    petition_version,
    post_tally,
    read_campaign_message,
    read_petition,
    read_poll_session,
    read_round,
    register_supervisor,
    rule_objection,
    rule_objection_payload,
    segregate_ballot,
    set_clock,
    setup_certified_case,
    setup_election_set,
    setup_polls_open,
    setup_scope_analysis,
    setup_tally_posted,
    train_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    verify_showing_payload,
)

# Two polling locations on the same round, sharing one time window.
SESSION_AT_CAFETERIA = {
    "location_code": "PLANT_1_CAFETERIA",
    "session_start_at": "2026-09-01T08:00:00Z",
    "session_end_at": "2026-09-01T12:00:00Z",
    "method": "MANUAL",
}
SESSION_AT_BREAKROOM = {
    "location_code": "PLANT_2_BREAKROOM",
    "session_start_at": "2026-09-01T08:00:00Z",
    "session_end_at": "2026-09-01T12:00:00Z",
    "method": "MANUAL",
}
SESSION_CLOSING_INSTANT = "2026-09-01T12:00:00Z"


def _round_with_two_sessions_and_three_challenges():
    """Polls open on a round carrying two sessions and three segregated ballots."""
    ctx = setup_polls_open(session_specs=[SESSION_AT_CAFETERIA, SESSION_AT_BREAKROOM])
    session_a, session_b = ctx["sessions"]
    ctx["ballots"] = [
        segregate_ballot(session_a["id"], challenger_party="EMPLOYER", basis="SUPERVISOR"),
        segregate_ballot(session_a["id"], challenger_party="UNION", basis="NOT_ON_LIST"),
        segregate_ballot(session_b["id"], challenger_party="EMPLOYER", basis="OUTSIDE_UNIT"),
    ]
    return ctx


def test_freshly_registered_supervisor_starts_untrained_with_no_history():
    """A supervisor registered against a case carries no training and no discipline yet.

    PRD: "A newly registered supervisor begins at `training_status` `UNTRAINED`, with `modules_completed` and `quiz_score` absent, `training_attempt_count` and `violation_count` at 0, and no `certified_at` or `last_violation_code`."

    Design: Corner/state_machines/initial_states_hold_for_every_freshly_created_row
    """
    ctx = setup_scope_analysis()

    resp = api_client.create_supervisor(
        create_supervisor_payload(ctx["petition"]["id"]), DIRECTOR
    )

    supervisor = validate_success(resp, 201)
    assert supervisor["training_status"] == "UNTRAINED"
    assert supervisor["training_attempt_count"] == 0
    assert supervisor["violation_count"] == 0
    assert_absent(supervisor, "modules_completed", "new supervisor")
    assert_absent(supervisor, "quiz_score", "new supervisor")
    assert_absent(supervisor, "certified_at", "new supervisor")
    assert_absent(supervisor, "last_violation_code", "new supervisor")


def test_freshly_drafted_campaign_message_starts_in_draft_at_zero_risk():
    """A brand new campaign message is an unscored draft credited to its author.

    PRD: "A draft starts at `status` `DRAFT` with `revision_round` 0, `risk_score` 0, `peerless_plywood_violation` false and `escalation_ack` false, records the drafting user's `X-User-ID` in `authored_by_user_id`, and leaves `reviewed_by_user_id`, `accuracy_reviewed_at`, `delivered_at` and `blocked_reason` absent."

    Design: Corner/state_machines/initial_states_hold_for_every_freshly_created_row
    """
    ctx = setup_election_set()

    resp = api_client.create_campaign_communication(
        create_campaign_communication_payload(ctx["petition"]["id"]), DIRECTOR
    )

    message = validate_success(resp, 201)
    assert message["status"] == "DRAFT"
    assert message["revision_round"] == 0
    assert message["risk_score"] == 0
    assert message["peerless_plywood_violation"] is False
    assert message["escalation_ack"] is False
    assert message["authored_by_user_id"] == DIRECTOR["X-User-ID"]
    assert_absent(message, "reviewed_by_user_id", "new draft")
    assert_absent(message, "accuracy_reviewed_at", "new draft")
    assert_absent(message, "delivered_at", "new draft")
    assert_absent(message, "blocked_reason", "new draft")


def test_newly_opened_voter_list_starts_in_draft_on_the_arrangement_deadline():
    """Opening a voter list produces a draft that inherits the arrangement's due date.

    PRD: "A successful create copies `due_at` from the arrangement's `voter_list_due_at`, starts the list at `status` `DRAFT`, and — this is the point of opening a fresh list — **supersedes** any list on the same case that is still `DRAFT` or `DEFICIENT`, moving each to the terminal `SUPERSEDED` state where it keeps its entries and its `cure_deadline_at` for the record but can never be submitted again."

    Design: Corner/state_machines/initial_states_hold_for_every_freshly_created_row
    """
    ctx = setup_election_set()
    petition_id = ctx["petition"]["id"]

    resp = api_client.create_voter_list(
        create_voter_list_payload(
            petition_id, ctx["agreement"]["id"], petition_version(petition_id)
        ),
        DIRECTOR,
    )

    voter_list = validate_success(resp, 201)
    assert voter_list["status"] == "DRAFT"
    assert_instants_equal(
        voter_list["due_at"], ctx["agreement"]["voter_list_due_at"], "voter list due_at"
    )


def test_stipulated_approval_mints_a_scheduled_first_round():
    """Approving the arrangement schedules round 1, copying the balloting window across.

    PRD: "Approval also schedules the balloting: an election round is created with `round_number` 1 and `status` `SCHEDULED`, copying `voting_method`, `election_date`, `polls_open_at` and `polls_close_at` from the approved arrangement."

    Design: Corner/state_machines/initial_states_hold_for_every_freshly_created_row
    """
    ctx = setup_election_set(
        fix_overrides={
            "polls_open_at": "2026-09-01T06:00:00Z",
            "polls_close_at": "2026-09-01T17:00:00Z",
        }
    )
    agreement = ctx["agreement"]

    election_round = validate_success(
        api_client.get_election_round(ctx["round"]["id"], BOARD)
    )

    assert election_round["status"] == "SCHEDULED"
    assert election_round["round_number"] == 1
    assert election_round["voting_method"] == agreement["voting_method"]
    assert election_round["election_date"] == agreement["approved_election_date"]
    assert_instant_equals(
        election_round["polls_open_at"], "2026-09-01T06:00:00Z", "round polls_open_at"
    )
    assert_instant_equals(
        election_round["polls_close_at"], "2026-09-01T17:00:00Z", "round polls_close_at"
    )


def test_first_round_carries_no_prior_round_reference():
    """The original election round has no set-aside predecessor to point back at.

    PRD: "Each round records the `petition_id` of its case, the `election_agreement_id` of the arrangement that produced it, its `round_number` — 1 for the original election and one higher for each rerun — and, on a rerun, the `prior_round_id` of the set-aside round it replaces, which is absent on round 1."

    Design: Corner/state_machines/initial_states_hold_for_every_freshly_created_row
    """
    ctx = setup_election_set()

    election_round = validate_success(
        api_client.get_election_round(ctx["round"]["id"], BOARD)
    )

    assert election_round["round_number"] == 1
    assert election_round["petition_id"] == ctx["petition"]["id"]
    assert election_round["election_agreement_id"] == ctx["agreement"]["id"]
    assert_absent(election_round, "prior_round_id", "round 1")


def test_training_attempt_at_the_pass_mark_certifies_the_supervisor():
    """A first attempt with all three modules and a score of exactly 80 certifies.

    PRD: "Certification is granted only when the attempt is complete on both counts: `modules_completed` must contain every one of the three required module codes — `TIPS_BOUNDARIES`, `PROHIBITED_CONDUCT` and `SOLICITATION_RULES` — and `quiz_score` must be at least 80."

    PRD: "A qualifying attempt increments `training_attempt_count`, records the score and the modules, stamps `certified_at` with the logical clock, and moves `training_status` from `UNTRAINED` to `TRAINED`."

    Design: Corner/state_machines/supervisor_training_pass_at_exact_threshold_marks_trained
    """
    ctx = setup_scope_analysis(clock="2026-08-03T09:00:00Z")
    supervisor = register_supervisor(ctx["petition"]["id"])

    resp = api_client.train_supervisor(
        supervisor["id"], train_payload(quiz_score=80), TRAINER
    )

    trained = validate_success(resp)
    assert trained["training_status"] == "TRAINED"
    assert trained["quiz_score"] == 80
    assert trained["training_attempt_count"] == 1
    assert sorted(trained["modules_completed"]) == sorted(REQUIRED_TRAINING_MODULES)
    assert_instant_equals(
        trained["certified_at"], "2026-08-03T09:00:00Z", "supervisor certified_at"
    )


def test_quiz_score_below_the_pass_mark_is_recorded_without_certifying():
    """A score of 79 with every module done is a self-loop, not a rejection.

    PRD: "An attempt that falls short — either because a required module is missing or because the score is below 80 — is recorded rather than rejected: it is a self-loop that leaves `training_status` at `UNTRAINED`, increments `training_attempt_count`, records the `quiz_score`, and withholds certification."

    Design: Corner/state_machines/supervisor_training_self_loop_counts_failed_attempts
    """
    ctx = setup_scope_analysis(clock="2026-08-03T09:00:00Z")
    supervisor = register_supervisor(ctx["petition"]["id"])

    resp = api_client.train_supervisor(
        supervisor["id"], train_payload(quiz_score=79), TRAINER
    )

    attempted = validate_success(resp)
    assert attempted["training_status"] == "UNTRAINED"
    assert attempted["quiz_score"] == 79
    assert attempted["training_attempt_count"] == 1
    assert attempted["violation_count"] == 0
    assert_absent(attempted, "certified_at", "supervisor after a failed attempt")


def test_missing_module_defeats_a_passing_score_until_a_complete_attempt_arrives():
    """Three attempts in a row: a low score, a high score with a module missing, then a
    complete attempt that finally certifies on the third try.

    PRD: "An attempt that falls short — either because a required module is missing or because the score is below 80 — is recorded rather than rejected: it is a self-loop that leaves `training_status` at `UNTRAINED`, increments `training_attempt_count`, records the `quiz_score`, and withholds certification."

    PRD: "A qualifying attempt increments `training_attempt_count`, records the score and the modules, stamps `certified_at` with the logical clock, and moves `training_status` from `UNTRAINED` to `TRAINED`."

    Design: Corner/state_machines/supervisor_training_self_loop_counts_failed_attempts
    """
    ctx = setup_scope_analysis(clock="2026-08-03T09:00:00Z")
    supervisor = register_supervisor(ctx["petition"]["id"])

    first = validate_success(
        api_client.train_supervisor(supervisor["id"], train_payload(quiz_score=79), TRAINER)
    )
    assert first["training_status"] == "UNTRAINED"
    assert first["training_attempt_count"] == 1

    second = validate_success(
        api_client.train_supervisor(
            supervisor["id"],
            train_payload(
                modules_completed=["TIPS_BOUNDARIES", "PROHIBITED_CONDUCT"], quiz_score=95
            ),
            TRAINER,
        )
    )
    assert second["training_status"] == "UNTRAINED"
    assert second["training_attempt_count"] == 2
    assert second["quiz_score"] == 95
    assert_absent(second, "certified_at", "supervisor after an incomplete attempt")

    third = validate_success(
        api_client.train_supervisor(supervisor["id"], train_payload(quiz_score=80), TRAINER)
    )
    assert third["training_status"] == "TRAINED"
    assert third["training_attempt_count"] == 3
    assert third["violation_count"] == 0
    assert_instant_equals(
        third["certified_at"], "2026-08-03T09:00:00Z", "supervisor certified_at"
    )


def test_closing_the_first_of_two_sessions_leaves_the_polls_open():
    """With a second location still voting, closing one session only moves that session.

    PRD: "Closing moves the session to the terminal `CLOSED` state, stamps `closed_at`, records the three counts, raises the round's `closed_session_count` by 1 and lowers its `scheduled_session_count` by 1."

    PRD: "When the closing of a session takes the round's `scheduled_session_count` to 0 and at least one session has closed, the round itself moves from `POLLS_OPEN` to `POLLS_CLOSED` within that same request, and the case's `case_status` becomes `VOTING_CLOSED`."

    Design: Corner/state_machines/closing_the_last_scheduled_session_bubbles_the_round_to_polls_closed
    """
    ctx = _round_with_two_sessions_and_three_challenges()
    cafeteria = ctx["sessions"][0]
    set_clock(SESSION_CLOSING_INSTANT)

    resp = api_client.close_poll_session(
        cafeteria["id"],
        close_session_payload(votes_for_count=30, votes_against_count=25, void_count=1),
        BOARD,
    )

    closed = validate_success(resp)
    assert closed["status"] == "CLOSED"
    assert_instant_equals(closed["closed_at"], SESSION_CLOSING_INSTANT, "session closed_at")
    election_round = read_round(ctx["round"]["id"])
    assert election_round["status"] == "POLLS_OPEN"
    assert election_round["scheduled_session_count"] == 1
    assert election_round["closed_session_count"] == 1
    assert read_petition(ctx["petition"]["id"])["case_status"] == "ELECTION_SET"


def test_closing_the_last_session_closes_the_polls_and_the_case():
    """The closing that empties the round's scheduled sessions carries the round and the
    case forward and sums the closed sessions' figures.

    PRD: "When the closing of a session takes the round's `scheduled_session_count` to 0 and at least one session has closed, the round itself moves from `POLLS_OPEN` to `POLLS_CLOSED` within that same request, and the case's `case_status` becomes `VOTING_CLOSED`."

    PRD: "At that point the round accumulates the closed sessions' figures: `provisional_votes_for`, `provisional_votes_against` and `provisional_void_count` are summed from the `CLOSED` sessions, and `ballots_cast_total` records every ballot that entered the box across the round."

    Design: Corner/state_machines/closing_the_last_scheduled_session_bubbles_the_round_to_polls_closed
    """
    ctx = _round_with_two_sessions_and_three_challenges()
    cafeteria, breakroom = ctx["sessions"]
    set_clock(SESSION_CLOSING_INSTANT)
    close_poll_session(cafeteria["id"], votes_for_count=30, votes_against_count=25, void_count=1)

    resp = api_client.close_poll_session(
        breakroom["id"],
        close_session_payload(votes_for_count=12, votes_against_count=14, void_count=0),
        BOARD,
    )

    closed = validate_success(resp)
    assert closed["status"] == "CLOSED"
    assert_instant_equals(closed["closed_at"], SESSION_CLOSING_INSTANT, "session closed_at")
    election_round = read_round(ctx["round"]["id"])
    assert election_round["status"] == "POLLS_CLOSED"
    assert election_round["scheduled_session_count"] == 0
    assert election_round["closed_session_count"] == 2
    assert election_round["provisional_votes_for"] == 42
    assert election_round["provisional_votes_against"] == 39
    assert election_round["provisional_void_count"] == 1
    assert_absent(election_round, "tally_posted_at", "round at POLLS_CLOSED")
    assert read_petition(ctx["petition"]["id"])["case_status"] == "VOTING_CLOSED"


def test_segregated_ballots_count_in_the_round_total_when_the_polls_close():
    """Three challenged ballots stay open through the close and still count as ballots cast.

    PRD: "A segregated ballot begins with `resolution` `OPEN`, `reopen_count` 0 and no `resolved_at`; it raises the session's `challenged_ballot_count` by 1, the round's `challenged_open_count` by 1, and the round's `ballots_cast_total` by 1, because a challenged ballot is a real ballot that entered the box."

    PRD: "At that point the round accumulates the closed sessions' figures: `provisional_votes_for`, `provisional_votes_against` and `provisional_void_count` are summed from the `CLOSED` sessions, and `ballots_cast_total` records every ballot that entered the box across the round."

    Design: Corner/state_machines/closing_the_last_scheduled_session_bubbles_the_round_to_polls_closed
    """
    ctx = _round_with_two_sessions_and_three_challenges()
    cafeteria, breakroom = ctx["sessions"]
    set_clock(SESSION_CLOSING_INSTANT)
    close_poll_session(cafeteria["id"], votes_for_count=30, votes_against_count=25, void_count=1)
    close_poll_session(breakroom["id"], votes_for_count=12, votes_against_count=14, void_count=0)

    election_round = read_round(ctx["round"]["id"])

    assert election_round["status"] == "POLLS_CLOSED"
    assert election_round["challenged_open_count"] == 3
    assert election_round["ballots_cast_total"] == 85
    assert read_poll_session(cafeteria["id"])["challenged_ballot_count"] == 2
    assert read_poll_session(breakroom["id"])["challenged_ballot_count"] == 1


TALLY_POSTING_INSTANT = "2026-09-02T12:00:00Z"


def _tally_posted_round_with_open_challenges():
    """Both sessions closed, the provisional tally posted, three challenges still open."""
    ctx = _round_with_two_sessions_and_three_challenges()
    cafeteria, breakroom = ctx["sessions"]
    set_clock(SESSION_CLOSING_INSTANT)
    ctx["sessions"] = [
        close_poll_session(
            cafeteria["id"], votes_for_count=30, votes_against_count=25, void_count=1
        ),
        close_poll_session(
            breakroom["id"], votes_for_count=12, votes_against_count=14, void_count=0
        ),
    ]
    set_clock(TALLY_POSTING_INSTANT)
    ctx["round"] = post_tally(ctx["round"]["id"])
    ctx["petition"] = read_petition(ctx["petition"]["id"])
    return ctx


def test_closing_an_already_closed_session_is_refused():
    """A second closing of the same session is rejected outright, not absorbed.

    PRD: "A session that is already closed, or one that was cancelled, is refused with `ERR_POLL_SESSION_STATUS_INVALID`."

    Design: Corner/state_machines/repeating_election_arc_actions_is_rejected_not_ignored
    """
    ctx = _round_with_two_sessions_and_three_challenges()
    cafeteria = ctx["sessions"][0]
    set_clock(SESSION_CLOSING_INSTANT)
    close_poll_session(cafeteria["id"], votes_for_count=30, votes_against_count=25, void_count=1)

    resp = api_client.close_poll_session(
        cafeteria["id"],
        close_session_payload(votes_for_count=5, votes_against_count=4, void_count=0),
        BOARD,
    )

    validate_error(resp, ApiErrorId.ERR_POLL_SESSION_STATUS_INVALID)
    session = read_poll_session(cafeteria["id"])
    assert session["status"] == "CLOSED"
    assert session["votes_for_count"] == 30
    assert session["votes_against_count"] == 25
    election_round = read_round(ctx["round"]["id"])
    assert election_round["status"] == "POLLS_OPEN"
    assert election_round["closed_session_count"] == 1
    assert election_round["scheduled_session_count"] == 1


def test_reposting_the_tally_on_a_posted_round_is_refused_and_recomputes_nothing():
    """Posting the provisional tally twice is a state error, and the first figures stand.

    PRD: "Posting the provisional tally is a `BoardAgent` act on a round in `POLLS_CLOSED`."

    PRD: "**Own-state precondition** — the target row is in a state from which the requested transition is declared, else the state code for that resource type: `ERR_PETITION_STATUS_INVALID`, `ERR_CLASSIFICATION_ALREADY_RULED`, `ERR_AGREEMENT_STATUS_INVALID`, `ERR_VOTER_LIST_STATUS_INVALID`, `ERR_COMMUNICATION_STATUS_INVALID`, `ERR_ROUND_NOT_SCHEDULED`, `ERR_ROUND_STATUS_INVALID`, `ERR_POLL_SESSION_STATUS_INVALID`, `ERR_BALLOT_STATUS_INVALID`, `ERR_OBJECTION_ALREADY_RULED` or `ERR_CHARGE_STATUS_INVALID`, each HTTP 409."

    Design: Corner/state_machines/repeating_election_arc_actions_is_rejected_not_ignored
    """
    ctx = _tally_posted_round_with_open_challenges()
    set_clock("2026-09-03T09:00:00Z")

    resp = api_client.post_tally(ctx["round"]["id"], BOARD)

    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_ROUND_STATUS_INVALID, ApiErrorId.ERR_ROUND_NOT_SCHEDULED],
    )
    assert resp.status_code == 409
    election_round = read_round(ctx["round"]["id"])
    assert election_round["status"] == "TALLY_POSTED"
    assert election_round["closed_session_count"] == 2
    assert election_round["ballots_cast_total"] == 85
    assert election_round["provisional_votes_for"] == 42
    assert election_round["provisional_margin"] == 3
    assert_instant_equals(
        election_round["tally_posted_at"], TALLY_POSTING_INSTANT, "round tally_posted_at"
    )


def test_reopening_the_polls_on_a_posted_round_is_refused():
    """The polls cannot be reopened once the round has moved past its balloting states.

    PRD: "Opening the polls advances a round from `SCHEDULED` to `POLLS_OPEN` and is a `BoardAgent` act."

    PRD: "**Own-state precondition** — the target row is in a state from which the requested transition is declared, else the state code for that resource type: `ERR_PETITION_STATUS_INVALID`, `ERR_CLASSIFICATION_ALREADY_RULED`, `ERR_AGREEMENT_STATUS_INVALID`, `ERR_VOTER_LIST_STATUS_INVALID`, `ERR_COMMUNICATION_STATUS_INVALID`, `ERR_ROUND_NOT_SCHEDULED`, `ERR_ROUND_STATUS_INVALID`, `ERR_POLL_SESSION_STATUS_INVALID`, `ERR_BALLOT_STATUS_INVALID`, `ERR_OBJECTION_ALREADY_RULED` or `ERR_CHARGE_STATUS_INVALID`, each HTTP 409."

    Design: Corner/state_machines/repeating_election_arc_actions_is_rejected_not_ignored
    """
    ctx = _tally_posted_round_with_open_challenges()

    resp = api_client.open_polls(ctx["round"]["id"], BOARD)

    validate_error_is_one_of(
        resp,
        [ApiErrorId.ERR_ROUND_STATUS_INVALID, ApiErrorId.ERR_ROUND_NOT_SCHEDULED],
    )
    assert resp.status_code == 409
    election_round = read_round(ctx["round"]["id"])
    assert election_round["status"] == "TALLY_POSTED"
    assert election_round["scheduled_session_count"] == 0
    assert election_round["closed_session_count"] == 2
    assert_instant_equals(
        election_round["tally_posted_at"], TALLY_POSTING_INSTANT, "round tally_posted_at"
    )


def test_a_delivered_message_cannot_be_delivered_a_second_time():
    """Delivery is a one-way door: the second confirmation is refused and the original
    delivery instant is left alone.

    PRD: "Delivery is confirmed by the director and moves an `APPROVED` message to the terminal `DELIVERED` state, stamping `delivered_at` with the logical clock."

    PRD: "**Own-state precondition** — the target row is in a state from which the requested transition is declared, else the state code for that resource type: `ERR_PETITION_STATUS_INVALID`, `ERR_CLASSIFICATION_ALREADY_RULED`, `ERR_AGREEMENT_STATUS_INVALID`, `ERR_VOTER_LIST_STATUS_INVALID`, `ERR_COMMUNICATION_STATUS_INVALID`, `ERR_ROUND_NOT_SCHEDULED`, `ERR_ROUND_STATUS_INVALID`, `ERR_POLL_SESSION_STATUS_INVALID`, `ERR_BALLOT_STATUS_INVALID`, `ERR_OBJECTION_ALREADY_RULED` or `ERR_CHARGE_STATUS_INVALID`, each HTTP 409."

    Design: Corner/state_machines/delivered_message_cannot_be_delivered_twice
    """
    ctx = setup_election_set()
    message = create_approved_message(
        ctx["petition"]["id"],
        message_overrides={"channel": "EMAIL", "audience_scope": "UNIT_WIDE"},
        accuracy_overrides={"material_claim_count": 4, "unsupported_material_claim_count": 0},
    )
    set_clock("2026-08-25T12:00:00Z")
    delivered = validate_success(api_client.deliver_communication(message["id"], DIRECTOR))
    assert delivered["status"] == "DELIVERED"
    assert_instant_equals(
        delivered["delivered_at"], "2026-08-25T12:00:00Z", "message delivered_at"
    )
    set_clock("2026-08-26T09:00:00Z")

    resp = api_client.deliver_communication(message["id"], DIRECTOR)

    validate_error(resp, ApiErrorId.ERR_COMMUNICATION_STATUS_INVALID)
    stored = read_campaign_message(message["id"])
    assert stored["status"] == "DELIVERED"
    assert_instant_equals(
        stored["delivered_at"], "2026-08-25T12:00:00Z", "message delivered_at after replay"
    )


CERTIFICATION_INSTANT = "2026-09-15T09:00:00Z"


def test_a_certified_case_cannot_be_pushed_back_into_scope_analysis():
    """Opening scope analysis on a certified case is refused on its status.

    PRD: "This is only possible from `RECEIVED` and only while `case_posture` is `OPEN`; from any other status the request is refused with `ERR_PETITION_STATUS_INVALID`."

    Design: Corner/state_machines/certified_petition_rejects_every_further_case_transition
    """
    ctx = setup_certified_case(certify_clock=CERTIFICATION_INSTANT)

    resp = api_client.open_scope_analysis(ctx["petition"]["id"], DIRECTOR)

    validate_error(resp, ApiErrorId.ERR_PETITION_STATUS_INVALID)
    petition = read_petition(ctx["petition"]["id"])
    assert petition["case_status"] == "CERTIFIED"


def test_a_certified_case_refuses_a_second_certification():
    """Certification is terminal, so certifying again is refused and the recorded
    certification stands untouched.

    PRD: "The certification itself stamps `certified_at` with the logical clock, records the named round in `certified_round_id`, moves the case to the terminal `CERTIFIED` status, and moves that round to the terminal `ROUND_CERTIFIED` status."

    Design: Corner/state_machines/certified_petition_rejects_every_further_case_transition
    """
    ctx = setup_certified_case(certify_clock=CERTIFICATION_INSTANT)
    round_id = ctx["round"]["id"]
    set_clock("2026-09-16T09:00:00Z")

    resp = api_client.certify_petition(
        ctx["petition"]["id"], {"election_round_id": round_id}, BOARD
    )

    validate_error(resp, ApiErrorId.ERR_PETITION_STATUS_INVALID)
    petition = read_petition(ctx["petition"]["id"])
    assert petition["case_status"] == "CERTIFIED"
    assert petition["certified_round_id"] == round_id
    assert_instant_equals(
        petition["certified_at"], CERTIFICATION_INSTANT, "petition certified_at"
    )
    assert read_round(round_id)["status"] == "ROUND_CERTIFIED"


def test_a_certified_case_refuses_a_fresh_showing_verification():
    """Re-verifying the showing of interest is unavailable once the case is certified, and
    the recorded percentage is not overwritten.

    PRD: "On a `SUFFICIENT` verdict the case advances from `SCOPE_ANALYSIS` to `SOI_VERIFIED`, writing `valid_card_count`, `showing_of_interest_pct`, `showing_headcount_basis` and `showing_verdict`."

    PRD: "**Own-state precondition** — the target row is in a state from which the requested transition is declared, else the state code for that resource type: `ERR_PETITION_STATUS_INVALID`, `ERR_CLASSIFICATION_ALREADY_RULED`, `ERR_AGREEMENT_STATUS_INVALID`, `ERR_VOTER_LIST_STATUS_INVALID`, `ERR_COMMUNICATION_STATUS_INVALID`, `ERR_ROUND_NOT_SCHEDULED`, `ERR_ROUND_STATUS_INVALID`, `ERR_POLL_SESSION_STATUS_INVALID`, `ERR_BALLOT_STATUS_INVALID`, `ERR_OBJECTION_ALREADY_RULED` or `ERR_CHARGE_STATUS_INVALID`, each HTTP 409."

    Design: Corner/state_machines/certified_petition_rejects_every_further_case_transition
    """
    ctx = setup_certified_case(certify_clock=CERTIFICATION_INSTANT)
    certified = read_petition(ctx["petition"]["id"])
    recorded_pct = certified["showing_of_interest_pct"]
    recorded_cards = certified["valid_card_count"]

    resp = api_client.verify_showing(
        ctx["petition"]["id"], verify_showing_payload(submitted_card_count=50), BOARD
    )

    validate_error(resp, ApiErrorId.ERR_PETITION_STATUS_INVALID)
    petition = read_petition(ctx["petition"]["id"])
    assert petition["case_status"] == "CERTIFIED"
    assert petition["showing_of_interest_pct"] == recorded_pct
    assert petition["valid_card_count"] == recorded_cards


def test_the_certified_round_refuses_a_further_tally_revision():
    """A round carried to its terminal certified state can no longer be revised.

    PRD: "A round in any other status is refused with `ERR_ROUND_STATUS_INVALID`."

    PRD: "The certification itself stamps `certified_at` with the logical clock, records the named round in `certified_round_id`, moves the case to the terminal `CERTIFIED` status, and moves that round to the terminal `ROUND_CERTIFIED` status."

    Design: Corner/state_machines/certified_petition_rejects_every_further_case_transition
    """
    ctx = setup_certified_case(certify_clock=CERTIFICATION_INSTANT)
    round_id = ctx["round"]["id"]
    revised_for = ctx["round"]["revised_votes_for"]

    resp = api_client.revise_tally(round_id, BOARD)

    validate_error(resp, ApiErrorId.ERR_ROUND_STATUS_INVALID)
    election_round = read_round(round_id)
    assert election_round["status"] == "ROUND_CERTIFIED"
    assert election_round["revised_votes_for"] == revised_for


OBJECTION_RULING_INSTANT = "2026-09-10T10:00:00Z"
OVERRULE_RATIONALE = "The incident was isolated and could not have changed the outcome."


def test_filing_an_objection_moves_the_case_into_its_objection_phase():
    """A single non-determinative objection still pushes the case out of TALLY_POSTED.

    PRD: "Filing raises the case's `pending_objection_count` by 1, and the first objection accepted against the current round moves `case_status` from `TALLY_POSTED` to `OBJECTIONS_PENDING`."

    PRD: "A new objection starts at `status` `FILED` with `rerun_directed` false and no `ruled_at` or `disposition_rationale`, and the system immediately computes `affects_results`: it is true exactly when `alleged_affected_voter_count` is greater than or equal to the absolute value of the objected round's `provisional_margin`."

    Design: Corner/state_machines/overruling_the_last_objection_bubbles_the_case_back_to_tally_posted
    """
    ctx = setup_tally_posted()

    resp = api_client.create_objection(
        create_objection_payload(
            ctx["round"]["id"], filed_by_party="UNION", alleged_affected_voter_count=1
        ),
        UNION,
    )

    objection = validate_success(resp, 201)
    assert objection["status"] == "FILED"
    assert objection["affects_results"] is False
    assert objection["rerun_directed"] is False
    assert_absent(objection, "ruled_at", "new objection")
    petition = read_petition(ctx["petition"]["id"])
    assert petition["case_status"] == "OBJECTIONS_PENDING"
    assert petition["pending_objection_count"] == 1


def test_overruling_the_last_objection_returns_the_case_to_tally_posted():
    """Clearing the only pending objection lets the case fall back to its posted tally,
    leaving the round and its objection window as they were.

    PRD: "Overruling is the quiet path: it stamps `ruled_at` and the rationale, moves the objection to the terminal `OVERRULED` state, and lowers the case's `pending_objection_count` by 1."

    PRD: "When that count reaches 0 with no objection on the round having been sustained, the case returns from `OBJECTIONS_PENDING` to `TALLY_POSTED`, so certification may proceed."

    Design: Corner/state_machines/overruling_the_last_objection_bubbles_the_case_back_to_tally_posted
    """
    ctx = setup_tally_posted()
    objection = file_objection(
        ctx["round"]["id"], UNION, filed_by_party="UNION", alleged_affected_voter_count=1
    )
    window_before = read_round(ctx["round"]["id"])["objection_window_close_at"]
    set_clock(OBJECTION_RULING_INSTANT)

    resp = api_client.rule_objection(
        objection["id"],
        rule_objection_payload(
            disposition="OVERRULE", disposition_rationale=OVERRULE_RATIONALE
        ),
        BOARD,
    )

    ruled = validate_success(resp)
    assert ruled["status"] == "OVERRULED"
    assert ruled["rerun_directed"] is False
    assert ruled["disposition_rationale"] == OVERRULE_RATIONALE
    assert_instant_equals(ruled["ruled_at"], OBJECTION_RULING_INSTANT, "objection ruled_at")
    petition = read_petition(ctx["petition"]["id"])
    assert petition["case_status"] == "TALLY_POSTED"
    assert petition["pending_objection_count"] == 0
    election_round = read_round(ctx["round"]["id"])
    assert election_round["status"] == "TALLY_POSTED"
    assert_instants_equal(
        election_round["objection_window_close_at"], window_before, "objection window close"
    )


def test_an_objection_cannot_be_ruled_twice():
    """Once ruled, an objection is closed: a second ruling is refused and the first
    disposition stands.

    PRD: "An objection that has already been ruled is refused with `ERR_OBJECTION_ALREADY_RULED`."

    Design: Corner/state_machines/objection_cannot_be_ruled_twice
    """
    ctx = setup_tally_posted()
    objection = file_objection(
        ctx["round"]["id"], UNION, filed_by_party="UNION", alleged_affected_voter_count=1
    )
    set_clock(OBJECTION_RULING_INSTANT)
    rule_objection(
        objection["id"], disposition="OVERRULE", disposition_rationale=OVERRULE_RATIONALE
    )

    resp = api_client.rule_objection(
        objection["id"],
        rule_objection_payload(
            disposition="OVERRULE",
            disposition_rationale="Reconsidered on the same record after further review.",
        ),
        BOARD,
    )

    validate_error(resp, ApiErrorId.ERR_OBJECTION_ALREADY_RULED)
    stored = validate_success(api_client.get_objection(objection["id"], BOARD))
    assert stored["status"] == "OVERRULED"
    assert stored["disposition_rationale"] == OVERRULE_RATIONALE
    assert stored["rerun_directed"] is False
    assert_instant_equals(stored["ruled_at"], OBJECTION_RULING_INSTANT, "objection ruled_at")
    assert read_round(ctx["round"]["id"])["status"] == "TALLY_POSTED"
    assert read_petition(ctx["petition"]["id"])["case_status"] == "TALLY_POSTED"
