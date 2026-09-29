"""Cross-entity preconditions, physical-resource overlap and conserved totals.

The behaviour under test here is the part of a representation case where one row
may only move because another row is already in the right state: the polls open
only against an accepted eligible-voter list, a meeting message enters legal
review only behind a certified presenter, and a tally is revised only once every
challenged ballot has left the open pool. The same file covers the two
occupancy rules that keep a polling location and a presenter's calendar from
being double-booked, and the two conserved quantities — classified headcount on
the case and physical ballots in the box — that must survive a ruling, a
reconsideration, a resolution and a reopen.
"""
from test_helpers import (
    BOARD,
    DIRECTOR,
    ApiErrorId,
    accuracy_review,
    api_client,
    assert_absent,
    assert_ballot_conservation,
    assert_headcount_conservation,
    assert_instant_equals,
    close_poll_session,
    create_campaign_communication_payload,
    create_campaign_message,
    create_petition_in_scope_analysis,
    create_poll_session,
    create_poll_session_payload,
    create_trained_supervisor,
    get_success_data,
    post_tally,
    read_campaign_message,
    read_petition,
    read_round,
    read_voter_list,
    reconsider_classification,
    register_supervisor,
    reopen_ballot,
    resolve_ballot,
    review_voter_list,
    round_version,
    rule_classification,
    score_classification,
    segregate_ballot,
    set_clock,
    setup_election_set,
    setup_polls_open,
    setup_scope_analysis,
    setup_submitted_voter_list,
    train_supervisor,
    validate_error,
    validate_success,
)

MEETING_SUMMARY = "Day shift briefing on the election process"

FOUR_CLASSIFICATION_SPECS = [
    {
        "code": "PROD", "title": "Production Operator", "headcount": 60,
        "avg_hourly_wage_cents": 2400, "employer_position": "INCLUDE",
        "union_position": "INCLUDE", "supervision_overlap": 88, "skills_overlap": 90,
        "functional_integration": 92, "interchange_rate": 74, "work_conditions_overlap": 95,
    },
    {
        "code": "MAINT", "title": "Maintenance Mechanic", "headcount": 30,
        "avg_hourly_wage_cents": 3200, "employer_position": "INCLUDE",
        "union_position": "INCLUDE", "supervision_overlap": 82, "skills_overlap": 78,
        "functional_integration": 86, "interchange_rate": 61, "work_conditions_overlap": 84,
    },
    {
        "code": "QC", "title": "Quality Inspector", "headcount": 12,
        "avg_hourly_wage_cents": 2900, "shift_code": "B", "work_location": "PLANT_1_LAB",
        "employer_position": "EXCLUDE", "union_position": "INCLUDE",
        "supervision_overlap": 41, "skills_overlap": 55, "functional_integration": 61,
        "interchange_rate": 21, "work_conditions_overlap": 71,
    },
    {
        "code": "LEAD", "title": "Lead Operator", "headcount": 8,
        "avg_hourly_wage_cents": 2800, "supervisory_authority_count": 4,
        "employer_position": "EXCLUDE", "union_position": "INCLUDE",
        "supervision_overlap": 78, "skills_overlap": 82, "functional_integration": 80,
        "interchange_rate": 66, "work_conditions_overlap": 88,
    },
]


def _scored_roster_of_110_heads():
    """A case in scope analysis with four scored classifications totalling 110 heads."""
    ctx = setup_scope_analysis(classification_specs=FOUR_CLASSIFICATION_SPECS)
    for classification in ctx["classifications"]:
        score_classification(classification["id"])
    by_code = {row["code"]: row for row in ctx["classifications"]}
    ctx["by_code"] = by_code
    ctx["petition"] = read_petition(ctx["petition"]["id"])
    return ctx


def _read_classification(classification_id):
    return get_success_data(api_client.get_classification(classification_id, BOARD))


def _buckets(petition):
    return (
        petition["included_headcount"],
        petition["excluded_headcount"],
        petition["pending_headcount"],
    )


def _tally_posted_with_three_open_challenges():
    """A closed election whose provisional tally is posted with three ballots open.

    One session closes at 42 for, 39 against and 1 void with three challenged
    ballots already segregated, so 85 physical ballots entered the box.
    """
    ctx = setup_polls_open(entry_count=3)
    session = ctx["sessions"][0]
    challenges = [
        {"challenger_party": "EMPLOYER", "basis": "SUPERVISOR"},
        {"challenger_party": "UNION", "basis": "NOT_ON_LIST"},
        {"challenger_party": "EMPLOYER", "basis": "OUTSIDE_UNIT"},
    ]
    ballots = []
    for entry, challenge in zip(ctx["entries"], challenges):
        ballots.append(
            segregate_ballot(session["id"], voter_list_entry_id=entry["id"], **challenge)
        )
    set_clock(session["session_end_at"])
    close_poll_session(
        session["id"], votes_for_count=42, votes_against_count=39, void_count=1
    )
    set_clock("2026-09-02T12:00:00Z")
    ctx["round"] = post_tally(ctx["round"]["id"])
    ctx["ballots"] = ballots
    return ctx


# --------------------------------------------------------------------------
# Opening the polls behind the eligible-voter list
# --------------------------------------------------------------------------
def test_polls_cannot_open_while_a_perfectly_graded_list_is_only_submitted():
    """A filed list that the Board has not yet accepted still keeps the polls shut,
    even when it graded COMPLIANT and was filed on time.

    PRD: "Four conditions must hold beyond the posture gate: the case must hold a
    voter list in `ACCEPTED` status, and if it does not the request is refused with
    `ERR_VOTER_LIST_NOT_ACCEPTED`; the round's `scheduled_session_count` must be at
    least 1; and the logical clock must have reached the round's `polls_open_at`,
    since opening early is refused with `ERR_POLLS_NOT_YET_OPEN`."
    PRD: "The base tier follows from the rounded percentage: exactly 100.00 is
    `COMPLIANT`, at least 90.00 is `MINOR_DEFECT`, at least 75.00 is
    `MATERIAL_DEFECT`, and anything below 75.00 is `GROSSLY_DEFICIENT`."

    Design: Difficulty/cross_entity_state_dependency/open_polls_requires_accepted_voter_list
    """
    ctx = setup_submitted_voter_list(entry_count=3)
    create_poll_session(ctx["round"]["id"])

    filed_list = read_voter_list(ctx["voter_list"]["id"])
    assert filed_list["status"] == "SUBMITTED", (
        f"the list must be awaiting Board review, got {filed_list['status']}"
    )
    assert filed_list["completeness_pct"] == 100.00, (
        f"three complete entries score 100.00, got {filed_list['completeness_pct']}"
    )
    assert filed_list["list_grade"] == "COMPLIANT", (
        f"100.00 percent complete grades COMPLIANT, got {filed_list['list_grade']}"
    )
    assert filed_list["is_late"] is False, "the list was filed before its due instant"

    set_clock(ctx["round"]["polls_open_at"])
    response = api_client.open_polls(ctx["round"]["id"], BOARD)
    validate_error(response, ApiErrorId.ERR_VOTER_LIST_NOT_ACCEPTED)

    unchanged = read_round(ctx["round"]["id"])
    assert unchanged["status"] == "SCHEDULED", (
        f"a refused opening writes nothing, got round status {unchanged['status']}"
    )


def test_polls_open_on_the_identical_request_once_the_board_accepts_the_list():
    """Accepting the filed list is the only thing that changes, and the same
    open-polls request then advances the round to POLLS_OPEN.

    PRD: "`ACCEPT` moves the list to `ACCEPTED` and is only available when
    `list_grade` is `COMPLIANT` or `MINOR_DEFECT`; it stamps `reviewed_at` and
    leaves both `cure_window_hours` and `cure_deadline_at` absent."
    PRD: "Four conditions must hold beyond the posture gate: the case must hold a
    voter list in `ACCEPTED` status, and if it does not the request is refused with
    `ERR_VOTER_LIST_NOT_ACCEPTED`; the round's `scheduled_session_count` must be at
    least 1; and the logical clock must have reached the round's `polls_open_at`,
    since opening early is refused with `ERR_POLLS_NOT_YET_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/open_polls_requires_accepted_voter_list
    """
    ctx = setup_submitted_voter_list(entry_count=3)
    create_poll_session(ctx["round"]["id"])
    set_clock(ctx["round"]["polls_open_at"])

    blocked = api_client.open_polls(ctx["round"]["id"], BOARD)
    validate_error(blocked, ApiErrorId.ERR_VOTER_LIST_NOT_ACCEPTED)

    accepted = review_voter_list(ctx["voter_list"]["id"], "ACCEPT")
    assert accepted["status"] == "ACCEPTED", (
        f"the Board accepted a COMPLIANT list, got {accepted['status']}"
    )

    opened = validate_success(api_client.open_polls(ctx["round"]["id"], BOARD))
    assert opened["status"] == "POLLS_OPEN", (
        f"the identical request must now open the polls, got {opened['status']}"
    )
    assert opened["scheduled_session_count"] == 1, (
        "opening the polls changes no session counter, expected 1 scheduled session, "
        f"got {opened['scheduled_session_count']}"
    )


# --------------------------------------------------------------------------
# Meeting messages behind a certified presenter
# --------------------------------------------------------------------------
def _case_with_an_untrained_presenter():
    """A scope-analysis case whose named presenter failed a training attempt."""
    set_clock("2026-08-12T09:00:00Z")
    petition = create_petition_in_scope_analysis()
    supervisor = register_supervisor(petition["id"])
    supervisor = train_supervisor(supervisor["id"], quiz_score=74)
    return {"petition": petition, "supervisor": supervisor}


def _meeting_draft(petition_id, supervisor_id, **overrides):
    """A small-group meeting draft that has passed its factual-accuracy review."""
    payload = {
        "channel": "SMALL_GROUP_MEETING",
        "audience_scope": "CLASSIFICATION",
        "presenter_supervisor_id": supervisor_id,
        "planned_delivery_at": "2026-08-25T10:00:00Z",
        "duration_minutes": 60,
        "message_summary": MEETING_SUMMARY,
    }
    payload.update(overrides)
    message = create_campaign_message(petition_id, **payload)
    accuracy_review(message["id"], material_claim_count=3, unsupported_material_claim_count=1)
    return message


def test_meeting_message_cannot_enter_legal_review_behind_a_failed_training_attempt():
    """A recorded but non-qualifying attempt leaves the presenter UNTRAINED, and the
    meeting message it presents cannot be sent into legal review.

    PRD: "An attempt that falls short — either because a required module is missing
    or because the score is below 80 — is recorded rather than rejected: it is a
    self-loop that leaves `training_status` at `UNTRAINED`, increments
    `training_attempt_count`, records the `quiz_score`, and withholds certification."
    PRD: "If the `channel` is `SMALL_GROUP_MEETING` or `CAPTIVE_AUDIENCE_MEETING`,
    the presenting supervisor's `training_status` must be `TRAINED`, and an untrained
    presenter is refused with `ERR_PRESENTER_NOT_TRAINED`."

    Design: Difficulty/cross_entity_state_dependency/meeting_submission_requires_trained_presenter
    """
    ctx = _case_with_an_untrained_presenter()
    supervisor = ctx["supervisor"]
    assert supervisor["training_status"] == "UNTRAINED", (
        f"a score of 74 withholds certification, got {supervisor['training_status']}"
    )
    assert supervisor["training_attempt_count"] == 1, (
        f"the failed attempt is still recorded, got {supervisor['training_attempt_count']}"
    )
    assert supervisor["quiz_score"] == 74, (
        f"the attempt's score is kept, got {supervisor['quiz_score']}"
    )
    assert_absent(supervisor, "certified_at", "supervisor")

    message = _meeting_draft(ctx["petition"]["id"], supervisor["id"])
    response = api_client.submit_communication_for_review(message["id"], DIRECTOR)
    validate_error(response, ApiErrorId.ERR_PRESENTER_NOT_TRAINED)

    unchanged = read_campaign_message(message["id"])
    assert unchanged["status"] == "DRAFT", (
        f"a refused submission leaves the draft where it was, got {unchanged['status']}"
    )


def test_an_email_message_on_the_same_case_enters_legal_review_with_no_presenter_at_all():
    """The training gate rides on the meeting channels, so an email draft on the very
    same case moves into legal review while the meeting draft cannot.

    PRD: "A `presenter_supervisor_id` names the presenting supervisor: it is required
    for the two meeting channels and absent otherwise."
    PRD: "If the `channel` is `SMALL_GROUP_MEETING` or `CAPTIVE_AUDIENCE_MEETING`,
    the presenting supervisor's `training_status` must be `TRAINED`, and an untrained
    presenter is refused with `ERR_PRESENTER_NOT_TRAINED`."

    Design: Difficulty/cross_entity_state_dependency/meeting_submission_requires_trained_presenter
    """
    ctx = _case_with_an_untrained_presenter()
    blocked_meeting = _meeting_draft(ctx["petition"]["id"], ctx["supervisor"]["id"])
    validate_error(
        api_client.submit_communication_for_review(blocked_meeting["id"], DIRECTOR),
        ApiErrorId.ERR_PRESENTER_NOT_TRAINED,
    )

    email = create_campaign_message(
        ctx["petition"]["id"], channel="EMAIL", audience_scope="UNIT_WIDE",
        planned_delivery_at="2026-08-25T10:00:00Z",
    )
    assert_absent(email, "presenter_supervisor_id", "communication")
    accuracy_review(email["id"], material_claim_count=3, unsupported_material_claim_count=1)

    submitted = validate_success(
        api_client.submit_communication_for_review(email["id"], DIRECTOR)
    )
    assert submitted["status"] == "PENDING_LEGAL_REVIEW", (
        f"an email draft needs no certified presenter, got {submitted['status']}"
    )


def test_meeting_message_enters_legal_review_once_a_qualifying_attempt_certifies_the_presenter():
    """A second attempt scoring exactly 80 with all three modules certifies the
    presenter, and the same meeting message then passes the gate.

    PRD: "Certification is granted only when the attempt is complete on both counts:
    `modules_completed` must contain every one of the three required module codes —
    `TIPS_BOUNDARIES`, `PROHIBITED_CONDUCT` and `SOLICITATION_RULES` — and
    `quiz_score` must be at least 80."
    PRD: "A qualifying attempt increments `training_attempt_count`, records the score
    and the modules, stamps `certified_at` with the logical clock, and moves
    `training_status` from `UNTRAINED` to `TRAINED`."

    Design: Difficulty/cross_entity_state_dependency/meeting_submission_requires_trained_presenter
    """
    ctx = _case_with_an_untrained_presenter()
    message = _meeting_draft(ctx["petition"]["id"], ctx["supervisor"]["id"])
    validate_error(
        api_client.submit_communication_for_review(message["id"], DIRECTOR),
        ApiErrorId.ERR_PRESENTER_NOT_TRAINED,
    )

    certified = train_supervisor(ctx["supervisor"]["id"], quiz_score=80)
    assert certified["training_status"] == "TRAINED", (
        f"a score of exactly 80 certifies, got {certified['training_status']}"
    )
    assert certified["training_attempt_count"] == 2, (
        f"the second attempt increments the counter, got {certified['training_attempt_count']}"
    )
    assert_instant_equals(
        certified["certified_at"], "2026-08-12T09:00:00Z", "supervisor.certified_at"
    )

    submitted = validate_success(
        api_client.submit_communication_for_review(message["id"], DIRECTOR)
    )
    assert submitted["status"] == "PENDING_LEGAL_REVIEW", (
        f"the meeting draft clears the gate behind a TRAINED presenter, "
        f"got {submitted['status']}"
    )


# --------------------------------------------------------------------------
# Revising the tally behind an empty open-challenge pool
# --------------------------------------------------------------------------
def test_tally_cannot_be_revised_while_challenged_ballots_are_still_open():
    """Three segregated ballots still sitting open keep the revision out, and the
    round holds its provisional figures.

    PRD: "Revising the tally folds the resolved challenges in, and it may only run
    when `challenged_open_count` has reached 0; while any ballot is still open the
    request is refused with `ERR_CHALLENGES_UNRESOLVED`."
    PRD: "`determinative_challenges` is **not** recomputed — it is a historical
    finding about the provisional margin and keeps its provisional value."

    Design: Difficulty/cross_entity_state_dependency/revise_tally_requires_all_challenges_resolved
    """
    ctx = _tally_posted_with_three_open_challenges()
    posted = ctx["round"]
    assert posted["status"] == "TALLY_POSTED", (
        f"the provisional tally is posted, got {posted['status']}"
    )
    assert posted["challenged_open_count"] == 3, (
        f"all three challenges are open, got {posted['challenged_open_count']}"
    )
    assert posted["provisional_margin"] == 3, (
        f"42 for less 39 against is a margin of 3, got {posted['provisional_margin']}"
    )
    assert posted["determinative_challenges"] is True, (
        "three open challenges against a margin of 3 are determinative, "
        f"got {posted['determinative_challenges']}"
    )

    response = api_client.revise_tally(ctx["round"]["id"], BOARD)
    validate_error(response, ApiErrorId.ERR_CHALLENGES_UNRESOLVED)

    unchanged = read_round(ctx["round"]["id"])
    assert unchanged["status"] == "TALLY_POSTED", (
        f"a refused revision leaves the round posted, got {unchanged['status']}"
    )
    assert unchanged["valid_votes_cast"] == 81, (
        f"the provisional base of 81 valid votes stands, got {unchanged['valid_votes_cast']}"
    )
    assert unchanged["majority_threshold"] == 41, (
        f"81 valid votes give a threshold of 41, got {unchanged['majority_threshold']}"
    )
    assert_absent(unchanged, "tally_revised_at", "round")
    assert_ballot_conservation(unchanged)


def test_one_ballot_left_open_out_of_three_still_blocks_the_revision():
    """The gate is on the open count reaching zero, not on most challenges being
    dispositioned: two resolutions out of three change nothing about the refusal.

    PRD: "Every resolution stamps `resolved_at`, lowers the round's
    `challenged_open_count` by 1, and raises exactly one of
    `challenged_counted_for_count`, `challenged_counted_against_count`,
    `challenged_voided_count` or `challenged_withdrawn_count` by 1."
    PRD: "Revising the tally folds the resolved challenges in, and it may only run
    when `challenged_open_count` has reached 0; while any ballot is still open the
    request is refused with `ERR_CHALLENGES_UNRESOLVED`."

    Design: Difficulty/cross_entity_state_dependency/revise_tally_requires_all_challenges_resolved
    """
    ctx = _tally_posted_with_three_open_challenges()
    resolve_ballot(ctx["ballots"][0]["id"], resolution="COUNTED_FOR")
    resolve_ballot(ctx["ballots"][1]["id"], resolution="COUNTED_AGAINST")

    partially_resolved = read_round(ctx["round"]["id"])
    assert partially_resolved["challenged_open_count"] == 1, (
        f"one challenge is still open, got {partially_resolved['challenged_open_count']}"
    )
    assert partially_resolved["challenged_counted_for_count"] == 1, (
        f"one ballot went into the for column, "
        f"got {partially_resolved['challenged_counted_for_count']}"
    )
    assert partially_resolved["challenged_counted_against_count"] == 1, (
        f"one ballot went into the against column, "
        f"got {partially_resolved['challenged_counted_against_count']}"
    )

    validate_error(
        api_client.revise_tally(ctx["round"]["id"], BOARD),
        ApiErrorId.ERR_CHALLENGES_UNRESOLVED,
    )
    still_posted = read_round(ctx["round"]["id"])
    assert still_posted["status"] == "TALLY_POSTED", (
        f"the last open ballot holds the round at TALLY_POSTED, got {still_posted['status']}"
    )
    assert_ballot_conservation(still_posted)


def test_revision_folds_the_resolved_challenges_in_once_the_open_pool_empties():
    """With the third ballot voided the open pool empties, and the revision recomputes
    the vote columns, the margin and the threshold on the wider base.

    PRD: "`revised_votes_for` is `provisional_votes_for` plus
    `challenged_counted_for_count`; `revised_votes_against` is
    `provisional_votes_against` plus `challenged_counted_against_count`;
    `revised_void_count` is `provisional_void_count` plus `challenged_voided_count`."
    PRD: "`revised_margin` is the revised votes for less the revised votes against,
    `valid_votes_cast` is recomputed as the revised votes for plus the revised votes
    against, and `majority_threshold` is recomputed from that new base by the same
    halve-discard-add-one rule."

    Design: Difficulty/cross_entity_state_dependency/revise_tally_requires_all_challenges_resolved
    """
    ctx = _tally_posted_with_three_open_challenges()
    validate_error(
        api_client.revise_tally(ctx["round"]["id"], BOARD),
        ApiErrorId.ERR_CHALLENGES_UNRESOLVED,
    )

    resolve_ballot(ctx["ballots"][0]["id"], resolution="COUNTED_FOR")
    resolve_ballot(ctx["ballots"][1]["id"], resolution="COUNTED_FOR")
    resolve_ballot(ctx["ballots"][2]["id"], resolution="VOIDED")

    emptied = read_round(ctx["round"]["id"])
    assert emptied["challenged_open_count"] == 0, (
        f"every challenge has been dispositioned, got {emptied['challenged_open_count']}"
    )

    revised = validate_success(api_client.revise_tally(ctx["round"]["id"], BOARD))
    assert revised["status"] == "TALLY_REVISED", (
        f"the revision now runs, got {revised['status']}"
    )
    assert revised["revised_votes_for"] == 44, (
        f"42 provisional plus 2 counted-for is 44, got {revised['revised_votes_for']}"
    )
    assert revised["revised_votes_against"] == 39, (
        f"39 provisional plus no counted-against is 39, got {revised['revised_votes_against']}"
    )
    assert revised["revised_void_count"] == 2, (
        f"1 provisional void plus 1 voided challenge is 2, got {revised['revised_void_count']}"
    )
    assert revised["revised_margin"] == 5, (
        f"44 less 39 is a margin of 5, got {revised['revised_margin']}"
    )
    assert revised["valid_votes_cast"] == 83, (
        f"44 plus 39 is a base of 83 valid votes, got {revised['valid_votes_cast']}"
    )
    assert revised["majority_threshold"] == 42, (
        f"83 halved and floored plus one is 42, got {revised['majority_threshold']}"
    )
    assert revised["determinative_challenges"] is True, (
        "the historical determinative finding survives the revision, "
        f"got {revised['determinative_challenges']}"
    )
    assert revised["ballots_cast_total"] == 85, (
        f"the physical ballot count never moves, got {revised['ballots_cast_total']}"
    )
    assert_ballot_conservation(revised)


# --------------------------------------------------------------------------
# Polling locations as a physical resource
# --------------------------------------------------------------------------
CAFETERIA = "PLANT_1_CAFETERIA"
ANNEX = "PLANT_1_ANNEX"


def _round_with_a_morning_session_in_the_cafeteria():
    """A scheduled round holding one cafeteria session running 08:00 to 11:00."""
    ctx = setup_election_set()
    ctx["first_session"] = create_poll_session(
        ctx["round"]["id"], location_code=CAFETERIA,
        session_start_at="2026-09-01T08:00:00Z", session_end_at="2026-09-01T11:00:00Z",
    )
    ctx["round"] = read_round(ctx["round"]["id"])
    return ctx


def _attempt_session(round_id, **overrides):
    return api_client.create_poll_session(
        create_poll_session_payload(round_id, round_version(round_id), **overrides), BOARD
    )


def test_a_session_starting_one_second_inside_the_teardown_window_collides():
    """The 30-minute teardown window belongs to the earlier session, so a second
    cafeteria session starting at 11:29:59 is a location collision.

    PRD: "Occupancy of a location extends 30 minutes past a session's close to allow
    for teardown, so two sessions at the same `location_code` on the same round may
    not overlap on the interval running from `session_start_at` up to but not
    including `session_end_at` plus 30 minutes."
    PRD: "A successful layout raises the round's `scheduled_session_count` by 1."

    Design: Difficulty/resource_temporal_overlap/poll_session_location_half_open_teardown
    """
    ctx = _round_with_a_morning_session_in_the_cafeteria()
    assert ctx["round"]["scheduled_session_count"] == 1, (
        f"one session is laid out, got {ctx['round']['scheduled_session_count']}"
    )

    response = _attempt_session(
        ctx["round"]["id"], location_code=CAFETERIA,
        session_start_at="2026-09-01T11:29:59Z", session_end_at="2026-09-01T13:00:00Z",
    )
    validate_error(response, ApiErrorId.ERR_POLL_SESSION_LOCATION_CONFLICT)

    unchanged = read_round(ctx["round"]["id"])
    assert unchanged["scheduled_session_count"] == 1, (
        "a refused layout adds no session, expected 1, "
        f"got {unchanged['scheduled_session_count']}"
    )


def test_a_session_starting_exactly_thirty_minutes_after_the_close_is_admitted():
    """The upper edge of the occupancy interval is open, so 11:30:00 exactly is free
    even though 11:29:59 is not.

    PRD: "That upper edge is open, which means a session may begin **exactly** 30
    minutes after the previous one ends but not one second earlier; a collision is
    reported as `ERR_POLL_SESSION_LOCATION_CONFLICT`."
    PRD: "A successful layout raises the round's `scheduled_session_count` by 1."

    Design: Difficulty/resource_temporal_overlap/poll_session_location_half_open_teardown
    """
    ctx = _round_with_a_morning_session_in_the_cafeteria()
    validate_error(
        _attempt_session(
            ctx["round"]["id"], location_code=CAFETERIA,
            session_start_at="2026-09-01T11:29:59Z", session_end_at="2026-09-01T13:00:00Z",
        ),
        ApiErrorId.ERR_POLL_SESSION_LOCATION_CONFLICT,
    )

    admitted = validate_success(
        _attempt_session(
            ctx["round"]["id"], location_code=CAFETERIA,
            session_start_at="2026-09-01T11:30:00Z", session_end_at="2026-09-01T13:00:00Z",
        ),
        expected_status=201,
    )
    assert admitted["location_code"] == CAFETERIA, (
        f"the afternoon session sits in the cafeteria, got {admitted['location_code']}"
    )
    assert_instant_equals(
        admitted["session_start_at"], "2026-09-01T11:30:00Z", "poll_session.session_start_at"
    )
    assert admitted["status"] == "SCHEDULED", (
        f"a new session starts SCHEDULED, got {admitted['status']}"
    )

    after = read_round(ctx["round"]["id"])
    assert after["scheduled_session_count"] == 2, (
        f"both sessions are now laid out, got {after['scheduled_session_count']}"
    )


def test_the_same_hours_at_a_second_location_do_not_collide():
    """Occupancy is per location, so an identical 08:00 to 11:00 window in the annex
    is admitted alongside the cafeteria session.

    PRD: "Occupancy of a location extends 30 minutes past a session's close to allow
    for teardown, so two sessions at the same `location_code` on the same round may
    not overlap on the interval running from `session_start_at` up to but not
    including `session_end_at` plus 30 minutes."
    PRD: "A session may only be laid out against a round that is `SCHEDULED`; a round
    that a blocking charge has suspended, or one whose polls have already opened, is
    refused with `ERR_ROUND_NOT_SCHEDULED`."

    Design: Difficulty/resource_temporal_overlap/poll_session_location_half_open_teardown
    """
    ctx = _round_with_a_morning_session_in_the_cafeteria()
    assert ctx["round"]["status"] == "SCHEDULED", (
        f"the round is still open for layout, got {ctx['round']['status']}"
    )

    admitted = validate_success(
        _attempt_session(
            ctx["round"]["id"], location_code=ANNEX,
            session_start_at="2026-09-01T08:00:00Z", session_end_at="2026-09-01T11:00:00Z",
        ),
        expected_status=201,
    )
    assert admitted["location_code"] == ANNEX, (
        f"the parallel session sits in the annex, got {admitted['location_code']}"
    )
    assert_instant_equals(
        admitted["session_start_at"], "2026-09-01T08:00:00Z", "poll_session.session_start_at"
    )

    after = read_round(ctx["round"]["id"])
    assert after["scheduled_session_count"] == 2, (
        "two locations may run the same hours, expected 2 scheduled sessions, "
        f"got {after['scheduled_session_count']}"
    )


# --------------------------------------------------------------------------
# A presenter's calendar as a physical resource
# --------------------------------------------------------------------------
def _case_with_two_certified_presenters():
    """A scope-analysis case carrying two certified presenting supervisors."""
    set_clock("2026-08-12T09:00:00Z")
    petition = create_petition_in_scope_analysis()
    first = create_trained_supervisor(petition["id"], full_name="Morgan Alvarez")
    second = create_trained_supervisor(petition["id"], full_name="Priya Nadar")
    return {"petition": petition, "presenter": first, "other_presenter": second}


def _booked_ten_oclock_meeting(petition_id, presenter_id):
    """One hour-long small-group meeting starting at 10:00 on 2026-08-25."""
    return create_campaign_message(
        petition_id, channel="SMALL_GROUP_MEETING", audience_scope="CLASSIFICATION",
        presenter_supervisor_id=presenter_id, planned_delivery_at="2026-08-25T10:00:00Z",
        duration_minutes=60, message_summary=MEETING_SUMMARY,
    )


def _attempt_meeting(petition_id, presenter_id, planned_delivery_at, duration_minutes=30,
                     **overrides):
    payload = {
        "channel": "SMALL_GROUP_MEETING",
        "audience_scope": "CLASSIFICATION",
        "presenter_supervisor_id": presenter_id,
        "planned_delivery_at": planned_delivery_at,
        "duration_minutes": duration_minutes,
        "message_summary": MEETING_SUMMARY,
    }
    payload.update(overrides)
    return api_client.create_campaign_communication(
        create_campaign_communication_payload(petition_id, **payload), DIRECTOR
    )


def test_two_meetings_whose_travel_buffers_merely_touch_still_conflict():
    """A 10:00 hour-long meeting holds the presenter to 12:00 once the travel buffer is
    added, and a 13:00 meeting whose own buffer opens at 12:00 touches that endpoint.

    PRD: "Drafting a meeting-channel message also reserves the presenter's calendar,
    and the reservation is padded on both sides by a 60-minute travel buffer."
    PRD: "That interval is **closed at both ends**, so two reservations that merely
    touch at an endpoint still conflict, and the collision is reported as
    `ERR_PRESENTER_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/presenter_calendar_closed_symmetric_buffer
    """
    ctx = _case_with_two_certified_presenters()
    first = _booked_ten_oclock_meeting(ctx["petition"]["id"], ctx["presenter"]["id"])

    response = _attempt_meeting(
        ctx["petition"]["id"], ctx["presenter"]["id"], "2026-08-25T13:00:00Z"
    )
    validate_error(response, ApiErrorId.ERR_PRESENTER_SCHEDULE_CONFLICT)

    unchanged = read_campaign_message(first["id"])
    assert unchanged["status"] == "DRAFT", (
        f"the standing reservation is untouched, got {unchanged['status']}"
    )
    assert_instant_equals(
        unchanged["planned_delivery_at"], "2026-08-25T10:00:00Z",
        "communication.planned_delivery_at",
    )


def test_a_meeting_one_second_past_the_touching_instant_is_booked():
    """Moving the second meeting to 13:00:01 lifts its buffer clear of the first
    reservation's closing endpoint, and the draft is accepted.

    PRD: "Two meeting-channel messages sharing a `presenter_supervisor_id` may not
    overlap on the interval running from one hour before `planned_delivery_at` to one
    hour after the delivery instant plus `duration_minutes`."
    PRD: "That interval is **closed at both ends**, so two reservations that merely
    touch at an endpoint still conflict, and the collision is reported as
    `ERR_PRESENTER_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/presenter_calendar_closed_symmetric_buffer
    """
    ctx = _case_with_two_certified_presenters()
    _booked_ten_oclock_meeting(ctx["petition"]["id"], ctx["presenter"]["id"])

    validate_error(
        _attempt_meeting(ctx["petition"]["id"], ctx["presenter"]["id"], "2026-08-25T13:00:00Z"),
        ApiErrorId.ERR_PRESENTER_SCHEDULE_CONFLICT,
    )

    booked = validate_success(
        _attempt_meeting(ctx["petition"]["id"], ctx["presenter"]["id"], "2026-08-25T13:00:01Z"),
        expected_status=201,
    )
    assert_instant_equals(
        booked["planned_delivery_at"], "2026-08-25T13:00:01Z",
        "communication.planned_delivery_at",
    )
    assert booked["presenter_supervisor_id"] == ctx["presenter"]["id"], (
        "the second meeting names the same presenter, "
        f"got {booked['presenter_supervisor_id']}"
    )
    assert booked["status"] == "DRAFT", (
        f"a new draft starts at DRAFT, got {booked['status']}"
    )


def test_the_conflicting_slot_is_free_for_a_second_presenter():
    """The calendar is keyed to the presenter, so the very slot that collided for one
    supervisor is bookable for another.

    PRD: "Two meeting-channel messages sharing a `presenter_supervisor_id` may not
    overlap on the interval running from one hour before `planned_delivery_at` to one
    hour after the delivery instant plus `duration_minutes`."
    PRD: "Drafting a meeting-channel message also reserves the presenter's calendar,
    and the reservation is padded on both sides by a 60-minute travel buffer."

    Design: Difficulty/resource_temporal_overlap/presenter_calendar_closed_symmetric_buffer
    """
    ctx = _case_with_two_certified_presenters()
    _booked_ten_oclock_meeting(ctx["petition"]["id"], ctx["presenter"]["id"])

    validate_error(
        _attempt_meeting(ctx["petition"]["id"], ctx["presenter"]["id"], "2026-08-25T13:00:00Z"),
        ApiErrorId.ERR_PRESENTER_SCHEDULE_CONFLICT,
    )

    booked = validate_success(
        _attempt_meeting(
            ctx["petition"]["id"], ctx["other_presenter"]["id"], "2026-08-25T13:00:00Z"
        ),
        expected_status=201,
    )
    assert booked["presenter_supervisor_id"] == ctx["other_presenter"]["id"], (
        "the slot belongs to the second presenter, "
        f"got {booked['presenter_supervisor_id']}"
    )
    assert_instant_equals(
        booked["planned_delivery_at"], "2026-08-25T13:00:00Z",
        "communication.planned_delivery_at",
    )


def test_an_email_draft_reserves_no_calendar_at_the_conflicting_instant():
    """Only meeting channels reserve a presenter, so an email planned for the instant
    that collided carries no presenter and is drafted freely.

    PRD: "A `presenter_supervisor_id` names the presenting supervisor: it is required
    for the two meeting channels and absent otherwise."
    PRD: "Drafting a meeting-channel message also reserves the presenter's calendar,
    and the reservation is padded on both sides by a 60-minute travel buffer."

    Design: Difficulty/resource_temporal_overlap/presenter_calendar_closed_symmetric_buffer
    """
    ctx = _case_with_two_certified_presenters()
    _booked_ten_oclock_meeting(ctx["petition"]["id"], ctx["presenter"]["id"])

    validate_error(
        _attempt_meeting(ctx["petition"]["id"], ctx["presenter"]["id"], "2026-08-25T13:00:00Z"),
        ApiErrorId.ERR_PRESENTER_SCHEDULE_CONFLICT,
    )

    email = validate_success(
        api_client.create_campaign_communication(
            create_campaign_communication_payload(
                ctx["petition"]["id"], channel="EMAIL", audience_scope="CLASSIFICATION",
                planned_delivery_at="2026-08-25T13:00:00Z", duration_minutes=30,
            ),
            DIRECTOR,
        ),
        expected_status=201,
    )
    assert_absent(email, "presenter_supervisor_id", "communication")
    assert_instant_equals(
        email["planned_delivery_at"], "2026-08-25T13:00:00Z",
        "communication.planned_delivery_at",
    )


# --------------------------------------------------------------------------
# Classified headcount conserved across rulings and reconsiderations
# --------------------------------------------------------------------------
def test_a_reconsideration_returns_exactly_the_headcount_the_ruling_moved():
    """Ruling one group in and another out fills both settled buckets, and
    reconsidering the excluded group puts precisely its 12 heads back into pending.

    PRD: "When the ruling lands, the classification's `headcount` moves out of the
    case's `pending_headcount` and into either `included_headcount` or
    `excluded_headcount` according to the ruling, the rationale is written, the
    conservation identity is re-checked, and the petition's `version` increments."
    PRD: "It reverses the exact headcount movement the ruling made, returning the
    classification's `headcount` from `included_headcount` or `excluded_headcount` to
    `pending_headcount`, and it clears `ruling_rationale` back to absent."

    Design: Difficulty/compensating_invariant/unit_headcount_conservation_across_rule_and_reconsider
    """
    ctx = _scored_roster_of_110_heads()
    petition_id = ctx["petition"]["id"]
    assert _buckets(ctx["petition"]) == (0, 0, 110), (
        f"all 110 classified heads start pending, got {_buckets(ctx['petition'])}"
    )
    assert ctx["petition"]["total_classified_headcount"] == 110, (
        f"60 plus 30 plus 12 plus 8 is 110, "
        f"got {ctx['petition']['total_classified_headcount']}"
    )
    assert_headcount_conservation(ctx["petition"])

    version_before = ctx["petition"]["version"]
    rule_classification(ctx["by_code"]["PROD"]["id"], "INCLUDED")
    after_include = read_petition(petition_id)
    assert _buckets(after_include) == (60, 0, 50), (
        f"60 production heads moved into the unit, got {_buckets(after_include)}"
    )
    assert after_include["version"] == version_before + 1, (
        f"the ruling increments the case version, got {after_include['version']}"
    )
    assert_headcount_conservation(after_include)

    rule_classification(ctx["by_code"]["QC"]["id"], "EXCLUDED")
    after_exclude = read_petition(petition_id)
    assert _buckets(after_exclude) == (60, 12, 38), (
        f"12 inspector heads moved out of the unit, got {_buckets(after_exclude)}"
    )
    assert after_exclude["version"] == version_before + 2, (
        f"the second ruling increments again, got {after_exclude['version']}"
    )
    assert_headcount_conservation(after_exclude)

    reconsidered = reconsider_classification(
        ctx["by_code"]["QC"]["id"], reconsideration_note="The lab reports to the same manager."
    )
    assert reconsidered["scope_ruling"] == "PENDING", (
        f"the reconsidered group is unruled again, got {reconsidered['scope_ruling']}"
    )
    assert_absent(reconsidered, "ruling_rationale", "classification")

    after_reconsider = read_petition(petition_id)
    assert _buckets(after_reconsider) == (60, 0, 50), (
        "the excluded bucket gives back exactly the 12 heads it took, "
        f"got {_buckets(after_reconsider)}"
    )
    assert after_reconsider["total_classified_headcount"] == 110, (
        f"the classified total never moves, got {after_reconsider['total_classified_headcount']}"
    )
    assert_headcount_conservation(after_reconsider)


def test_a_reconsidered_group_can_be_ruled_the_other_way_with_the_totals_balanced():
    """Excluding a group, reconsidering it and then including it lands its 8 heads in
    the opposite bucket without ever disturbing the classified total.

    PRD: "Reconsideration takes a ruled classification — `INCLUDED` or `EXCLUDED` —
    back to `PENDING`, optionally recording a `reconsideration_note`."
    PRD: "On a petition, `included_headcount` plus `excluded_headcount` plus
    `pending_headcount` must always equal `total_classified_headcount`; a write that
    would leave those out of balance is rejected with
    `ERR_HEADCOUNT_CONSERVATION_VIOLATION` (HTTP 409) and nothing is persisted."

    Design: Difficulty/compensating_invariant/unit_headcount_conservation_across_rule_and_reconsider
    """
    ctx = _scored_roster_of_110_heads()
    petition_id = ctx["petition"]["id"]
    lead_id = ctx["by_code"]["LEAD"]["id"]

    rule_classification(lead_id, "EXCLUDED")
    excluded = read_petition(petition_id)
    assert _buckets(excluded) == (0, 8, 102), (
        f"the 8 lead heads sit outside the unit, got {_buckets(excluded)}"
    )
    assert_headcount_conservation(excluded)

    reconsider_classification(lead_id)
    back_to_pending = read_petition(petition_id)
    assert _buckets(back_to_pending) == (0, 0, 110), (
        f"every head is pending once more, got {_buckets(back_to_pending)}"
    )
    assert_headcount_conservation(back_to_pending)

    ruled_again = rule_classification(lead_id, "INCLUDED")
    assert ruled_again["scope_ruling"] == "INCLUDED", (
        f"the second ruling goes the other way, got {ruled_again['scope_ruling']}"
    )
    included = read_petition(petition_id)
    assert _buckets(included) == (8, 0, 102), (
        f"the same 8 heads now sit inside the unit, got {_buckets(included)}"
    )
    assert included["total_classified_headcount"] == 110, (
        f"the classified total is untouched, got {included['total_classified_headcount']}"
    )
    assert_headcount_conservation(included)


def test_reconsidering_an_included_group_drains_the_included_bucket_not_the_excluded_one():
    """With every group ruled and pending at zero, reconsidering an included group
    takes its heads back out of `included_headcount` and leaves the excluded bucket
    alone.

    PRD: "It reverses the exact headcount movement the ruling made, returning the
    classification's `headcount` from `included_headcount` or `excluded_headcount` to
    `pending_headcount`, and it clears `ruling_rationale` back to absent."
    PRD: "On a petition, `included_headcount` plus `excluded_headcount` plus
    `pending_headcount` must always equal `total_classified_headcount`; a write that
    would leave those out of balance is rejected with
    `ERR_HEADCOUNT_CONSERVATION_VIOLATION` (HTTP 409) and nothing is persisted."

    Design: Difficulty/compensating_invariant/unit_headcount_conservation_across_rule_and_reconsider
    """
    ctx = _scored_roster_of_110_heads()
    petition_id = ctx["petition"]["id"]
    rule_classification(ctx["by_code"]["PROD"]["id"], "INCLUDED")
    rule_classification(ctx["by_code"]["MAINT"]["id"], "INCLUDED")
    rule_classification(ctx["by_code"]["QC"]["id"], "EXCLUDED")
    rule_classification(ctx["by_code"]["LEAD"]["id"], "EXCLUDED")

    fully_ruled = read_petition(petition_id)
    assert _buckets(fully_ruled) == (90, 20, 0), (
        f"90 heads in, 20 out and none pending, got {_buckets(fully_ruled)}"
    )
    assert_headcount_conservation(fully_ruled)

    reconsider_classification(ctx["by_code"]["MAINT"]["id"])
    after = read_petition(petition_id)
    assert _buckets(after) == (60, 20, 30), (
        "the 30 maintenance heads leave the included bucket for pending, "
        f"got {_buckets(after)}"
    )
    assert_headcount_conservation(after)

    maintenance = _read_classification(ctx["by_code"]["MAINT"]["id"])
    assert maintenance["scope_ruling"] == "PENDING", (
        f"the maintenance group is unruled again, got {maintenance['scope_ruling']}"
    )
    assert_absent(maintenance, "ruling_rationale", "classification")


# --------------------------------------------------------------------------
# Physical ballots conserved across resolutions and reopens
# --------------------------------------------------------------------------
def test_each_resolution_moves_one_ballot_out_of_the_open_pool_and_into_one_bucket():
    """Counting one challenge for the union and withdrawing another moves two ballots
    out of the open pool without changing the number of ballots in the box.

    PRD: "Every resolution stamps `resolved_at`, lowers the round's
    `challenged_open_count` by 1, and raises exactly one of
    `challenged_counted_for_count`, `challenged_counted_against_count`,
    `challenged_voided_count` or `challenged_withdrawn_count` by 1."
    PRD: "Withdrawn challenges never enter any vote column, though they remain inside
    `ballots_cast_total`."

    Design: Difficulty/compensating_invariant/ballot_conservation_across_resolve_and_reopen
    """
    ctx = _tally_posted_with_three_open_challenges()
    posted = ctx["round"]
    assert posted["ballots_cast_total"] == 85, (
        f"82 unchallenged plus 3 segregated ballots is 85, got {posted['ballots_cast_total']}"
    )
    assert_ballot_conservation(posted)

    counted = resolve_ballot(ctx["ballots"][0]["id"], resolution="COUNTED_FOR")
    assert counted["resolution"] == "COUNTED_FOR", (
        f"the first challenge is counted for the union, got {counted['resolution']}"
    )
    assert counted["resolved_at"] is not None, "a resolution stamps resolved_at"

    withdrawn = resolve_ballot(
        ctx["ballots"][1]["id"], resolution="WITHDRAWN", withdrawing_party="UNION"
    )
    assert withdrawn["resolution"] == "WITHDRAWN", (
        f"the union withdrew its own challenge, got {withdrawn['resolution']}"
    )

    after = read_round(ctx["round"]["id"])
    assert after["challenged_open_count"] == 1, (
        f"two ballots left the open pool, got {after['challenged_open_count']}"
    )
    assert after["challenged_counted_for_count"] == 1, (
        f"one ballot entered the for column, got {after['challenged_counted_for_count']}"
    )
    assert after["challenged_withdrawn_count"] == 1, (
        f"one ballot was withdrawn, got {after['challenged_withdrawn_count']}"
    )
    assert after["challenged_counted_against_count"] == 0, (
        "no ballot went against, got "
        f"{after['challenged_counted_against_count']}"
    )
    assert after["challenged_voided_count"] == 0, (
        f"no ballot was voided, got {after['challenged_voided_count']}"
    )
    assert after["ballots_cast_total"] == 85, (
        f"the box still holds 85 ballots, got {after['ballots_cast_total']}"
    )
    assert_ballot_conservation(after)


def test_a_reopen_undoes_the_resolution_bucket_for_bucket():
    """Reopening a counted ballot empties the bucket the resolution filled, returns the
    ballot to the open pool and leaves it free to be resolved the other way.

    PRD: "Resolution and reopening are exact inverses of one another: a resolution
    moves one ballot out of the open bucket and into exactly one other bucket, and a
    reopen moves that same ballot back."
    PRD: "A segregated ballot begins with `resolution` `OPEN`, `reopen_count` 0 and no
    `resolved_at`; it raises the session's `challenged_ballot_count` by 1, the round's
    `challenged_open_count` by 1, and the round's `ballots_cast_total` by 1, because a
    challenged ballot is a real ballot that entered the box."
    PRD: "Reopening is only possible while the round is `TALLY_POSTED` or
    `TALLY_REVISED`, only on a ballot that is not `OPEN`, and only while `reopen_count`
    is still below its ceiling of 2; a third reopen is refused with
    `ERR_REOPEN_LIMIT_EXCEEDED`."

    Design: Difficulty/compensating_invariant/ballot_conservation_across_resolve_and_reopen
    """
    ctx = _tally_posted_with_three_open_challenges()
    ballot_id = ctx["ballots"][0]["id"]
    resolve_ballot(ballot_id, resolution="COUNTED_FOR")
    resolved_round = read_round(ctx["round"]["id"])
    assert resolved_round["challenged_counted_for_count"] == 1, (
        f"the ballot sits in the for column, "
        f"got {resolved_round['challenged_counted_for_count']}"
    )
    assert_ballot_conservation(resolved_round)

    reopened = reopen_ballot(ballot_id, reopen_reason="The challenger produced new payroll data.")
    assert reopened["resolution"] == "OPEN", (
        f"the ballot is open again, got {reopened['resolution']}"
    )
    assert_absent(reopened, "resolved_at", "challenged_ballot")
    assert reopened["reopen_count"] == 1, (
        f"the first reopen counts once, got {reopened['reopen_count']}"
    )

    after_reopen = read_round(ctx["round"]["id"])
    assert after_reopen["challenged_counted_for_count"] == 0, (
        "the for column gives the ballot back, got "
        f"{after_reopen['challenged_counted_for_count']}"
    )
    assert after_reopen["challenged_open_count"] == 3, (
        f"all three challenges are open once more, got {after_reopen['challenged_open_count']}"
    )
    assert after_reopen["ballots_cast_total"] == 85, (
        f"the box is unchanged by a reopen, got {after_reopen['ballots_cast_total']}"
    )
    assert_ballot_conservation(after_reopen)

    re_resolved = resolve_ballot(ballot_id, resolution="COUNTED_AGAINST")
    assert re_resolved["resolution"] == "COUNTED_AGAINST", (
        f"the reopened ballot may land in a different bucket, got {re_resolved['resolution']}"
    )
    after_re_resolution = read_round(ctx["round"]["id"])
    assert after_re_resolution["challenged_counted_against_count"] == 1, (
        "the ballot now sits in the against column, got "
        f"{after_re_resolution['challenged_counted_against_count']}"
    )
    assert after_re_resolution["challenged_counted_for_count"] == 0, (
        f"and no longer in the for column, "
        f"got {after_re_resolution['challenged_counted_for_count']}"
    )
    assert after_re_resolution["challenged_open_count"] == 2, (
        f"two challenges remain open, got {after_re_resolution['challenged_open_count']}"
    )
    assert_ballot_conservation(after_re_resolution)


def test_a_corrected_tally_converges_with_the_ballot_total_untouched():
    """Revising, reopening a counted ballot, re-resolving it the other way and revising
    again moves one ballot between vote columns while the box still holds 85 ballots.

    PRD: "Revising is also a self-loop: a round already in `TALLY_REVISED` may be
    revised again after a ballot has been reopened and re-resolved, overwriting the
    revised fields and advancing `tally_revised_at`, so a corrected tally can converge."
    PRD: "On an election round, the physical ballots that entered the box are
    conserved: `provisional_votes_for` plus `challenged_counted_for_count`, plus
    `provisional_votes_against` plus `challenged_counted_against_count`, plus
    `provisional_void_count` plus `challenged_voided_count`, plus
    `challenged_withdrawn_count`, plus `challenged_open_count`, must equal
    `ballots_cast_total`."

    Design: Difficulty/compensating_invariant/ballot_conservation_across_resolve_and_reopen
    """
    ctx = _tally_posted_with_three_open_challenges()
    first_ballot, second_ballot, third_ballot = ctx["ballots"]
    resolve_ballot(first_ballot["id"], resolution="COUNTED_FOR")
    resolve_ballot(second_ballot["id"], resolution="COUNTED_FOR")
    resolve_ballot(third_ballot["id"], resolution="VOIDED")

    first_revision = validate_success(api_client.revise_tally(ctx["round"]["id"], BOARD))
    assert first_revision["revised_votes_for"] == 44, (
        f"both counted challenges go to the union, got {first_revision['revised_votes_for']}"
    )
    assert_ballot_conservation(first_revision)

    reopen_ballot(second_ballot["id"])
    resolve_ballot(second_ballot["id"], resolution="COUNTED_AGAINST")

    second_revision = validate_success(api_client.revise_tally(ctx["round"]["id"], BOARD))
    assert second_revision["status"] == "TALLY_REVISED", (
        f"the round stays revised across the correction, got {second_revision['status']}"
    )
    assert second_revision["revised_votes_for"] == 43, (
        f"42 provisional plus one counted-for is 43, got {second_revision['revised_votes_for']}"
    )
    assert second_revision["revised_votes_against"] == 40, (
        "39 provisional plus one counted-against is 40, got "
        f"{second_revision['revised_votes_against']}"
    )
    assert second_revision["revised_void_count"] == 2, (
        f"one provisional void plus one voided challenge is 2, "
        f"got {second_revision['revised_void_count']}"
    )
    assert second_revision["revised_margin"] == 3, (
        f"43 less 40 is a margin of 3, got {second_revision['revised_margin']}"
    )
    assert second_revision["valid_votes_cast"] == 83, (
        f"43 plus 40 is a base of 83 valid votes, got {second_revision['valid_votes_cast']}"
    )
    assert second_revision["majority_threshold"] == 42, (
        f"83 halved and floored plus one is 42, got {second_revision['majority_threshold']}"
    )
    assert second_revision["ballots_cast_total"] == 85, (
        f"no reopen or re-resolution changes the box, "
        f"got {second_revision['ballots_cast_total']}"
    )
    assert_ballot_conservation(second_revision)
