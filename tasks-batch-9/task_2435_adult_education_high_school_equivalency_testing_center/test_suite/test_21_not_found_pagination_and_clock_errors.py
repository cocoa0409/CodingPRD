"""The error catalogue read directly: one unknown identifier swept across every path-scoped
entity, the two edges of the declared paging window, and the forward-only logical clock.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.constants import INITIAL_CLOCK
from test_helpers.test_users import (
    make_instructor_headers,
    make_program_coordinator_headers,
    make_registrar_headers,
    make_state_authority_headers,
)
from test_helpers.types import ProgramTrack

UNKNOWN_ID = "00000000-0000-0000-0000-0000000000ff"

FORWARD_INSTANT = "2026-08-20T12:00:00Z"
ONE_SECOND_EARLIER = "2026-08-20T11:59:59Z"
ONE_SECOND_LATER = "2026-08-20T12:00:01Z"


def _per_entity_reads():
    """The eleven single-record reads, paired with the code each must report."""
    authority = make_state_authority_headers()
    return (
        (api_client.get_testing_room(UNKNOWN_ID, headers=authority),
         ApiErrorId.TESTING_ROOM_NOT_FOUND),
        (api_client.get_proctor(UNKNOWN_ID, headers=authority),
         ApiErrorId.PROCTOR_NOT_FOUND),
        (api_client.get_attendance_entry(UNKNOWN_ID, headers=authority),
         ApiErrorId.ATTENDANCE_ENTRY_NOT_FOUND),
        (api_client.get_test_event(UNKNOWN_ID, headers=authority),
         ApiErrorId.TEST_EVENT_NOT_FOUND),
        (api_client.get_exam_session(UNKNOWN_ID, headers=authority),
         ApiErrorId.EXAM_SESSION_NOT_FOUND),
        (api_client.get_exam_registration(UNKNOWN_ID, headers=authority),
         ApiErrorId.EXAM_REGISTRATION_NOT_FOUND),
        (api_client.get_accommodation_request(UNKNOWN_ID, headers=authority),
         ApiErrorId.ACCOMMODATION_REQUEST_NOT_FOUND),
        (api_client.get_outcome_record(UNKNOWN_ID, headers=authority),
         ApiErrorId.OUTCOME_RECORD_NOT_FOUND),
        (api_client.get_credential(UNKNOWN_ID, headers=authority),
         ApiErrorId.CREDENTIAL_NOT_FOUND),
        (api_client.get_transcript_order(UNKNOWN_ID, headers=authority),
         ApiErrorId.TRANSCRIPT_ORDER_NOT_FOUND),
        (api_client.get_funding_period(UNKNOWN_ID, headers=authority),
         ApiErrorId.FUNDING_PERIOD_NOT_FOUND),
    )


def _two_learners():
    first = fixtures.create_student(
        full_name="Ana Bell", email="ana.bell@example.org", primary_track=ProgramTrack.LITERACY
    )
    second = fixtures.create_student(
        full_name="Ben Cole", email="ben.cole@example.org", primary_track=ProgramTrack.LITERACY
    )
    return first, second


def _list_students(**params):
    return api_client.list_students(headers=make_registrar_headers(), params=params or None)


def test_01_each_unknown_path_identifier_names_the_entity_it_addressed():
    """"Every identifier embedded in the path is resolved left to right, and the first one that
    does not resolve determines the 404 reported: `ERR_STUDENT_NOT_FOUND`,
    `ERR_TESTING_CENTER_NOT_FOUND`, `ERR_TESTING_ROOM_NOT_FOUND`, `ERR_PROCTOR_NOT_FOUND`"

    Design: Corner/errors/every_path_scoped_entity_id_is_not_found_when_unknown
    """
    for response, expected_error_id in _per_entity_reads():
        validate_error(response, expected_error_id, expected_status=404)


def test_02_an_empty_service_reports_its_default_clock_and_eleven_distinct_codes():
    """"Before any client sets it, the clock reads exactly `2026-08-01T00:00:00Z`; the server
    never falls back to real time, at startup or afterwards."

    Design: Corner/errors/every_path_scoped_entity_id_is_not_found_when_unknown
    """
    assert fixtures.read_clock() == INITIAL_CLOCK

    reported = [
        response.json()["data"]["error_id"] for response, _expected in _per_entity_reads()
    ]
    assert len(set(reported)) == 11

    assert fixtures.read_clock() == INITIAL_CLOCK


def test_03_a_window_outside_the_declared_range_is_refused():
    """"A `limit` outside the permitted range, or a negative `offset`, is rejected with
    `ERR_INVALID_PAGINATION` (400)." and "`limit` caps the number of records returned; it
    defaults to 10 when omitted, may be no smaller than 1 and no larger than 100."

    Design: Corner/errors/pagination_bounds_outside_the_declared_range_are_rejected
    """
    _two_learners()

    validate_error(
        _list_students(limit=0, offset=0), ApiErrorId.INVALID_PAGINATION, expected_status=400
    )
    validate_error(
        _list_students(limit=101, offset=0), ApiErrorId.INVALID_PAGINATION, expected_status=400
    )
    validate_error(
        _list_students(limit=10, offset=-1), ApiErrorId.INVALID_PAGINATION, expected_status=400
    )

    survivors, meta = validate_paginated(_list_students(limit=10, offset=0))
    assert meta["total_count"] == 2
    assert len(survivors) == 2


def test_04_both_ends_of_the_permitted_limit_are_inside_the_range():
    """"`total_count` is the number of records matching the filters before the pagination window
    is applied, and `has_more` states whether any matching record remains beyond the returned
    window."

    Design: Corner/errors/pagination_bounds_outside_the_declared_range_are_rejected
    """
    first, second = _two_learners()

    narrow, narrow_meta = validate_paginated(_list_students(limit=1, offset=0))
    assert len(narrow) == 1
    assert narrow_meta["total_count"] == 2
    assert narrow_meta["has_more"] is True

    wide, wide_meta = validate_paginated(_list_students(limit=100, offset=0))
    assert len(wide) == 2
    assert wide_meta["total_count"] == 2
    assert wide_meta["has_more"] is False
    assert {row["id"] for row in wide} == {first["id"], second["id"]}


def test_05_an_offset_past_the_end_is_an_empty_window_not_an_error():
    """"`offset` is the number of records to skip before the returned window begins; it defaults
    to 0 and may not be negative."

    Design: Corner/errors/pagination_bounds_outside_the_declared_range_are_rejected
    """
    _two_learners()

    beyond, beyond_meta = validate_paginated(_list_students(limit=10, offset=5))
    assert beyond == []
    assert beyond_meta["total_count"] == 2
    assert beyond_meta["has_more"] is False

    defaulted, default_meta = validate_paginated(_list_students())
    assert len(defaulted) == 2
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0
    assert default_meta["total_count"] == 2
    assert default_meta["has_more"] is False


def test_06_a_backward_step_is_refused_while_standing_still_is_allowed():
    """"The clock may only move forward. Setting it takes a `current_utc` instant, and a value
    earlier than the clock's current reading is rejected with `ERR_CLOCK_BACKWARD` (422); setting
    it to exactly the current reading is accepted."

    Design: Corner/errors/the_logical_clock_must_not_move_backward
    """
    assert fixtures.read_clock() == INITIAL_CLOCK
    assert fixtures.set_clock(FORWARD_INSTANT)["current_utc"] == FORWARD_INSTANT

    backward = api_client.set_clock(
        factories.clock_payload(ONE_SECOND_EARLIER), headers=make_state_authority_headers()
    )
    validate_error(backward, ApiErrorId.CLOCK_BACKWARD, expected_status=422)
    assert fixtures.read_clock() == FORWARD_INSTANT

    standing_still = validate_success(
        api_client.set_clock(
            factories.clock_payload(FORWARD_INSTANT), headers=make_state_authority_headers()
        )
    )
    assert standing_still["current_utc"] == FORWARD_INSTANT


def test_07_one_second_later_is_accepted_and_the_read_agrees_with_the_write():
    """"Both the write and the read of the clock return the resulting `current_utc` value."
    and "`StateAuthority`, `ProgramCoordinator`, `Registrar`, `CenterAdministrator` and
    `Instructor` may advance the clock; every role including `Proctor` and `Student` may read it."

    Design: Corner/errors/the_logical_clock_must_not_move_backward
    """
    fixtures.set_clock(FORWARD_INSTANT, headers=make_registrar_headers())

    advanced = validate_success(
        api_client.set_clock(
            factories.clock_payload(ONE_SECOND_LATER), headers=make_instructor_headers()
        )
    )
    assert advanced["current_utc"] == ONE_SECOND_LATER

    assert fixtures.read_clock(headers=make_program_coordinator_headers()) == ONE_SECOND_LATER
