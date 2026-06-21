"""Reading-room (aggregate-capacity, half-open) and review-station (closed + buffer) bookings.

Difficulty queue: resource_temporal_overlap. Corner queue: reading-room concurrent under capacity.
"""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId, fixtures


# ─────────────────────────────────────────────────────
# Difficulty/resource_temporal_overlap/reading_room_aggregate_capacity_half_open
# ─────────────────────────────────────────────────────
def test_reading_room_overlap_at_capacity_rejected(api):
    """PRD §3.9: "The new booking is rejected when, at some instant it covers, the count of
    existing bookings already active there is at or above capacity — that is, the room is
    already full at some instant the new booking would occupy. Such a rejection carries
    `ERR_ROOM_AT_CAPACITY`."

    Design: Difficulty/resource_temporal_overlap/reading_room_aggregate_capacity_half_open
    """
    ctx = fixtures.setup_reading_room_with_booking(
        capacity=1, starts_at="2026-03-02T10:00:00.000Z", ends_at="2026-03-02T11:00:00.000Z"
    )
    resp = api.create_reading_room_booking(
        ctx["room"]["id"],
        {"request_id": ctx["request"]["id"],
         "starts_at": "2026-03-02T10:30:00.000Z", "ends_at": "2026-03-02T11:30:00.000Z"},
        ctx["officer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_ROOM_AT_CAPACITY.value)


def test_reading_room_touching_endpoint_accepted(api):
    """PRD §3.9: "Because the intervals are half-open, two bookings that merely touch at an
    endpoint (one ending exactly when the next begins) never conflict, so adjacency is always
    permitted regardless of capacity."

    Design: Difficulty/resource_temporal_overlap/reading_room_aggregate_capacity_half_open
    """
    ctx = fixtures.setup_reading_room_with_booking(
        capacity=1, starts_at="2026-03-02T10:00:00.000Z", ends_at="2026-03-02T11:00:00.000Z"
    )
    # New booking starts exactly when the existing one ends.
    booking = validate_success(api.create_reading_room_booking(
        ctx["room"]["id"],
        {"request_id": ctx["request"]["id"],
         "starts_at": "2026-03-02T11:00:00.000Z", "ends_at": "2026-03-02T12:00:00.000Z"},
        ctx["officer_headers"],
    ), expected_status=201)
    assert booking["room_id"] == ctx["room"]["id"], booking


# ─────────────────────────────────────────────────────
# Difficulty/resource_temporal_overlap/review_station_closed_interval_buffer
# ─────────────────────────────────────────────────────
def test_review_station_touching_within_buffer_rejected(api):
    """PRD §3.9: "Unlike the reading room, here adjacency is rejected: when two closed
    intervals merely touch at an endpoint they share that instant, and a non-negative buffer
    demands a gap, so a booking that begins exactly when another ends conflicts."
    PRD §3.9: "The rejection carries `ERR_STATION_BUFFER_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/review_station_closed_interval_buffer
    """
    ctx = fixtures.setup_review_station_with_booking(
        buffer_minutes=15, starts_at="2026-03-02T13:00:00.000Z", ends_at="2026-03-02T14:00:00.000Z"
    )
    # New booking starts exactly when the existing one ends -> within the 15-min buffer.
    resp = api.create_review_station_booking(
        ctx["station"]["id"],
        {"request_id": ctx["request"]["id"],
         "starts_at": "2026-03-02T14:00:00.000Z", "ends_at": "2026-03-02T15:00:00.000Z"},
        ctx["officer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_STATION_BUFFER_CONFLICT.value)


def test_review_station_beyond_buffer_accepted(api):
    """PRD §3.9: "A new booking is rejected when it falls within the station's buffer of any
    existing booking on it — concretely, when the new start is at or before an existing
    booking's end plus the buffer minutes and that existing booking's start is at or before
    the new end plus the buffer minutes."

    A booking starting well beyond the buffer (16+ minutes after the prior end) is accepted.

    Design: Difficulty/resource_temporal_overlap/review_station_closed_interval_buffer
    """
    ctx = fixtures.setup_review_station_with_booking(
        buffer_minutes=15, starts_at="2026-03-02T13:00:00.000Z", ends_at="2026-03-02T14:00:00.000Z"
    )
    # Prior ends 14:00; buffer 15 min; start at 14:16 is strictly beyond end+buffer (14:15).
    booking = validate_success(api.create_review_station_booking(
        ctx["station"]["id"],
        {"request_id": ctx["request"]["id"],
         "starts_at": "2026-03-02T14:16:00.000Z", "ends_at": "2026-03-02T15:00:00.000Z"},
        ctx["officer_headers"],
    ), expected_status=201)
    assert booking["station_id"] == ctx["station"]["id"], booking


# ─────────────────────────────────────────────────────
# Corner/cross_cutting_complexity_layers/reading_room_concurrent_under_capacity_accepted
# ─────────────────────────────────────────────────────
def test_reading_room_concurrent_under_capacity_accepted(api):
    """PRD §3.9: "at any instant covered by the proposed booking, the count of existing
    bookings on that room whose half-open interval contains that instant must stay below the
    room's capacity."

    With capacity 2 and one existing booking, an overlapping second booking is accepted (1 < 2).

    Design: Corner/cross_cutting_complexity_layers/reading_room_concurrent_under_capacity_accepted
    """
    ctx = fixtures.setup_reading_room_with_booking(
        capacity=2, starts_at="2026-03-02T10:00:00.000Z", ends_at="2026-03-02T11:00:00.000Z"
    )
    booking = validate_success(api.create_reading_room_booking(
        ctx["room"]["id"],
        {"request_id": ctx["request"]["id"],
         "starts_at": "2026-03-02T10:30:00.000Z", "ends_at": "2026-03-02T11:30:00.000Z"},
        ctx["officer_headers"],
    ), expected_status=201)
    assert booking["room_id"] == ctx["room"]["id"], booking
