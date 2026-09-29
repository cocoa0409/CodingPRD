"""Two scarce resources with deliberately different interval arithmetic: the room, whose
occupancy is buffered on both trailing edges, and the proctor, whose calendar is half-open
with no buffer at all.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import assert_exam_session
from test_helpers.test_users import make_center_administrator_headers
from test_helpers.types import CenterDecision, ProctorCertificationStatus, SessionStatus, Subtest

EXISTING_SITTING = ("2026-08-15T09:00:00Z", "2026-08-15T11:00:00Z")
GAP_ONE_MINUTE_SHORT = ("2026-08-15T11:44:00Z", "2026-08-15T13:44:00Z")
GAP_EXACTLY_THE_BUFFER = ("2026-08-15T11:45:00Z", "2026-08-15T13:45:00Z")
GAP_BEFORE_THE_EXISTING_SITTING = ("2026-08-15T06:15:00Z", "2026-08-15T08:15:00Z")

FIRST_PROCTOR_SITTING = ("2026-08-18T09:00:00Z", "2026-08-18T11:00:00Z")
ADJACENT_PROCTOR_SITTING = ("2026-08-18T11:00:00Z", "2026-08-18T13:00:00Z")
OVERLAPPING_PROCTOR_SITTING = ("2026-08-18T10:30:00Z", "2026-08-18T12:30:00Z")


def _setup_room_with_one_occupying_sitting():
    """A 45-minute room holding a single DRAFT sitting from 09:00 to 11:00."""
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Buffer Center", state_code="OH"
    )
    room = fixtures.create_room(
        center["id"], room_code="R1", seat_capacity=10, turnaround_buffer_minutes=45
    )
    existing = fixtures.create_session(
        center["id"],
        room["id"],
        EXISTING_SITTING[0],
        EXISTING_SITTING[1],
        subtest=Subtest.MATH,
        requested_seats=6,
    )
    return {
        "center_id": center["id"],
        "room_id": room["id"],
        "existing_id": existing["id"],
    }


def _schedule(center_id, room_id, window, subtest):
    return api_client.create_exam_session(
        factories.create_exam_session_payload(
            room_id, window[0], window[1], subtest=subtest, requested_seats=6
        ),
        headers=make_center_administrator_headers(center_id),
    )


def _sittings_in_room(center_id, room_id):
    return fixtures.list_all(
        api_client.list_exam_sessions,
        make_center_administrator_headers(center_id),
        testing_room_id=room_id,
    )


def _setup_three_rooms_and_one_proctor():
    """Three sittings on one date, each in its own room, all still DRAFT."""
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Adjacency Center", state_code="OH"
    )
    rooms = [
        fixtures.create_room(
            center["id"], room_code=code, seat_capacity=6, turnaround_buffer_minutes=45
        )
        for code in ("R1", "R2", "R3")
    ]
    proctor = fixtures.create_certified_proctor(
        center["id"],
        certification_expires_at="2027-01-01T00:00:00Z",
        full_name="Yara Proctor",
        daily_hour_cap=8.00,
    )
    windows = (FIRST_PROCTOR_SITTING, ADJACENT_PROCTOR_SITTING, OVERLAPPING_PROCTOR_SITTING)
    subtests = (Subtest.MATH, Subtest.RLA, Subtest.SCIENCE)
    sessions = [
        fixtures.create_session(
            center["id"],
            room["id"],
            window[0],
            window[1],
            subtest=subtest,
            requested_seats=5,
        )
        for room, window, subtest in zip(rooms, windows, subtests)
    ]
    return {
        "center_id": center["id"],
        "proctor_id": proctor["id"],
        "sessions": sessions,
    }


def _assign(center_id, session_id, proctor_id):
    return api_client.assign_proctor(
        session_id,
        factories.proctor_assignment_payload(proctor_id),
        headers=make_center_administrator_headers(center_id),
    )


def test_01_a_gap_one_minute_short_of_the_buffer_is_refused():
    """"The comparisons are strict, so two sittings separated by a gap of exactly the buffer
    are accepted while a gap one minute shorter is refused with `ERR_ROOM_BUFFER_CONFLICT`.
    The sittings compared are every non-cancelled one in the same room — those whose
    `status` is `DRAFT`, `SCHEDULED`, `IN_PROGRESS` or `COMPLETED`."

    Design: Difficulty/resource_temporal_overlap/room_session_buffer_gap_45min_boundary
    """
    context = _setup_room_with_one_occupying_sitting()

    response = _schedule(
        context["center_id"], context["room_id"], GAP_ONE_MINUTE_SHORT, Subtest.RLA
    )
    validate_error(response, ApiErrorId.ROOM_BUFFER_CONFLICT, expected_status=409)

    # The refused candidate left nothing behind: only the occupying sitting remains.
    sittings = _sittings_in_room(context["center_id"], context["room_id"])
    assert [sitting["id"] for sitting in sittings] == [context["existing_id"]]


def test_02_a_gap_of_exactly_the_buffer_is_accepted():
    """"The room's `turnaround_buffer_minutes` is added to the trailing edge of *both* the
    candidate sitting and each existing one, and a conflict exists when the candidate begins
    before an existing sitting's buffered end and that existing sitting begins before the
    candidate's buffered end." and "Its `duration_hours` is the span from `starts_at` to
    `ends_at` expressed in hours to two decimal places, rounded half up."

    Design: Difficulty/resource_temporal_overlap/room_session_buffer_gap_45min_boundary
    """
    context = _setup_room_with_one_occupying_sitting()

    accepted = validate_success(
        _schedule(
            context["center_id"], context["room_id"], GAP_EXACTLY_THE_BUFFER, Subtest.RLA
        ),
        expected_status=201,
    )
    assert_exam_session(accepted)
    assert accepted["status"] == SessionStatus.DRAFT
    assert float(accepted["duration_hours"]) == 2.00
    assert accepted["starts_at"] == GAP_EXACTLY_THE_BUFFER[0]

    sittings = _sittings_in_room(context["center_id"], context["room_id"])
    assert len(sittings) == 2


def test_03_the_buffer_is_applied_on_the_candidates_own_trailing_edge_too():
    """"**Room turnaround** is what "free" means here, and it is deliberately generous on
    both sides." and "The comparisons are strict, so two sittings separated by a gap of
    exactly the buffer are accepted while a gap one minute shorter is refused with
    `ERR_ROOM_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/room_session_buffer_gap_45min_boundary
    """
    context = _setup_room_with_one_occupying_sitting()

    # This candidate ends 45 minutes before the existing sitting begins, so the buffer is
    # measured off the candidate's trailing edge rather than the existing sitting's.
    earlier = validate_success(
        _schedule(
            context["center_id"],
            context["room_id"],
            GAP_BEFORE_THE_EXISTING_SITTING,
            Subtest.SCIENCE,
        ),
        expected_status=201,
    )
    assert earlier["status"] == SessionStatus.DRAFT
    assert float(earlier["duration_hours"]) == 2.00

    later = validate_success(
        _schedule(
            context["center_id"], context["room_id"], GAP_EXACTLY_THE_BUFFER, Subtest.RLA
        ),
        expected_status=201,
    )

    sittings = _sittings_in_room(context["center_id"], context["room_id"])
    assert sorted(sitting["id"] for sitting in sittings) == sorted(
        [context["existing_id"], earlier["id"], later["id"]]
    )


def test_04_back_to_back_supervision_is_legal_for_the_proctor():
    """"Back-to-back supervision is therefore legal — a sitting starting at exactly the
    instant another ends is accepted — while any genuine overlap is refused with
    `ERR_PROCTOR_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/proctor_adjacent_sessions_allowed_but_overlap_rejected
    """
    context = _setup_three_rooms_and_one_proctor()
    proctor_id = context["proctor_id"]

    first = validate_success(
        _assign(context["center_id"], context["sessions"][0]["id"], proctor_id)
    )
    assert first["status"] == SessionStatus.SCHEDULED
    assert first["proctor_id"] == proctor_id

    adjacent = validate_success(
        _assign(context["center_id"], context["sessions"][1]["id"], proctor_id)
    )
    assert adjacent["status"] == SessionStatus.SCHEDULED
    assert adjacent["starts_at"] == first["ends_at"]

    proctor = fixtures.read_proctor(proctor_id)
    assert proctor["certification_status"] == ProctorCertificationStatus.CERTIFIED
    assert proctor["assigned_session_count"] == 2


def test_05_a_genuine_overlap_in_a_third_room_is_refused_before_the_daily_cap():
    """"**Interval conflict** treats a proctor's committed sittings as half-open intervals
    with **zero** buffer: a conflict exists when the candidate sitting begins before an
    existing one ends and that existing one begins before the candidate ends, comparing
    strictly on both sides." and "Bands 34 and 35 are two separate gates on the same
    operation and the interval conflict reports first."

    Design: Difficulty/resource_temporal_overlap/proctor_adjacent_sessions_allowed_but_overlap_rejected
    """
    context = _setup_three_rooms_and_one_proctor()
    proctor_id = context["proctor_id"]

    fixtures.assign_session_proctor(
        context["center_id"], context["sessions"][0]["id"], proctor_id
    )
    fixtures.assign_session_proctor(
        context["center_id"], context["sessions"][1]["id"], proctor_id
    )

    overlapping_id = context["sessions"][2]["id"]
    # The projected daily load is 6.00 hours against a cap of 8.00, so only the interval
    # gate can answer here.
    response = _assign(context["center_id"], overlapping_id, proctor_id)
    validate_error(response, ApiErrorId.PROCTOR_TIME_CONFLICT, expected_status=409)

    refused = fixtures.read_session(overlapping_id)
    assert refused["status"] == SessionStatus.DRAFT
    assert refused["proctor_id"] is None
    assert fixtures.read_proctor(proctor_id)["assigned_session_count"] == 2
