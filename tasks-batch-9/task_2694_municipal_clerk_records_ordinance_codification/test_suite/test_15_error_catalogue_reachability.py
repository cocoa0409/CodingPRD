"""The first half of the error catalogue, reached one code at a time: the two
authentication refusals, the thirteen distinct not-found codes, the state codes of
nine different aggregates, the three cycle gates, and the two tally refusals.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client, assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    CITY_CLERK,
    CODIFICATION_EDITOR,
    CODIFICATION_EDITOR_ALT,
    DEPUTY_CLERK,
    NO_AUTH_HEADERS,
    PRESIDING_OFFICER,
    RECORDS_OFFICER,
    UNKNOWN_ROLE_HEADERS,
)

VENUE_BODY = {"name": "Council Chamber", "address": "1 Civic Plaza", "capacity": 120}


def test_a_missing_header_pair_and_an_unrecognised_role_are_both_refused_at_the_door():
    """Both bodies would have registered a room; neither request gets far enough for
    that to matter, and the two refusals are told apart by their error ids.

    PRD 2.1: "If either header is absent, the request is rejected with
    `ERR_MISSING_AUTH_HEADERS` (HTTP 401) before anything else about the request is
    examined. If `X-User-Role` carries a value that is not one of the seven role
    names defined below, the rejection is `ERR_UNKNOWN_ROLE`, also HTTP 401."

    Design: Corner/errors/calls_missing_auth_headers_or_naming_an_invalid_role_are_rejected
    """
    unauthenticated = api_client.create_venue(VENUE_BODY, NO_AUTH_HEADERS)
    unknown_role = api_client.create_venue(VENUE_BODY, UNKNOWN_ROLE_HEADERS)

    validate_error(unauthenticated, ApiErrorId.MISSING_AUTH_HEADERS.value, 401)
    validate_error(unknown_role, ApiErrorId.UNKNOWN_ROLE.value, 401)


def test_thirteen_reads_of_one_unissued_identifier_answer_with_thirteen_codes():
    """The catalogue does not collapse onto a single generic not-found: each read
    names the entity of the collection it was addressed to.

    PRD 2.6: "A path segment naming a numbering series resolves against
    `NumberSeries` and reports `ERR_NUMBER_SERIES_NOT_FOUND`; a path segment naming a
    retention series resolves against `RecordSeries` and reports
    `ERR_SERIES_NOT_FOUND`."

    Design: Corner/errors/every_remaining_entity_read_returns_its_own_not_found_error_id
    """
    reads = (
        (api_client.get_venue(NON_EXISTENT_UUID, CITY_CLERK), ApiErrorId.VENUE_NOT_FOUND),
        (
            api_client.get_agenda_item(NON_EXISTENT_UUID, CITY_CLERK),
            ApiErrorId.AGENDA_ITEM_NOT_FOUND,
        ),
        (api_client.get_motion(NON_EXISTENT_UUID, CITY_CLERK), ApiErrorId.MOTION_NOT_FOUND),
        (
            api_client.get_minutes(NON_EXISTENT_UUID, CITY_CLERK),
            ApiErrorId.MINUTES_NOT_FOUND,
        ),
        (
            api_client.get_number_series(NON_EXISTENT_UUID, CITY_CLERK),
            ApiErrorId.NUMBER_SERIES_NOT_FOUND,
        ),
        (
            api_client.get_instrument(NON_EXISTENT_UUID, CITY_CLERK),
            ApiErrorId.INSTRUMENT_NOT_FOUND,
        ),
        (
            api_client.get_publication_notice(NON_EXISTENT_UUID, CITY_CLERK),
            ApiErrorId.NOTICE_NOT_FOUND,
        ),
        (
            api_client.get_code_title(NON_EXISTENT_UUID, CODIFICATION_EDITOR),
            ApiErrorId.CODE_TITLE_NOT_FOUND,
        ),
        (
            api_client.get_supplement_cycle(NON_EXISTENT_UUID, CODIFICATION_EDITOR),
            ApiErrorId.CYCLE_NOT_FOUND,
        ),
        (
            api_client.get_codification_submission(
                NON_EXISTENT_UUID, CODIFICATION_EDITOR
            ),
            ApiErrorId.SUBMISSION_NOT_FOUND,
        ),
        (
            api_client.get_records_request(NON_EXISTENT_UUID, CITY_CLERK),
            ApiErrorId.REQUEST_NOT_FOUND,
        ),
        (
            api_client.get_record_series(NON_EXISTENT_UUID, RECORDS_OFFICER),
            ApiErrorId.SERIES_NOT_FOUND,
        ),
        (
            api_client.get_destruction_batch(NON_EXISTENT_UUID, RECORDS_OFFICER),
            ApiErrorId.BATCH_NOT_FOUND,
        ),
    )

    seen = []
    for response, expected in reads:
        body = validate_error(response, expected.value, 404)
        seen.append(body["error_id"])

    assert len(set(seen)) == 13, f"expected thirteen distinct codes, got {seen}"


def test_four_replays_off_one_sitting_answer_with_four_different_state_codes():
    """Each of the four aggregates has already travelled the edge being replayed, and
    each answers with its own code while leaving its own record untouched.

    PRD 2.11: "Only then does the service consider state: first whether the target
    entity is in a state from which the requested transition is declared — reported as
    `ERR_INVALID_MEETING_STATE`, `ERR_INVALID_PACKET_STATE`,
    `ERR_INVALID_MOTION_STATE`, `ERR_INVALID_MINUTES_STATE`,
    `ERR_INVALID_INSTRUMENT_STATE`, `ERR_INVALID_NOTICE_STATE`,
    `ERR_INVALID_SUBMISSION_STATE`, `ERR_INVALID_BATCH_STATE` or
    `ERR_INVALID_REQUEST_STATE`, all HTTP 409 — and then the cross-entity state
    guards, the closability check on a records request, and segregation of duties."

    Design: Corner/errors/repeating_a_meeting_side_action_cannot_bypass_the_packet_motion_instrument_or_notice_state
    """
    number_series = fx.create_number_series()
    ctx = fx.noticed_meeting(item_types=["ORDINANCE_FIRST_READING"])
    notice_id = ctx["agenda_notice"]["id"]
    fx.ordered_notice(notice_id, ["2026-09-14"], column_inches=20.0)
    validate_success(
        api_client.convene_meeting(
            ctx["meeting"]["id"], f.convene_payload(5), PRESIDING_OFFICER
        )
    )
    instrument = fx.introduced_ordinance_at_first_reading(
        ctx["meeting"]["id"], number_series["id"]
    )
    motion = fx.record_motion(ctx["meeting"]["id"])
    fx.tally(motion["id"], 3, 2)

    packet_replay = api_client.post_agenda_packet(ctx["packet"]["id"], CITY_CLERK)
    motion_replay = api_client.tally_motion(
        motion["id"], f.tally_payload(4, 1), CITY_CLERK
    )
    instrument_replay = api_client.advance_reading(
        instrument["id"], f.advance_reading_payload(ctx["meeting"]["id"]), CITY_CLERK
    )
    notice_replay = api_client.order_publication(
        notice_id,
        f.publication_order_payload(
            ["2026-09-13"], column_inches=30.0, affidavit_required=True
        ),
        CITY_CLERK,
    )

    validate_error(packet_replay, ApiErrorId.INVALID_PACKET_STATE.value, 409)
    validate_error(motion_replay, ApiErrorId.INVALID_MOTION_STATE.value, 409)
    validate_error(instrument_replay, ApiErrorId.INVALID_INSTRUMENT_STATE.value, 409)
    validate_error(notice_replay, ApiErrorId.INVALID_NOTICE_STATE.value, 409)
    a.assert_status(fx.read_packet(ctx["packet"]["id"]), "POSTED")
    a.assert_fields(fx.read_motion(motion["id"]), status="TALLIED", yes_count=3)
    a.assert_fields(
        fx.read_instrument(instrument["id"]),
        status="FIRST_READING_PASSED",
        reading_count=1,
    )
    a.assert_fields(fx.read_notice(notice_id), status="ORDERED", column_inches=20.0)


def test_three_unrelated_aggregates_each_refuse_the_action_their_state_forbids():
    """A batch that was never certified, a file already open for review and a
    submission whose cycle was never locked each answer with their own state code —
    and the submission's own state is reported ahead of its cycle's.

    PRD 2.11: "Only then does the service consider state: first whether the target
    entity is in a state from which the requested transition is declared — reported as
    `ERR_INVALID_MEETING_STATE`, `ERR_INVALID_PACKET_STATE`,
    `ERR_INVALID_MOTION_STATE`, `ERR_INVALID_MINUTES_STATE`,
    `ERR_INVALID_INSTRUMENT_STATE`, `ERR_INVALID_NOTICE_STATE`,
    `ERR_INVALID_SUBMISSION_STATE`, `ERR_INVALID_BATCH_STATE` or
    `ERR_INVALID_REQUEST_STATE`, all HTTP 409 — and then the cross-entity state
    guards, the closability check on a records request, and segregation of duties."

    Design: Corner/errors/batch_request_and_submission_replays_cannot_bypass_their_own_state_errors
    """
    series = fx.series_eligible_for_destruction(
        40, "2019-06-15", retention_years=0, series_code="CC-05",
        name="Routine correspondence",
    )
    batch = fx.proposed_destruction_batch(series["id"], 10, "2019-06-15")
    request = fx.request_under_review(
        subject_description="Routine correspondence 2019"
    )
    number_series = fx.create_number_series()
    pair = fx.code_title_with_open_cycle()
    instrument = fx.create_code_amendment(
        number_series["id"], pair["code_title"]["id"], "12.04.030",
        title="Amending 12.04.030",
    )
    submission = fx.file_submission(
        pair["cycle"]["id"], instrument["id"], pair["code_title"]["id"], "12.04.030"
    )

    batch_replay = api_client.rescind_destruction_batch(
        batch["id"], f.rescind_batch_payload(rescind_reason="Filed in error"),
        RECORDS_OFFICER,
    )
    request_replay = api_client.begin_review(request["id"], CITY_CLERK)
    submission_replay = api_client.decide_submission(
        submission["id"], f.decide_payload("ACCEPT"), CODIFICATION_EDITOR
    )

    validate_error(batch_replay, ApiErrorId.INVALID_BATCH_STATE.value, 409)
    validate_error(request_replay, ApiErrorId.INVALID_REQUEST_STATE.value, 409)
    body = validate_error(
        submission_replay, ApiErrorId.INVALID_SUBMISSION_STATE.value, 409
    )
    assert body["error_id"] != ApiErrorId.CYCLE_NOT_LOCKED.value
    standing_batch = fx.read_batch(batch["id"])
    a.assert_status(standing_batch, "PROPOSED")
    a.assert_nulls(standing_batch, "rescind_reason")
    a.assert_fields(
        fx.read_records_request(request["id"]), fulfillment_status="UNDER_REVIEW"
    )
    a.assert_status(fx.read_submission(submission["id"]), "PENDING")


def test_one_cycle_produces_all_three_of_its_gate_refusals_in_turn():
    """Certification before the lock, a filing after it, and certification while the
    lone submission is still in review are three different refusals on one cycle.

    PRD 3.7: "The cycle must be `LOCKED`." and "Deciding is available only from
    `IN_REVIEW` and only while the parent cycle is `LOCKED`; a cycle in the wrong state
    reports `ERR_CYCLE_NOT_LOCKED` (HTTP 409) and a submission in the wrong state
    reports `ERR_INVALID_SUBMISSION_STATE`." and "no submission may still be `PENDING`
    or `IN_REVIEW`, or the attempt is `ERR_CYCLE_HAS_OPEN_SUBMISSIONS` (HTTP 409)"

    Design: Corner/errors/the_cycle_gate_errors_are_all_reachable_across_the_open_locked_boundary
    """
    number_series = fx.create_number_series()
    pair = fx.code_title_with_open_cycle()
    title_id = pair["code_title"]["id"]
    cycle_id = pair["cycle"]["id"]
    first = fx.create_code_amendment(
        number_series["id"], title_id, "12.04.030", title="Amending 12.04.030"
    )
    second = fx.create_code_amendment(
        number_series["id"], title_id, "12.04.040", title="Adding 12.04.040",
        full_text_length=1200,
    )
    filed = fx.file_submission(cycle_id, first["id"], title_id, "12.04.030")

    too_early = api_client.certify_supplement_cycle(
        cycle_id, f.certify_cycle_payload("2026-09-30"), CODIFICATION_EDITOR_ALT
    )
    locked = validate_success(
        api_client.lock_supplement_cycle(cycle_id, CODIFICATION_EDITOR)
    )
    too_late = api_client.create_codification_submission(
        f.codification_submission_payload(
            cycle_id, second["id"], fx.code_title_version(title_id), "12.04.040", "ADD"
        ),
        CODIFICATION_EDITOR,
    )
    still_open = api_client.certify_supplement_cycle(
        cycle_id, f.certify_cycle_payload("2026-09-30"), CODIFICATION_EDITOR_ALT
    )

    validate_error(too_early, ApiErrorId.CYCLE_NOT_LOCKED.value, 409)
    a.assert_status(locked, "LOCKED")
    validate_error(too_late, ApiErrorId.CYCLE_NOT_OPEN.value, 409)
    validate_error(still_open, ApiErrorId.CYCLE_HAS_OPEN_SUBMISSIONS.value, 409)
    cycle = fx.read_cycle(cycle_id)
    a.assert_fields(cycle, status="LOCKED", submission_count=1, conflict_count=0)
    a.assert_nulls(cycle, "certified_on")
    a.assert_status(fx.read_submission(filed["id"]), "IN_REVIEW")
    title = fx.read_code_title(title_id)
    a.assert_fields(title, current_supplement_number=0)
    a.assert_section_refs(title, [])


def test_a_tally_that_does_not_account_for_the_room_is_refused_twice_over():
    """Four votes in a room of five is unaccounted attendance, and a room where
    everybody recuses leaves nobody to carry the motion; the empty base is reported
    even though those counts do add up.

    PRD 3.3: "The four counts must together account for exactly the meeting's
    `present_member_count`; any other sum is `ERR_VOTE_TALLY_MISMATCH` (HTTP 422)."
    and "And at least one present member must remain unrecused: if `recused_count`
    equals `present_member_count`, so that nobody is eligible to vote, the tally is
    refused with `ERR_NO_VOTING_MEMBERS` (HTTP 422)."

    Design: Corner/errors/a_tally_that_does_not_account_for_the_room_is_rejected
    """
    ctx = fx.in_session_meeting(5, ["REPORT"])
    motion = fx.record_motion(ctx["meeting"]["id"], headers=DEPUTY_CLERK)

    short_sum = api_client.tally_motion(
        motion["id"], f.tally_payload(3, 1), CITY_CLERK
    )
    all_recused = api_client.tally_motion(
        motion["id"], f.tally_payload(0, 0, 0, 5), CITY_CLERK
    )

    validate_error(short_sum, ApiErrorId.VOTE_TALLY_MISMATCH.value, 422)
    validate_error(all_recused, ApiErrorId.NO_VOTING_MEMBERS.value, 422)
    standing = fx.read_motion(motion["id"])
    a.assert_fields(standing, status="SECONDED", outcome="PENDING")
    a.assert_nulls(standing, "effective_base", "required_yes")
