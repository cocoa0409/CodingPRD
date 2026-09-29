"""Layered request gates and same-request read consistency.

Covers where the read-consistency assertions on petitions and election rounds sit
relative to the schema, existence, role and business-rule layers around them; how a
blocking charge fans out across a case and unwinds only part of the way; how a fresh
verification of the showing switches the headcount base it divides by; how the cure
loop on an eligible-voter list counts resubmissions per list; and how every write
hands back its own recomputed figures that the next read of any collection agrees with.
"""
from test_helpers import (
    BOARD,
    DIRECTOR,
    NON_EXISTENT_UUID,
    TRAINER,
    ApiErrorId,
    add_business_days,
    add_complete_entries,
    add_incomplete_entries,
    api_client,
    assert_ballot_conservation,
    assert_campaign_communication,
    assert_election_round,
    assert_headcount_conservation,
    assert_instant_equals,
    assert_instants_equal,
    assert_petition,
    assert_poll_session,
    assert_supervisor,
    assert_voter_list,
    accuracy_review,
    create_approved_message,
    create_campaign_message,
    create_petition,
    create_poll_session,
    create_trained_supervisor,
    create_voter_list,
    docket_blocking_charge,
    open_scope_analysis,
    petition_version,
    plus_days,
    plus_hours,
    read_campaign_message,
    record_violation,
    read_petition,
    read_poll_session,
    read_round,
    read_voter_list,
    reconsider_classification,
    resolve_ballot,
    review_voter_list,
    round_version,
    rule_classification,
    score_classification,
    segregate_ballot,
    set_clock,
    settle_charge,
    setup_accepted_voter_list,
    setup_election_set,
    setup_polls_closed,
    setup_polls_open,
    setup_sessions_laid_out,
    submit_message_for_review,
    submit_voter_list,
    train_supervisor,
    validate_error,
    validate_paginated,
    validate_success,
    verify_showing,
    add_classification,
)

# The five statutory cards figures used by every showing verification below: 45 cards
# submitted, 10 struck for the four defect reasons, so 35 valid cards remain.
CARD_COUNTS = {
    "submitted_card_count": 45,
    "duplicate_card_count": 3,
    "undated_card_count": 2,
    "stale_card_count": 2,
    "nonunit_card_count": 3,
}


def _case_with_election_set():
    """A stipulated case whose voter-list deadline falls on 2026-08-24."""
    return setup_election_set(clock="2026-08-20T15:00:00Z")


def _case_with_three_classifications():
    """Scope analysis with production, maintenance and quality-control groups.

    Production and maintenance are ruled into the unit; quality control is scored
    but left unruled, so 102 classified heads split 90 included and 12 pending.
    """
    set_clock("2026-08-03T09:00:00Z")
    petition = create_petition()
    open_scope_analysis(petition["id"])
    production = add_classification(
        petition["id"], code="PROD", title="Production Operator", headcount=60,
        avg_hourly_wage_cents=2400,
    )
    maintenance = add_classification(
        petition["id"], code="MAINT", title="Maintenance Mechanic", headcount=30,
        avg_hourly_wage_cents=3200, supervision_overlap=82, skills_overlap=78,
        functional_integration=86, interchange_rate=61, work_conditions_overlap=84,
    )
    quality = add_classification(
        petition["id"], code="QC", title="Quality Inspector", headcount=12,
        avg_hourly_wage_cents=2900, employer_position="EXCLUDE", union_position="INCLUDE",
        shift_code="B", work_location="PLANT_1_LAB", supervision_overlap=41,
        skills_overlap=55, functional_integration=61, interchange_rate=21,
        work_conditions_overlap=71,
    )
    for classification in (production, maintenance, quality):
        score_classification(classification["id"], "TRADITIONAL")
    rule_classification(production["id"], "INCLUDED")
    rule_classification(maintenance["id"], "INCLUDED")
    return petition, production, maintenance, quality


def _list_returned_for_cure_twice():
    """A four-entry list carried through both permitted cure resubmissions.

    Three of the four entries are complete, so every grading of the list scores
    75.00 and lands on MATERIAL_DEFECT with its 24-hour cure window.
    """
    ctx = _case_with_election_set()
    voter_list = create_voter_list(ctx["petition"]["id"], ctx["agreement"]["id"])
    classification_id = ctx["classifications"][0]["id"]
    add_complete_entries(voter_list["id"], classification_id, 3)
    add_incomplete_entries(voter_list["id"], classification_id, 1)
    set_clock("2026-08-21T10:00:00Z")
    filed = submit_voter_list(voter_list["id"])
    first_review = review_voter_list(
        voter_list["id"], "RETURN_FOR_CURE", ["MISSING_PERSONAL_EMAIL"]
    )
    set_clock("2026-08-21T12:00:00Z")
    first_cure = api_client.resubmit_voter_list(
        voter_list["id"], {"attested_by_title": "Director of Labor Relations"}, DIRECTOR
    )
    first_cure = validate_success(first_cure)
    second_review = review_voter_list(
        voter_list["id"], "RETURN_FOR_CURE", ["MISSING_PERSONAL_EMAIL"]
    )
    set_clock("2026-08-21T14:00:00Z")
    second_cure = validate_success(api_client.resubmit_voter_list(
        voter_list["id"], {"attested_by_title": "Director of Labor Relations"}, DIRECTOR
    ))
    third_review = review_voter_list(
        voter_list["id"], "RETURN_FOR_CURE", ["MISSING_PERSONAL_EMAIL"]
    )
    return {
        "ctx": ctx,
        "voter_list_id": voter_list["id"],
        "filed": filed,
        "reviews": [first_review, second_review, third_review],
        "cures": [first_cure, second_cure],
    }


def _case_at_polls_closed_with_three_open_challenges():
    """Two closed sessions and three ballots still in dispute on the round.

    The sessions close 30 for, 25 against, 1 void and 12 for, 14 against, none
    void, so 82 unchallenged ballots plus 3 challenged ones entered the box.
    """
    ctx = setup_accepted_voter_list(entry_count=3, clock="2026-08-20T15:00:00Z")
    ctx = setup_sessions_laid_out(ctx, session_specs=[
        {
            "location_code": "PLANT_1_CAFETERIA", "method": "MANUAL",
            "session_start_at": "2026-09-01T08:00:00Z",
            "session_end_at": "2026-09-01T12:00:00Z",
        },
        {
            "location_code": "PLANT_2_BREAKROOM", "method": "MANUAL",
            "session_start_at": "2026-09-01T08:00:00Z",
            "session_end_at": "2026-09-01T12:00:00Z",
        },
    ])
    ctx = setup_polls_open(ctx)
    first_session, second_session = ctx["sessions"]
    entries = ctx["entries"]
    ctx["ballots"] = [
        segregate_ballot(
            first_session["id"], voter_list_entry_id=entries[0]["id"],
            challenger_party="EMPLOYER", basis="SUPERVISOR",
        ),
        segregate_ballot(
            first_session["id"], voter_list_entry_id=entries[1]["id"],
            challenger_party="UNION", basis="NOT_ON_LIST",
        ),
        segregate_ballot(
            second_session["id"], voter_list_entry_id=entries[2]["id"],
            challenger_party="EMPLOYER", basis="OUTSIDE_UNIT",
        ),
    ]
    ctx = setup_polls_closed(ctx, session_counts=[
        {"votes_for_count": 30, "votes_against_count": 25, "void_count": 1},
        {"votes_for_count": 12, "votes_against_count": 14, "void_count": 0},
    ])
    return ctx


def _case_with_trained_presenter_and_approved_meeting():
    """An approved small-group meeting whose presenting supervisor is certified."""
    ctx = _case_with_election_set()
    supervisor = create_trained_supervisor(
        ctx["petition"]["id"], full_name="Marta Chen", job_title="Line Lead",
        span_of_control=14,
    )
    message = create_approved_message(
        ctx["petition"]["id"],
        message_overrides={
            "channel": "SMALL_GROUP_MEETING",
            "audience_scope": "CLASSIFICATION",
            "presenter_supervisor_id": supervisor["id"],
            "planned_delivery_at": "2026-08-27T13:00:00Z",
            "duration_minutes": 30,
        },
    )
    ctx["supervisor"] = supervisor
    ctx["message"] = message
    set_clock("2026-08-24T09:00:00Z")
    return ctx


# --------------------------------------------------------------------------
# Opening an eligible-voter list: where the petition read-consistency check sits
# --------------------------------------------------------------------------
def test_opening_a_voter_list_without_the_asserted_petition_version_is_a_schema_failure():
    """A create that never states the petition version it read fails at the schema layer, before any lookup.

    PRD: "The field is not optional: a create request that omits it fails validation with `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/cross_cutting_complexity_layers/the_petition_version_gate_sits_between_existence_and_business_rules
    """
    ctx = _case_with_election_set()
    resp = api_client.create_voter_list(
        {"petition_id": ctx["petition"]["id"], "election_agreement_id": ctx["agreement"]["id"]},
        DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    listing = api_client.list_voter_lists(BOARD, params={"petition_id": ctx["petition"]["id"]})
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, "a schema failure must not open a list"
    assert rows == []


def test_an_unknown_election_agreement_outranks_a_stale_petition_version():
    """A body reference that resolves to nothing is reported before the petition version is compared at all.

    PRD: "Only then are the foreign keys in the body resolved, in the order the endpoint declares its input fields, each producing the referenced type's own not-found code."

    Design: Corner/cross_cutting_complexity_layers/the_petition_version_gate_sits_between_existence_and_business_rules
    """
    ctx = _case_with_election_set()
    petition_id = ctx["petition"]["id"]
    current = petition_version(petition_id)

    resp = api_client.create_voter_list(
        {
            "petition_id": petition_id,
            "election_agreement_id": NON_EXISTENT_UUID,
            "expected_petition_version": current - 1,
        },
        DIRECTOR,
    )
    validate_error(resp, ApiErrorId.ERR_ELECTION_AGREEMENT_NOT_FOUND)

    petition = read_petition(petition_id)
    assert_petition(petition)
    assert petition["version"] == current, "a rejected create must leave the petition version alone"


def test_a_role_that_may_not_open_a_voter_list_outranks_a_stale_petition_version():
    """An unauthorized caller is turned away before the petition version comparison runs.

    PRD: "The comparison runs after authentication, role and existence checks, and before any business validation."

    Design: Corner/cross_cutting_complexity_layers/the_petition_version_gate_sits_between_existence_and_business_rules
    """
    ctx = _case_with_election_set()
    petition_id = ctx["petition"]["id"]
    current = petition_version(petition_id)

    resp = api_client.create_voter_list(
        {
            "petition_id": petition_id,
            "election_agreement_id": ctx["agreement"]["id"],
            "expected_petition_version": current - 1,
        },
        TRAINER,
    )
    validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)

    listing = api_client.list_voter_lists(BOARD, params={"petition_id": petition_id})
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, "a refused role must not open a list"
    assert read_petition(petition_id)["version"] == current


def test_replaying_an_accepted_voter_list_create_conflicts_on_the_asserted_version():
    """The first create bumps the petition version by one, so the identical second create is stale and writes nothing.

    PRD: "On success the petition's `version` increments by exactly 1, so replaying the same create with the same asserted value conflicts."

    Design: Corner/cross_cutting_complexity_layers/the_petition_version_gate_sits_between_existence_and_business_rules
    """
    ctx = _case_with_election_set()
    petition_id = ctx["petition"]["id"]
    observed = petition_version(petition_id)
    payload = {
        "petition_id": petition_id,
        "election_agreement_id": ctx["agreement"]["id"],
        "expected_petition_version": observed,
    }

    created = validate_success(api_client.create_voter_list(payload, DIRECTOR), 201)
    assert_voter_list(created)
    assert created["status"] == "DRAFT"
    assert_instant_equals(
        created["due_at"], add_business_days("2026-08-20", 2), "voter_list.due_at"
    )
    assert read_petition(petition_id)["version"] == observed + 1

    replay = api_client.create_voter_list(payload, DIRECTOR)
    validate_error(replay, ApiErrorId.ERR_STALE_PETITION_VERSION)

    listing = api_client.list_voter_lists(BOARD, params={"petition_id": petition_id})
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1, "the stale replay must not open a second list"
    assert rows[0]["id"] == created["id"]
    assert read_petition(petition_id)["version"] == observed + 1


# --------------------------------------------------------------------------
# Laying out polling sessions: the round version check ahead of the geometry
# --------------------------------------------------------------------------
def _session_payload(round_id, **overrides):
    payload = {
        "election_round_id": round_id,
        "location_code": "PLANT_1_CAFETERIA",
        "session_start_at": "2026-09-01T08:00:00Z",
        "session_end_at": "2026-09-01T12:00:00Z",
        "method": "MANUAL",
    }
    payload.update(overrides)
    return payload


def test_laying_out_a_session_without_the_asserted_round_version_is_a_schema_failure():
    """A layout request that never states the round version it read is refused at the schema layer.

    PRD: "Creating a poll session requires `expected_election_round_version`, carrying the client's last observed `version` of the target election round; again the field is mandatory, and its absence is `ERR_INVALID_REQUEST` (HTTP 422)."

    Design: Corner/cross_cutting_complexity_layers/the_round_version_gate_runs_before_the_layout_geometry_checks
    """
    ctx = _case_with_election_set()
    round_id = ctx["round"]["id"]

    resp = api_client.create_poll_session(_session_payload(round_id), BOARD)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    listing = api_client.list_poll_sessions(BOARD, params={"election_round_id": round_id})
    _, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, "a schema failure must not lay out a session"
    assert read_round(round_id)["scheduled_session_count"] == 0


def test_replaying_an_accepted_session_layout_conflicts_on_the_round_version():
    """A successful layout raises the round's session count and version by one, so the replay is stale.

    PRD: "On success the round's `scheduled_session_count` rises by 1 and its `version` increments by exactly 1."

    Design: Corner/cross_cutting_complexity_layers/the_round_version_gate_runs_before_the_layout_geometry_checks
    """
    ctx = _case_with_election_set()
    round_id = ctx["round"]["id"]
    observed = round_version(round_id)
    payload = _session_payload(round_id, expected_election_round_version=observed)

    created = validate_success(api_client.create_poll_session(payload, BOARD), 201)
    assert_poll_session(created)
    assert created["status"] == "SCHEDULED"

    round_row = read_round(round_id)
    assert_election_round(round_row)
    assert round_row["scheduled_session_count"] == 1
    assert round_row["version"] == observed + 1

    replay = api_client.create_poll_session(payload, BOARD)
    validate_error(replay, ApiErrorId.ERR_STALE_ROUND_VERSION)

    listing = api_client.list_poll_sessions(BOARD, params={"election_round_id": round_id})
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1, "the stale replay must not lay out a second session"
    assert rows[0]["id"] == created["id"]
    assert read_round(round_id)["version"] == observed + 1


def test_a_stale_round_version_outranks_the_location_overlap_check():
    """An overlapping layout that also asserts a stale round version is reported as the version conflict.

    PRD: "The location-overlap and observer-capacity checks therefore run only after the version comparison has succeeded."

    Design: Corner/cross_cutting_complexity_layers/the_round_version_gate_runs_before_the_layout_geometry_checks
    """
    ctx = _case_with_election_set()
    round_id = ctx["round"]["id"]
    stale = round_version(round_id)
    first = create_poll_session(
        round_id, location_code="PLANT_1_CAFETERIA",
        session_start_at="2026-09-01T08:00:00Z", session_end_at="2026-09-01T12:00:00Z",
    )
    current = round_version(round_id)
    assert current == stale + 1

    resp = api_client.create_poll_session(
        _session_payload(round_id, expected_election_round_version=stale), BOARD
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ROUND_VERSION)

    round_row = read_round(round_id)
    assert round_row["scheduled_session_count"] == 1
    assert round_row["version"] == current
    assert read_poll_session(first["id"])["status"] == "SCHEDULED"


def test_an_overlapping_location_is_refused_once_the_round_version_is_current():
    """With the asserted version current, a second crew at the same location and hour collides.

    PRD: "Occupancy of a location extends 30 minutes past a session's close to allow for teardown, so two sessions at the same `location_code` on the same round may not overlap on the interval running from `session_start_at` up to but not including `session_end_at` plus 30 minutes."

    Design: Corner/cross_cutting_complexity_layers/the_round_version_gate_runs_before_the_layout_geometry_checks
    """
    ctx = _case_with_election_set()
    round_id = ctx["round"]["id"]
    create_poll_session(
        round_id, location_code="PLANT_1_CAFETERIA",
        session_start_at="2026-09-01T08:00:00Z", session_end_at="2026-09-01T12:00:00Z",
    )
    current = round_version(round_id)

    collision = api_client.create_poll_session(
        _session_payload(round_id, expected_election_round_version=current), BOARD
    )
    validate_error(collision, ApiErrorId.ERR_POLL_SESSION_LOCATION_CONFLICT)

    round_row = read_round(round_id)
    assert round_row["scheduled_session_count"] == 1
    assert round_row["version"] == current, "a refused layout writes nothing"

    elsewhere = validate_success(api_client.create_poll_session(
        _session_payload(
            round_id, location_code="PLANT_2_BREAKROOM",
            expected_election_round_version=current,
        ),
        BOARD,
    ), 201)
    assert elsewhere["location_code"] == "PLANT_2_BREAKROOM"
    reread = read_round(round_id)
    assert reread["scheduled_session_count"] == 2
    assert reread["version"] == current + 1


# --------------------------------------------------------------------------
# A blocking charge: which siblings it reaches, and how far the unwind goes
# --------------------------------------------------------------------------
def _case_with_sessions_and_three_messages():
    """An election-set case carrying two scheduled sessions and three messages.

    One message is left in draft, one is waiting on legal review and one has been
    approved, so the three source statuses can be told apart afterwards.
    """
    ctx = _case_with_election_set()
    petition_id = ctx["petition"]["id"]
    round_id = ctx["round"]["id"]
    ctx["sessions"] = [
        create_poll_session(
            round_id, location_code="PLANT_1_CAFETERIA",
            session_start_at="2026-09-01T08:00:00Z",
            session_end_at="2026-09-01T12:00:00Z",
        ),
        create_poll_session(
            round_id, location_code="PLANT_2_BREAKROOM",
            session_start_at="2026-09-01T08:00:00Z",
            session_end_at="2026-09-01T12:00:00Z",
        ),
    ]
    ctx["draft_message"] = create_campaign_message(
        petition_id, planned_delivery_at="2026-08-26T09:00:00Z",
    )
    pending = create_campaign_message(
        petition_id, planned_delivery_at="2026-08-26T11:00:00Z",
    )
    accuracy_review(pending["id"])
    ctx["pending_message"] = submit_message_for_review(pending["id"])
    ctx["approved_message"] = create_approved_message(
        petition_id, message_overrides={"planned_delivery_at": "2026-08-26T15:00:00Z"},
    )
    ctx["round"] = read_round(round_id)
    return ctx


def test_a_blocking_charge_suspends_the_round_cancels_its_sessions_and_blocks_only_approved_messages():
    """Docketing the charge suspends the scheduled round, cancels its sessions and blocks the approved message alone.

    PRD: "Selective means a cascade names the states it acts on and leaves siblings alone: the blocking-charge cascade blocks approved campaign messages but not drafts, whereas the dismissal cascade blocks drafts as well."

    Design: Corner/cross_cutting_complexity_layers/the_posture_cascade_selects_by_source_status_and_only_partly_reverses
    """
    ctx = _case_with_sessions_and_three_messages()
    petition_id = ctx["petition"]["id"]
    assert ctx["round"]["scheduled_session_count"] == 2

    docket_blocking_charge(petition_id)

    petition = read_petition(petition_id)
    assert_petition(petition)
    assert petition["case_posture"] == "BLOCKED"
    assert petition["blocking_charge_count"] == 1
    assert petition["case_status"] == "ELECTION_SET", (
        "the two lifecycle dimensions move independently"
    )

    round_row = read_round(ctx["round"]["id"])
    assert round_row["status"] == "SUSPENDED"
    assert round_row["scheduled_session_count"] == 0
    for session in ctx["sessions"]:
        assert read_poll_session(session["id"])["status"] == "CANCELLED"

    blocked = read_campaign_message(ctx["approved_message"]["id"])
    assert_campaign_communication(blocked)
    assert blocked["status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "POSTURE_BLOCKED"

    assert read_campaign_message(ctx["draft_message"]["id"])["status"] == "DRAFT"
    still_pending = read_campaign_message(ctx["pending_message"]["id"])
    assert still_pending["status"] == "PENDING_LEGAL_REVIEW"
    assert still_pending["blocked_reason"] is None

    listing = api_client.list_campaign_communications(
        DIRECTOR, params={"petition_id": petition_id, "status": "BLOCKED"}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["approved_message"]["id"]


def test_settling_the_last_blocking_charge_restores_the_round_and_the_message_but_not_the_sessions():
    """The unwind returns the round to scheduled and the message to approved, while the cancelled sessions stay cancelled.

    PRD: "Partly reversible means the unwinding of a cascade is narrower than the cascade itself: when the last blocking charge on a case goes away, suspended rounds return to `SCHEDULED` and messages blocked for that specific reason return to `APPROVED`, but poll sessions that were cancelled during the block are never restored and must be laid out again."

    Design: Corner/cross_cutting_complexity_layers/the_posture_cascade_selects_by_source_status_and_only_partly_reverses
    """
    ctx = _case_with_sessions_and_three_messages()
    petition_id = ctx["petition"]["id"]
    charge = docket_blocking_charge(petition_id)
    assert read_petition(petition_id)["case_posture"] == "BLOCKED"

    settled = settle_charge(charge["id"], "NON_BOARD")
    assert settled["status"] == "SETTLED"
    assert_instant_equals(settled["settled_at"], "2026-08-20T15:00:00Z", "charge.settled_at")

    petition = read_petition(petition_id)
    assert petition["case_posture"] == "OPEN"
    assert petition["blocking_charge_count"] == 0
    assert petition["notice_posting_end_at"] is None, (
        "no notice period is opened when no posting days are ordered"
    )

    round_row = read_round(ctx["round"]["id"])
    assert round_row["status"] == "SCHEDULED"
    assert round_row["scheduled_session_count"] == 0, (
        "the cancelled sessions are not restored by the unwind"
    )
    for session in ctx["sessions"]:
        assert read_poll_session(session["id"])["status"] == "CANCELLED"

    restored = read_campaign_message(ctx["approved_message"]["id"])
    assert restored["status"] == "APPROVED"
    assert restored["blocked_reason"] is None
    assert read_campaign_message(ctx["draft_message"]["id"])["status"] == "DRAFT"
    assert read_campaign_message(ctx["pending_message"]["id"])["status"] == "PENDING_LEGAL_REVIEW"


# --------------------------------------------------------------------------
# Verifying the showing again after the scope rulings have moved
# --------------------------------------------------------------------------
def test_verifying_the_showing_again_after_the_last_ruling_switches_to_the_ruled_base():
    """While one group is unruled the showing divides by every classified head; once all three are ruled it divides by the included heads.

    PRD: "If every classification on the case has been ruled — that is, each one's `scope_ruling` is either `INCLUDED` or `EXCLUDED` — the basis is `AS_RULED` and the denominator is the case's `included_headcount`, because once scope is settled only the classifications actually inside the voting unit form the base."

    Design: Corner/cross_cutting_complexity_layers/re_verifying_after_the_last_ruling_switches_the_denominator_variant
    """
    petition, _production, _maintenance, quality = _case_with_three_classifications()

    first = verify_showing(petition["id"], **CARD_COUNTS)
    assert_petition(first)
    assert first["valid_card_count"] == 35
    assert first["showing_headcount_basis"] == "AS_PETITIONED"
    assert round(float(first["showing_of_interest_pct"]), 2) == 34.31
    assert first["showing_verdict"] == "SUFFICIENT"
    assert first["case_status"] == "SOI_VERIFIED"
    assert first["total_classified_headcount"] == 102
    assert first["included_headcount"] == 90
    assert first["pending_headcount"] == 12

    ruled = rule_classification(quality["id"], "EXCLUDED")
    assert ruled["scope_ruling"] == "EXCLUDED"
    after_ruling = read_petition(petition["id"])
    assert_headcount_conservation(after_ruling)
    assert after_ruling["included_headcount"] == 90
    assert after_ruling["excluded_headcount"] == 12
    assert after_ruling["pending_headcount"] == 0
    assert after_ruling["showing_headcount_basis"] == "AS_PETITIONED", (
        "the ruling moves headcount but does not itself re-run the audit"
    )
    assert round(float(after_ruling["showing_of_interest_pct"]), 2) == 34.31

    second = verify_showing(petition["id"], **CARD_COUNTS)
    assert second["case_status"] == "SOI_VERIFIED"
    assert second["valid_card_count"] == 35
    assert second["showing_headcount_basis"] == "AS_RULED"
    assert round(float(second["showing_of_interest_pct"]), 2) == 38.89
    assert second["showing_verdict"] == "SUFFICIENT"


def test_reconsidering_a_ruling_swings_the_showing_base_back_and_then_forward_again():
    """Returning a ruled group to pending puts the audit back on the petitioned base, and ruling it out again raises the percentage further.

    PRD: "If at least one classification is still `PENDING`, or has become `MOOT`, the basis is `AS_PETITIONED` and the denominator is `total_classified_headcount`, because with scope unresolved the Board tests the showing against the unit as the petition described it — every classified head counts, including the ones the employer wants excluded."

    Design: Corner/cross_cutting_complexity_layers/re_verifying_after_the_last_ruling_switches_the_denominator_variant
    """
    petition, _production, maintenance, quality = _case_with_three_classifications()
    verify_showing(petition["id"], **CARD_COUNTS)
    rule_classification(quality["id"], "EXCLUDED")
    ruled_basis = verify_showing(petition["id"], **CARD_COUNTS)
    assert ruled_basis["showing_headcount_basis"] == "AS_RULED"
    assert round(float(ruled_basis["showing_of_interest_pct"]), 2) == 38.89

    reconsidered = reconsider_classification(
        maintenance["id"], "The hearing reopened the maintenance mechanics' community of interest."
    )
    assert reconsidered["scope_ruling"] == "PENDING"
    assert reconsidered["ruling_rationale"] is None
    back_to_pending = read_petition(petition["id"])
    assert_headcount_conservation(back_to_pending)
    assert back_to_pending["included_headcount"] == 60
    assert back_to_pending["pending_headcount"] == 30
    assert back_to_pending["excluded_headcount"] == 12

    third = verify_showing(petition["id"], **CARD_COUNTS)
    assert third["showing_headcount_basis"] == "AS_PETITIONED"
    assert round(float(third["showing_of_interest_pct"]), 2) == 34.31

    rule_classification(maintenance["id"], "EXCLUDED")
    fourth = verify_showing(petition["id"], **CARD_COUNTS)
    assert fourth["showing_headcount_basis"] == "AS_RULED"
    assert fourth["included_headcount"] == 60
    assert round(float(fourth["showing_of_interest_pct"]), 2) == 58.33
    assert fourth["showing_verdict"] == "SUFFICIENT"


# --------------------------------------------------------------------------
# The cure loop: a counter that belongs to one list and starts over on the next
# --------------------------------------------------------------------------
def test_a_third_cure_attempt_on_the_same_list_is_refused_at_the_ceiling():
    """Two cures are permitted on one list and the third is refused, with the window re-anchored on every review.

    PRD: "Resubmission is only possible from `DEFICIENT`, only while the logical clock is at or before `cure_deadline_at` — later is `ERR_CURE_WINDOW_EXPIRED` — and only while `resubmission_count` is still below its ceiling of 2, since a third cure attempt is refused with `ERR_RESUBMISSION_LIMIT_EXCEEDED`."

    Design: Corner/cross_cutting_complexity_layers/the_cure_resubmission_counter_is_per_list_and_resets_on_replacement
    """
    state = _list_returned_for_cure_twice()
    voter_list_id = state["voter_list_id"]

    filed = state["filed"]
    assert_voter_list(filed)
    assert filed["status"] == "SUBMITTED"
    assert filed["total_entry_count"] == 4
    assert filed["complete_entry_count"] == 3
    assert round(float(filed["completeness_pct"]), 2) == 75.00
    assert filed["list_grade"] == "MATERIAL_DEFECT"
    assert filed["is_late"] is False
    assert filed["resubmission_count"] == 0

    first_review, second_review, third_review = state["reviews"]
    for review in (first_review, second_review, third_review):
        assert review["status"] == "DEFICIENT"
        assert review["cure_window_hours"] == 24
        assert_instant_equals(
            review["cure_deadline_at"], plus_hours(review["reviewed_at"], 24),
            "voter_list.cure_deadline_at",
        )
    assert_instant_equals(first_review["cure_deadline_at"], "2026-08-22T10:00:00Z")
    assert_instant_equals(second_review["cure_deadline_at"], "2026-08-22T12:00:00Z")
    assert_instant_equals(third_review["cure_deadline_at"], "2026-08-22T14:00:00Z")

    first_cure, second_cure = state["cures"]
    assert first_cure["status"] == "SUBMITTED"
    assert first_cure["resubmission_count"] == 1
    assert_instant_equals(first_cure["submitted_at"], "2026-08-21T12:00:00Z")
    assert round(float(first_cure["completeness_pct"]), 2) == 75.00
    assert first_cure["list_grade"] == "MATERIAL_DEFECT"
    assert second_cure["resubmission_count"] == 2
    assert_instant_equals(second_cure["submitted_at"], "2026-08-21T14:00:00Z")

    refused = api_client.resubmit_voter_list(
        voter_list_id, {"attested_by_title": "Director of Labor Relations"}, DIRECTOR
    )
    validate_error(refused, ApiErrorId.ERR_RESUBMISSION_LIMIT_EXCEEDED)

    unchanged = read_voter_list(voter_list_id)
    assert unchanged["status"] == "DEFICIENT"
    assert unchanged["resubmission_count"] == 2
    assert_instant_equals(unchanged["submitted_at"], "2026-08-21T14:00:00Z")


def test_a_replacement_list_supersedes_the_exhausted_one_and_starts_its_own_counter_at_zero():
    """Opening a fresh list retires the exhausted one with its cure window on the record and begins with no cures used.

    PRD: "any list on the same case that is still `DRAFT` or `DEFICIENT`, moving each to the terminal `SUPERSEDED` state where it keeps its entries and its `cure_deadline_at` for the record but can never be submitted again."

    Design: Corner/cross_cutting_complexity_layers/the_cure_resubmission_counter_is_per_list_and_resets_on_replacement
    """
    state = _list_returned_for_cure_twice()
    ctx = state["ctx"]
    petition_id = ctx["petition"]["id"]
    exhausted_id = state["voter_list_id"]
    exhausted_before = read_voter_list(exhausted_id)
    assert exhausted_before["resubmission_count"] == 2

    replacement = create_voter_list(petition_id, ctx["agreement"]["id"])
    assert_voter_list(replacement)
    assert replacement["status"] == "DRAFT"
    assert replacement["resubmission_count"] == 0, (
        "the cure counter belongs to one list, not to the case"
    )
    assert replacement["total_entry_count"] == 0
    assert replacement["cure_deadline_at"] is None
    assert_instant_equals(
        replacement["due_at"], add_business_days("2026-08-20", 2), "voter_list.due_at"
    )

    retired = read_voter_list(exhausted_id)
    assert retired["status"] == "SUPERSEDED"
    assert retired["resubmission_count"] == 2
    assert retired["total_entry_count"] == 4
    assert_instant_equals(
        retired["cure_deadline_at"], exhausted_before["cure_deadline_at"],
        "voter_list.cure_deadline_at",
    )

    listing = api_client.list_voter_lists(
        BOARD, params={"petition_id": petition_id, "status": "SUPERSEDED"}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == exhausted_id

    refused = api_client.resubmit_voter_list(
        exhausted_id, {"attested_by_title": "Director of Labor Relations"}, DIRECTOR
    )
    validate_error(refused, ApiErrorId.ERR_VOTER_LIST_STATUS_INVALID)


# --------------------------------------------------------------------------
# Every write hands back its own recomputed figures
# --------------------------------------------------------------------------
def _round_with_all_challenges_resolved():
    """A posted tally whose three disputed ballots have all been dispositioned."""
    ctx = _case_at_polls_closed_with_three_open_challenges()
    set_clock("2026-09-02T12:00:00Z")
    ctx["posted"] = validate_success(api_client.post_tally(ctx["round"]["id"], BOARD))
    first, second, third = ctx["ballots"]
    resolve_ballot(first["id"], resolution="COUNTED_FOR")
    resolve_ballot(second["id"], resolution="COUNTED_FOR")
    resolve_ballot(third["id"], resolution="VOIDED")
    ctx["round"] = read_round(ctx["round"]["id"])
    return ctx


def test_posting_the_tally_returns_the_summed_figures_and_the_objection_deadline_in_its_own_body():
    """The posting response already carries the summed provisional counts, the derived threshold and the window it just opened.

    PRD: "A response body likewise reflects its own cascade: an operation that recomputes derived fields on the row it returns returns the recomputed values, not the pre-write ones."

    Design: Corner/consistency_model/each_write_returns_its_own_recomputed_derived_fields_with_no_second_read
    """
    ctx = _case_at_polls_closed_with_three_open_challenges()
    set_clock("2026-09-02T12:00:00Z")

    posted = validate_success(api_client.post_tally(ctx["round"]["id"], BOARD))
    assert_election_round(posted)
    assert posted["status"] == "TALLY_POSTED"
    assert posted["provisional_votes_for"] == 42
    assert posted["provisional_votes_against"] == 39
    assert posted["provisional_void_count"] == 1
    assert posted["provisional_margin"] == 3
    assert posted["valid_votes_cast"] == 81
    assert round(float(posted["majority_threshold"]), 2) == 41.00
    assert posted["ballots_cast_total"] == 85
    assert posted["challenged_open_count"] == 3
    assert posted["determinative_challenges"] is True
    assert posted["closed_session_count"] == 2
    assert posted["scheduled_session_count"] == 0
    assert_ballot_conservation(posted)
    assert_instant_equals(
        posted["tally_posted_at"], "2026-09-02T12:00:00Z", "election_round.tally_posted_at"
    )
    assert_instant_equals(
        posted["objection_window_close_at"], add_business_days("2026-09-02", 7),
        "election_round.objection_window_close_at",
    )

    petition = read_petition(ctx["petition"]["id"])
    assert petition["case_status"] == "TALLY_POSTED"

    listing = api_client.list_election_rounds(
        BOARD, params={"petition_id": ctx["petition"]["id"]}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "TALLY_POSTED"
    assert rows[0]["valid_votes_cast"] == 81
    assert rows[0]["ballots_cast_total"] == 85


def test_each_challenge_resolution_is_visible_on_the_very_next_read_of_the_round():
    """Every disposition moves one ballot out of the open bucket and into its own, with the box total untouched.

    PRD: "Every resolution stamps `resolved_at`, lowers the round's `challenged_open_count` by 1, and raises exactly one of `challenged_counted_for_count`, `challenged_counted_against_count`, `challenged_voided_count` or `challenged_withdrawn_count` by 1."

    Design: Corner/consistency_model/each_write_returns_its_own_recomputed_derived_fields_with_no_second_read
    """
    ctx = _case_at_polls_closed_with_three_open_challenges()
    set_clock("2026-09-02T12:00:00Z")
    validate_success(api_client.post_tally(ctx["round"]["id"], BOARD))
    round_id = ctx["round"]["id"]
    first, second, third = ctx["ballots"]

    resolved = resolve_ballot(first["id"], resolution="COUNTED_FOR")
    assert resolved["resolution"] == "COUNTED_FOR"
    assert_instant_equals(resolved["resolved_at"], "2026-09-02T12:00:00Z", "ballot.resolved_at")

    after_first = read_round(round_id)
    assert after_first["challenged_open_count"] == 2
    assert after_first["challenged_counted_for_count"] == 1
    assert after_first["ballots_cast_total"] == 85
    assert_ballot_conservation(after_first)

    still_open = api_client.list_challenged_ballots(
        BOARD, params={"poll_session_id": ctx["sessions"][0]["id"], "resolution": "OPEN"}
    )
    rows, meta = validate_paginated(still_open)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == second["id"]

    resolve_ballot(second["id"], resolution="COUNTED_FOR")
    resolve_ballot(third["id"], resolution="VOIDED")

    after_all = read_round(round_id)
    assert after_all["challenged_open_count"] == 0
    assert after_all["challenged_counted_for_count"] == 2
    assert after_all["challenged_voided_count"] == 1
    assert after_all["challenged_counted_against_count"] == 0
    assert after_all["challenged_withdrawn_count"] == 0
    assert after_all["ballots_cast_total"] == 85
    assert_ballot_conservation(after_all)


def test_revising_the_tally_returns_the_folded_in_counts_and_the_recomputed_threshold():
    """The revision response carries the folded-in challenge counts, the new base and the threshold recomputed from it.

    PRD: "`revised_margin` is the revised votes for less the revised votes against, `valid_votes_cast` is recomputed as the revised votes for plus the revised votes against, and `majority_threshold` is recomputed from that new base by the same halve-discard-add-one rule."

    Design: Corner/consistency_model/each_write_returns_its_own_recomputed_derived_fields_with_no_second_read
    """
    ctx = _round_with_all_challenges_resolved()
    posted = ctx["posted"]

    revised = validate_success(api_client.revise_tally(ctx["round"]["id"], BOARD))
    assert_election_round(revised)
    assert revised["status"] == "TALLY_REVISED"
    assert revised["revised_votes_for"] == 44
    assert revised["revised_votes_against"] == 39
    assert revised["revised_void_count"] == 2
    assert revised["revised_margin"] == 5
    assert revised["valid_votes_cast"] == 83
    assert round(float(revised["majority_threshold"]), 2) == 42.00
    assert revised["ballots_cast_total"] == 85
    assert revised["determinative_challenges"] is True, (
        "the determinative finding is historical and keeps its provisional value"
    )
    assert_instant_equals(
        revised["tally_revised_at"], "2026-09-02T12:00:00Z", "election_round.tally_revised_at"
    )
    assert_instants_equal(
        revised["objection_window_close_at"], posted["objection_window_close_at"],
        "election_round.objection_window_close_at",
    )
    assert_ballot_conservation(revised)

    reread = read_round(ctx["round"]["id"])
    assert reread["status"] == "TALLY_REVISED"
    assert reread["revised_votes_for"] == 44
    assert round(float(reread["majority_threshold"]), 2) == 42.00


def test_certifying_the_result_returns_the_whole_bargaining_timeline_in_its_own_body():
    """The certification response carries the outcome, the duty-to-bargain start and the insulated year it just computed.

    PRD: "When the union prevailed, `certification_outcome` becomes `CERTIFICATION_OF_REPRESENTATIVE`; `bargaining_obligation_start_at` equals `certified_at`, because the duty to bargain begins immediately; `certification_year_end_at` is `certified_at` plus 365 days, the insulated certification year; `decert_window_open_at` equals `certification_year_end_at`, since a decertification petition may only be filed once that year closes; and `election_bar_end_at` and `bargaining_obligation_end_at` are both left absent."

    Design: Corner/consistency_model/each_write_returns_its_own_recomputed_derived_fields_with_no_second_read
    """
    ctx = _round_with_all_challenges_resolved()
    round_id = ctx["round"]["id"]
    validate_success(api_client.revise_tally(round_id, BOARD))
    set_clock("2026-09-15T09:00:00Z")

    certified = validate_success(api_client.certify_petition(
        ctx["petition"]["id"], {"election_round_id": round_id}, BOARD
    ))
    assert_petition(certified)
    assert certified["case_status"] == "CERTIFIED"
    assert certified["certification_outcome"] == "CERTIFICATION_OF_REPRESENTATIVE"
    assert certified["certified_round_id"] == round_id
    assert_instant_equals(
        certified["certified_at"], "2026-09-15T09:00:00Z", "petition.certified_at"
    )
    assert_instants_equal(
        certified["bargaining_obligation_start_at"], certified["certified_at"],
        "petition.bargaining_obligation_start_at",
    )
    assert_instant_equals(
        certified["certification_year_end_at"], plus_days(certified["certified_at"], 365),
        "petition.certification_year_end_at",
    )
    assert_instant_equals(
        certified["certification_year_end_at"], "2027-09-15T09:00:00Z",
        "petition.certification_year_end_at",
    )
    assert_instants_equal(
        certified["decert_window_open_at"], certified["certification_year_end_at"],
        "petition.decert_window_open_at",
    )
    assert certified["election_bar_end_at"] is None
    assert certified["bargaining_obligation_end_at"] is None

    assert read_round(round_id)["status"] == "ROUND_CERTIFIED"
    listing = api_client.list_petitions(BOARD, params={"case_status": "CERTIFIED"})
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == ctx["petition"]["id"]
    assert rows[0]["certification_outcome"] == "CERTIFICATION_OF_REPRESENTATIVE"


# --------------------------------------------------------------------------
# A decertifying finding: three hops settled inside the one request
# --------------------------------------------------------------------------
def test_a_substantiated_finding_is_visible_three_hops_away_in_the_same_instant():
    """Recording the finding decertifies the presenter, blocks their approved meeting and flags the case for retraining at once.

    PRD: "Second, because the presenter has lost certification, every campaign communication naming this supervisor in `presenter_supervisor_id` whose `status` is `PENDING_LEGAL_REVIEW` or `APPROVED` becomes `BLOCKED` with `blocked_reason` set to `PRESENTER_DECERTIFIED`."

    Design: Corner/consistency_model/a_three_hop_cascade_is_visible_to_every_reader_in_the_same_instant
    """
    ctx = _case_with_trained_presenter_and_approved_meeting()
    petition_id = ctx["petition"]["id"]
    supervisor_id = ctx["supervisor"]["id"]
    assert ctx["message"]["status"] == "APPROVED"
    assert read_petition(petition_id)["retraining_required"] is False

    decertified = record_violation(supervisor_id, "INTERROGATION", True)
    assert_supervisor(decertified)
    assert decertified["training_status"] == "UNTRAINED"
    assert decertified["violation_count"] == 1
    assert decertified["last_violation_code"] == "INTERROGATION"
    assert decertified["certified_at"] is None
    assert decertified["training_attempt_count"] == 1

    blocked = read_campaign_message(ctx["message"]["id"])
    assert_campaign_communication(blocked)
    assert blocked["status"] == "BLOCKED"
    assert blocked["blocked_reason"] == "PRESENTER_DECERTIFIED"

    petition = read_petition(petition_id)
    assert_petition(petition)
    assert petition["retraining_required"] is True

    trained_listing = api_client.list_supervisors(
        TRAINER, params={"petition_id": petition_id, "training_status": "TRAINED"}
    )
    _, trained_meta = validate_paginated(trained_listing)
    assert trained_meta["total_count"] == 0

    untrained_listing = api_client.list_supervisors(
        TRAINER, params={"petition_id": petition_id, "training_status": "UNTRAINED"}
    )
    untrained_rows, untrained_meta = validate_paginated(untrained_listing)
    assert untrained_meta["total_count"] == 1
    assert untrained_rows[0]["id"] == supervisor_id

    blocked_listing = api_client.list_campaign_communications(
        DIRECTOR, params={"petition_id": petition_id, "status": "BLOCKED"}
    )
    blocked_rows, blocked_meta = validate_paginated(blocked_listing)
    assert blocked_meta["total_count"] == 1
    assert blocked_rows[0]["id"] == ctx["message"]["id"]
    assert blocked_rows[0]["blocked_reason"] == "PRESENTER_DECERTIFIED"


def test_training_the_presenter_again_recertifies_them_without_releasing_the_blocked_message():
    """A second qualifying attempt restores certification, and the message blocked for decertification stays blocked.

    PRD: "A qualifying attempt increments `training_attempt_count`, records the score and the modules, stamps `certified_at` with the logical clock, and moves `training_status` from `UNTRAINED` to `TRAINED`."

    PRD: "`RERUN_BLACKOUT`, `PRESENTER_DECERTIFIED` and `CASE_DISMISSED` are permanent for that row."

    Design: Corner/consistency_model/a_three_hop_cascade_is_visible_to_every_reader_in_the_same_instant
    """
    ctx = _case_with_trained_presenter_and_approved_meeting()
    petition_id = ctx["petition"]["id"]
    supervisor_id = ctx["supervisor"]["id"]
    record_violation(supervisor_id, "INTERROGATION", True)
    set_clock("2026-08-25T09:00:00Z")

    recertified = train_supervisor(supervisor_id, quiz_score=92)
    assert_supervisor(recertified)
    assert recertified["training_status"] == "TRAINED"
    assert recertified["training_attempt_count"] == 2
    assert recertified["quiz_score"] == 92
    assert recertified["violation_count"] == 1
    assert recertified["last_violation_code"] == "INTERROGATION"
    assert_instant_equals(
        recertified["certified_at"], "2026-08-25T09:00:00Z", "supervisor.certified_at"
    )

    still_blocked = read_campaign_message(ctx["message"]["id"])
    assert still_blocked["status"] == "BLOCKED"
    assert still_blocked["blocked_reason"] == "PRESENTER_DECERTIFIED"

    trained_listing = api_client.list_supervisors(
        TRAINER, params={"petition_id": petition_id, "training_status": "TRAINED"}
    )
    trained_rows, trained_meta = validate_paginated(trained_listing)
    assert trained_meta["total_count"] == 1
    assert trained_rows[0]["id"] == supervisor_id
