"""Two occupancy rules over the same intervals, with deliberately unequal arithmetic.

A room demands a clear turnover gap of at least its buffer, while a faculty
member's calendar is compared as half-open intervals with no buffer at all.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_instant
from test_helpers.factories import create_defense_event_payload
from test_helpers.test_users import TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]


def _announced_defense_plus_second_candidate() -> dict:
    """One announced 14:00-16:00 defense and a second candidate ready to book."""
    world = fx.setup_announced_defense(thesis_overrides={"title": "First Occupation"})
    world["other"] = fx.add_second_candidate_pipeline(world, title="Second Occupation")
    return world


def _book(world: dict, room: dict, start: str, end: str):
    """Attempt the second candidate's booking and return the raw response."""
    other = world["other"]
    return fx.api_client.create_defense_event(
        create_defense_event_payload(
            other["thesis"]["id"], room["id"], scheduled_start=start, scheduled_end=end
        ),
        other["student_headers"],
    )


def test_room_gap_one_minute_short_of_the_buffer_conflicts(api: ApiClient) -> None:
    """A 16:29 start leaves 29 minutes after a 16:00 finish and is refused.

    PRD §3.4: "Concretely, the new occupation conflicts with an existing one when the new start is earlier than the existing end advanced by the buffer **and** the existing start is earlier than the new end advanced by the buffer."

    Design: Difficulty/resource_temporal_overlap/room_buffer_boundary_29_versus_30_minute_gap
    """
    world = _announced_defense_plus_second_candidate()

    validate_error(
        _book(world, world["room"], "2026-09-25T16:29:00Z", "2026-09-25T18:29:00Z"),
        "ERR_ROOM_BOOKING_CONFLICT",
        409,
    )

    room = get_success_data(api.get_defense_room(world["room"]["id"], REGISTRAR))
    assert room["booked_minutes_total"] == 120

    thesis = get_success_data(
        api.get_thesis(world["other"]["thesis"]["id"], REGISTRAR)
    )
    assert thesis["workflow_state"] == "COMMITTEE_APPROVED"


def test_room_gap_of_exactly_the_buffer_is_accepted(api: ApiClient) -> None:
    """A 16:30 start leaves exactly the thirty-minute turnover and is accepted.

    PRD §3.4: "A gap of exactly the buffer is therefore legal, while a gap one minute shorter conflicts; a conflict is `ERR_ROOM_BOOKING_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/room_buffer_boundary_29_versus_30_minute_gap
    """
    world = _announced_defense_plus_second_candidate()
    validate_error(
        _book(world, world["room"], "2026-09-25T16:29:00Z", "2026-09-25T18:29:00Z"),
        "ERR_ROOM_BOOKING_CONFLICT",
        409,
    )

    event = get_success_data(
        _book(world, world["room"], "2026-09-25T16:30:00Z", "2026-09-25T18:30:00Z"),
        201,
    )
    assert event["status"] == "DRAFT"
    assert_instant(
        event["scheduled_start"], "2026-09-25T16:30:00Z", "scheduled_start"
    )

    room = get_success_data(api.get_defense_room(world["room"]["id"], REGISTRAR))
    assert room["booked_minutes_total"] == 240

    thesis = get_success_data(
        api.get_thesis(world["other"]["thesis"]["id"], REGISTRAR)
    )
    assert thesis["workflow_state"] == "DEFENSE_SCHEDULED"

    first_event = get_success_data(
        api.get_defense_event(world["defense_event"]["id"], REGISTRAR)
    )
    assert first_event["status"] == "ANNOUNCED"


def _two_rooms_and_a_shared_chair() -> dict:
    """The same chair sits on both committees, and a second room stands empty."""
    world = _announced_defense_plus_second_candidate()
    world["second_room"] = fx.add_defense_room(
        world,
        code="R102",
        building="Graduate Hall",
        seat_capacity=30,
        turnover_buffer_minutes=30,
    )
    return world


def test_faculty_intervals_overlapping_by_one_minute_are_refused(
    api: ApiClient,
) -> None:
    """A 15:59 start in the free room still overlaps the chair's 16:00 finish.

    PRD §3.4: "Those intervals are treated as half-open with no buffer at all: a conflict exists when the new start is earlier than the existing end **and** the existing start is earlier than the new end."

    Design: Difficulty/resource_temporal_overlap/faculty_half_open_adjacency_allowed_but_overlap_rejected
    """
    world = _two_rooms_and_a_shared_chair()

    error = validate_error(
        _book(
            world,
            world["second_room"],
            "2026-09-25T15:59:00Z",
            "2026-09-25T17:59:00Z",
        ),
        "ERR_FACULTY_SCHEDULE_CONFLICT",
        409,
    )
    assert error["error_id"] != "ERR_ROOM_BOOKING_CONFLICT"

    second_room = get_success_data(
        api.get_defense_room(world["second_room"]["id"], REGISTRAR)
    )
    assert second_room["booked_minutes_total"] == 0

    thesis = get_success_data(
        api.get_thesis(world["other"]["thesis"]["id"], REGISTRAR)
    )
    assert thesis["workflow_state"] == "COMMITTEE_APPROVED"


def test_faculty_intervals_that_merely_touch_are_accepted(api: ApiClient) -> None:
    """A 16:00 start in the free room touches the chair's 16:00 finish and is legal.

    PRD §3.4: "Exact adjacency is consequently legal — a faculty member may finish one defense at eleven o'clock and begin another at eleven o'clock — whereas the same pair of intervals in the same room would violate the buffered room rule."

    Design: Difficulty/resource_temporal_overlap/faculty_half_open_adjacency_allowed_but_overlap_rejected
    """
    world = _two_rooms_and_a_shared_chair()
    validate_error(
        _book(
            world,
            world["second_room"],
            "2026-09-25T15:59:00Z",
            "2026-09-25T17:59:00Z",
        ),
        "ERR_FACULTY_SCHEDULE_CONFLICT",
        409,
    )

    event = get_success_data(
        _book(
            world,
            world["second_room"],
            "2026-09-25T16:00:00Z",
            "2026-09-25T18:00:00Z",
        ),
        201,
    )
    assert event["status"] == "DRAFT"
    assert event["room_id"] == world["second_room"]["id"]

    second_room = get_success_data(
        api.get_defense_room(world["second_room"]["id"], REGISTRAR)
    )
    assert second_room["booked_minutes_total"] == 120
    first_room = get_success_data(api.get_defense_room(world["room"]["id"], REGISTRAR))
    assert first_room["booked_minutes_total"] == 120

    thesis = get_success_data(
        api.get_thesis(world["other"]["thesis"]["id"], REGISTRAR)
    )
    assert thesis["workflow_state"] == "DEFENSE_SCHEDULED"
