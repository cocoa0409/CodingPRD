"""Contested resources: a buffered room widens on both sides, a person carries no buffer."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_rounded, assert_values


def _buffered_room_with_morning_session(api):
    """A room buffered by 15 minutes holding a SCHEDULED 10:00-11:00 session."""
    program = fx.create_program(api, name="Bingo", domain="COGNITIVE")
    room = fx.create_room(api, name="Buffered Hall", capacity=10, buffer_minutes=15)
    session = fx.create_session(
        api,
        program["id"],
        room["id"],
        starts_at="2026-08-10T10:00:00Z",
        ends_at="2026-08-10T11:00:00Z",
    )
    return program, room, session


def test_room_buffer_widens_interval_on_both_sides(api, director):
    """An 11:10 candidate is widened back to 10:55 and so still collides with the existing
    session's own widened span, which reaches 11:15.

    PRD: "The candidate session's half-open interval is widened by the room's
    `buffer_minutes` on **both** sides, and the widened interval must not intersect the
    interval of any other session in the same room whose `status` is `SCHEDULED`,
    `IN_PROGRESS`, or `DOCUMENTED`."

    Design: Difficulty/resource_temporal_overlap/room_buffer_widens_interval_on_both_sides
    """
    program, room, session = _buffered_room_with_morning_session(api)

    response = api.create_session(
        f.session_payload(
            program["id"],
            room["id"],
            starts_at="2026-08-10T11:10:00Z",
            ends_at="2026-08-10T12:10:00Z",
        ),
        director,
    )
    validate_error(response, ApiErrorId.ROOM_TIME_CONFLICT, 409)
    assert_values(fx.read_session(api, session["id"]), status="SCHEDULED")


def test_room_buffer_widens_interval_on_both_sides_boundary_touch_admitted(api, director):
    """Five minutes later the candidate's widened span begins exactly where the incumbent's
    widened span ends, and a half-open interval that only touches does not intersect.

    PRD: "in a room with `buffer_minutes` at 0, a session starting at the exact instant
    another ends is legal, while in a room with `buffer_minutes` at 15 the same pair of
    slots is not."

    Design: Difficulty/resource_temporal_overlap/room_buffer_widens_interval_on_both_sides
    """
    program, room, session = _buffered_room_with_morning_session(api)

    response = api.create_session(
        f.session_payload(
            program["id"],
            room["id"],
            starts_at="2026-08-10T11:15:00Z",
            ends_at="2026-08-10T12:15:00Z",
        ),
        director,
    )
    created = validate_success(response, 201)
    assert_values(created, status="SCHEDULED")
    assert_values(fx.read_session(api, session["id"]), status="SCHEDULED")


def _volunteer_with_one_morning_assignment(api):
    """A CLEARED volunteer proposed on a 10:00-12:00 session, plus a back-to-back slot and
    a straddling slot in a second unbuffered room."""
    fx.advance_clock(api, "2026-08-05T08:00:00Z")
    program = fx.create_program(
        api,
        name="Pet Visit",
        domain="SOCIAL",
        max_supervision_tier="TIER_2",
        volunteer_eligible=True,
        required_screening_level="BASIC",
    )
    east = fx.create_room(api, name="Lounge East", capacity=10, buffer_minutes=0)
    west = fx.create_room(api, name="Lounge West", capacity=10, buffer_minutes=0)
    first = fx.create_session(
        api, program["id"], east["id"],
        starts_at="2026-08-06T10:00:00Z", ends_at="2026-08-06T12:00:00Z",
    )
    adjacent = fx.create_session(
        api, program["id"], east["id"],
        starts_at="2026-08-06T12:00:00Z", ends_at="2026-08-06T14:00:00Z",
    )
    straddling = fx.create_session(
        api, program["id"], west["id"],
        starts_at="2026-08-06T11:00:00Z", ends_at="2026-08-06T13:00:00Z",
    )
    volunteer = fx.cleared_volunteer(api, full_name="Grace Lindqvist")
    fx.assign_volunteer(api, volunteer["id"], first["id"], role_type="COMPANION")
    return volunteer, adjacent, straddling


def test_volunteer_double_booking_allows_back_to_back(api, coordinator):
    """A second assignment that starts exactly when the first ends is accepted, because a
    person carries no turnover buffer, and its two hours join the weekly commitment.

    PRD: "note that back-to-back sessions with zero gap are perfectly legal for
    volunteers, since there is no turnover buffer on people"

    Design: Difficulty/resource_temporal_overlap/volunteer_double_booking_allows_back_to_back
    """
    volunteer, adjacent, _ = _volunteer_with_one_morning_assignment(api)

    response = api.create_volunteer_assignment(
        f.assignment_payload(volunteer["id"], adjacent["id"], role_type="COMPANION"),
        coordinator,
    )
    created = validate_success(response, 201)
    assert_values(created, status="PROPOSED")
    assert_rounded(created["hours"], 2.0, 2)

    assert_rounded(fx.read_volunteer(api, volunteer["id"])["scheduled_hours_week"], 4.0, 2)


def test_volunteer_double_booking_allows_back_to_back_straddle_rejected(api, coordinator):
    """A third slot that genuinely overlaps both held sessions is refused as a volunteer
    conflict — not as an hour-cap breach, since six hours is still under the cap — and the
    weekly commitment is left where it was.

    PRD: "the target session's half-open interval must not intersect the interval of any
    other session on which the same volunteer already holds a `PROPOSED` or `CONFIRMED`
    assignment, because a volunteer is never double-booked, and a conflict reports
    `ERR_VOLUNTEER_TIME_CONFLICT`"

    Design: Difficulty/resource_temporal_overlap/volunteer_double_booking_allows_back_to_back
    """
    volunteer, adjacent, straddling = _volunteer_with_one_morning_assignment(api)
    fx.assign_volunteer(api, volunteer["id"], adjacent["id"], role_type="COMPANION")

    response = api.create_volunteer_assignment(
        f.assignment_payload(volunteer["id"], straddling["id"], role_type="COMPANION"),
        coordinator,
    )
    validate_error(response, ApiErrorId.VOLUNTEER_TIME_CONFLICT, 409)

    assert_rounded(fx.read_volunteer(api, volunteer["id"])["scheduled_hours_week"], 4.0, 2)
