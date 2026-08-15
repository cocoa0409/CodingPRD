"""Green-room booking: aggregate capacity boundary, half-open adjacency,
the logical-clock past check, and accessibility room enforcement.
"""
import pytest
from datetime import datetime

from test_helpers import (
    ApiErrorId,
    assert_green_room_booking,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers.factories import create_green_room_booking_payload
from test_helpers.test_users import TEST_USERS

LEAD = TEST_USERS["contest_lead_headers"]


def test_green_room_aggregate_capacity_boundary(api):
    """PRD §3.9: "Counting the new request against existing `BOOKED` bookings in the same room, the request is rejected with `ERR_GREEN_ROOM_FULL` when the resulting overlap count would reach 4; stated at the boundary, exactly four simultaneously overlapping bookings are legal, and the fifth overlapping request is the one rejected."
    PRD §3.9: "Two bookings overlap when neither ends on or before the other's start — equivalently, adjacency where one booking's `end_at` equals the other's `start_at` does not count as an overlap."

    Four NORTH bookings 12:00-13:00 exist; the fifth fully-overlapping one is
    rejected, and the half-open-adjacent one at 13:00 is legal. The logical
    clock is at its default 2026-08-01, so August bookings are in the future.

    Design: Difficulty/resource_temporal_overlap/green_room_aggregate_capacity_boundary
    """
    contest = fx.create_contest()
    contestants = [fx.create_contestant(full_name=f"C {i + 1}") for i in range(5)]
    for contestant in contestants[:4]:
        booking = fx.create_green_room_booking(
            contestant, contest["id"], room_name="NORTH",
            start_at="2026-08-15T12:00:00Z", end_at="2026-08-15T13:00:00Z",
        )
        assert booking["status"] == "BOOKED"

    c5 = contestants[4]
    resp_full = api.create_green_room_booking(
        create_green_room_booking_payload(
            c5["id"], contest["id"], room_name="NORTH",
            start_at="2026-08-15T12:00:00Z", end_at="2026-08-15T13:00:00Z"),
        fx.contestant_headers(c5),
    )
    validate_error(resp_full, ApiErrorId.ERR_GREEN_ROOM_FULL)

    resp_adjacent = api.create_green_room_booking(
        create_green_room_booking_payload(
            c5["id"], contest["id"], room_name="NORTH",
            start_at="2026-08-15T13:00:00Z", end_at="2026-08-15T14:00:00Z"),
        fx.contestant_headers(c5),
    )
    adjacent = validate_success(resp_adjacent, 201)
    assert_green_room_booking(adjacent)
    assert adjacent["status"] == "BOOKED"


def test_green_room_capacity_counts_only_booked_and_same_room(api):
    """PRD §3.9: "Counting the new request against existing `BOOKED` bookings in the same room, the request is rejected with `ERR_GREEN_ROOM_FULL` when the resulting overlap count would reach 4; stated at the boundary, exactly four simultaneously overlapping bookings are legal, and the fifth overlapping request is the one rejected."
    PRD §3.9: "A booking is born `BOOKED`; the owning contestant may cancel it, moving it to the terminal `CANCELLED` state, and a contest-level cancellation cascade cancels every `BOOKED` booking of the contest as described in §2.9."

    Capacity is per room (a SOUTH booking does not count against NORTH) and a
    CANCELLED booking frees its share of the room's capacity.

    Design: Difficulty/resource_temporal_overlap/green_room_aggregate_capacity_boundary
    """
    contest = fx.create_contest()
    contestants = [fx.create_contestant(full_name=f"C {i + 1}") for i in range(6)]
    bookings = [
        fx.create_green_room_booking(
            contestants[i], contest["id"], room_name="NORTH",
            start_at="2026-08-15T12:00:00Z", end_at="2026-08-15T13:00:00Z")
        for i in range(4)
    ]

    # A fully overlapping booking in another room is legal.
    other_room = fx.create_green_room_booking(
        contestants[4], contest["id"], room_name="SOUTH",
        start_at="2026-08-15T12:00:00Z", end_at="2026-08-15T13:00:00Z",
    )
    assert other_room["status"] == "BOOKED"

    # Cancelling one NORTH booking frees capacity for the next overlapping one.
    validate_success(
        api.cancel_green_room_booking(
            bookings[0]["id"], fx.contestant_headers(contestants[0]))
    )
    assert (fx.get_contest(contest["id"])  # contest untouched by booking ops
            ["status"] == "SETUP")
    freed = fx.create_green_room_booking(
        contestants[5], contest["id"], room_name="NORTH",
        start_at="2026-08-15T12:00:00Z", end_at="2026-08-15T13:00:00Z",
    )
    assert freed["status"] == "BOOKED"


def test_green_room_booking_in_past_rejected(api):
    """PRD §2.7: "Before any operator call sets it, the logical clock is exactly `2026-08-01T00:00:00Z`; the server must never fall back to wall-clock time. A contest-lead-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant."
    PRD §3.9: "The window may not begin in the past relative to the logical clock of §2.7, otherwise `ERR_BOOKING_IN_PAST` (HTTP 422)."

    With the logical clock at 2026-08-15T10:00:00Z, a 09:00 booking is in the
    past.

    Design: Corner/validations/green_room_booking_in_past_returns_422
    """
    contest = fx.create_contest()
    contestant = fx.create_contestant()
    current = fx.set_logical_clock("2026-08-15T10:00:00Z")
    # PRD §2.7 pins the instant the clock advances to, not the response
    # string's serialization; compare instants.
    assert datetime.fromisoformat(current) == datetime.fromisoformat(
        "2026-08-15T10:00:00Z"
    )

    resp = api.create_green_room_booking(
        create_green_room_booking_payload(
            contestant["id"], contest["id"], room_name="NORTH",
            start_at="2026-08-15T09:00:00Z", end_at="2026-08-15T09:30:00Z"),
        fx.contestant_headers(contestant),
    )
    validate_error(resp, ApiErrorId.ERR_BOOKING_IN_PAST)


def test_accessibility_setup_requires_equipped_room(api):
    """PRD §3.9: "Accessibility is enforced structurally: only `EAST` is accessibility-equipped, so a request with `requires_accessibility_setup` true and any other `room_name` is rejected with `ERR_GREEN_ROOM_INACCESSIBLE` (HTTP 422)."

    The default logical clock (2026-08-01) makes these August windows future.

    Design: Corner/validations/accessibility_requires_equipped_room
    """
    contest = fx.create_contest()
    contestant = fx.create_contestant()

    resp_north = api.create_green_room_booking(
        create_green_room_booking_payload(
            contestant["id"], contest["id"], room_name="NORTH",
            requires_accessibility_setup=True),
        fx.contestant_headers(contestant),
    )
    validate_error(resp_north, ApiErrorId.ERR_GREEN_ROOM_INACCESSIBLE)

    resp_east = api.create_green_room_booking(
        create_green_room_booking_payload(
            contestant["id"], contest["id"], room_name="EAST",
            requires_accessibility_setup=True),
        fx.contestant_headers(contestant),
    )
    booking = validate_success(resp_east, 201)
    assert_green_room_booking(booking)
    assert booking["status"] == "BOOKED"
    assert booking["requires_accessibility_setup"] is True
