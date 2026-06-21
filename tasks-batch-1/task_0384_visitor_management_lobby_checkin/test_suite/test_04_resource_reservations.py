"""Meeting-room and parking-space reservation interval semantics.

Difficulty queue (A): resource_temporal_overlap.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_site_floor_host,
    create_meeting_room, create_parking_space, create_visit,
    TEST_USERS,
)

LA = TEST_USERS["lobby_attendant_headers"]


def test_meeting_room_adjacent_booking_allowed(api):
    """PRD 3.3: "When a `room_id` is supplied at pre-registration, the booking
    interval runs from `scheduled_start` up to but not including `scheduled_end` — a
    half-open interval. The booking is rejected with `ERR_ROOM_CONFLICT` (HTTP 409) if
    it overlaps any existing booking on that same room; two intervals that merely
    touch at an endpoint (one ending exactly when the next begins) are adjacent, not
    overlapping, and are permitted with zero buffer."

    Visit A books 09:00-10:00; Visit B booking 10:00-11:00 touches the endpoint and is
    permitted (PREREGISTERED, room booked).

    Design: Difficulty/resource_temporal_overlap/rto_meeting_room_halfopen_adjacency_allowed
    """
    site, floor, host = setup_site_floor_host()
    room = create_meeting_room(floor["id"], name="Room 1", seats=6)
    create_visit(
        site["id"], host["id"], floor["id"], room_id=room["id"],
        visitor_full_name="Visitor A", visitor_company="ACo",
        scheduled_start="2026-06-16T09:00:00Z", scheduled_end="2026-06-16T10:00:00Z",
    )
    res = api.create_visit(
        {
            "site_id": site["id"], "host_id": host["id"], "floor_id": floor["id"],
            "room_id": room["id"], "visitor_full_name": "Visitor B",
            "visitor_company": "BCo",
            "scheduled_start": "2026-06-16T10:00:00Z",
            "scheduled_end": "2026-06-16T11:00:00Z", "id_scanned": True,
        },
        LA,
    )
    visit_b = validate_success(res, 201)
    assert visit_b["status"] == "PREREGISTERED", (
        f"expected PREREGISTERED, got {visit_b['status']}"
    )
    assert visit_b["room_id"] == room["id"], (
        f"expected room_id {room['id']}, got {visit_b['room_id']}"
    )


def test_parking_adjacent_reservation_rejected_by_buffer(api):
    """PRD 3.3: "When a `parking_space_id` is supplied, the reservation is held to a
    stricter standard: it must keep a gap of at least fifteen minutes from every
    existing reservation on that bay, treated as a closed interval extended by that
    cleaning buffer on each side. Two parking reservations that merely touch
    end-to-end are *not* allowed, because they violate the fifteen-minute cleaning
    gap; a violation is rejected with `ERR_PARKING_CONFLICT` (HTTP 409)."

    Visit A reserves 09:00-10:00; Visit B reserving 10:00-11:00 touches end-to-end and
    is rejected — opposite adjacency behaviour from the meeting room.

    Design: Difficulty/resource_temporal_overlap/rto_parking_closed_buffer_adjacency_rejected
    """
    site, floor, host = setup_site_floor_host()
    space = create_parking_space(site["id"], bay_label="P12")
    create_visit(
        site["id"], host["id"], floor["id"], parking_space_id=space["id"],
        visitor_full_name="Visitor A", visitor_company="ACo",
        scheduled_start="2026-06-16T09:00:00Z", scheduled_end="2026-06-16T10:00:00Z",
    )
    res = api.create_visit(
        {
            "site_id": site["id"], "host_id": host["id"], "floor_id": floor["id"],
            "parking_space_id": space["id"], "visitor_full_name": "Visitor B",
            "visitor_company": "BCo",
            "scheduled_start": "2026-06-16T10:00:00Z",
            "scheduled_end": "2026-06-16T11:00:00Z", "id_scanned": True,
        },
        LA,
    )
    validate_error(res, ApiErrorId.ERR_PARKING_CONFLICT)


def test_meeting_room_overlapping_booking_rejected(api):
    """PRD 3.3: "The booking is rejected with `ERR_ROOM_CONFLICT` (HTTP 409) if it
    overlaps any existing booking on that same room; two intervals that merely touch
    at an endpoint (one ending exactly when the next begins) are adjacent, not
    overlapping, and are permitted with zero buffer."

    The rejection side of the half-open rule: Visit B booking 09:30-10:30 overlaps the
    existing 09:00-10:00 booking and is rejected.

    Design: Difficulty/resource_temporal_overlap/rto_meeting_room_halfopen_adjacency_allowed
    """
    site, floor, host = setup_site_floor_host()
    room = create_meeting_room(floor["id"], name="Room 1", seats=6)
    create_visit(
        site["id"], host["id"], floor["id"], room_id=room["id"],
        visitor_full_name="Visitor A", visitor_company="ACo",
        scheduled_start="2026-06-16T09:00:00Z", scheduled_end="2026-06-16T10:00:00Z",
    )
    res = api.create_visit(
        {
            "site_id": site["id"], "host_id": host["id"], "floor_id": floor["id"],
            "room_id": room["id"], "visitor_full_name": "Visitor B",
            "visitor_company": "BCo",
            "scheduled_start": "2026-06-16T09:30:00Z",
            "scheduled_end": "2026-06-16T10:30:00Z", "id_scanned": True,
        },
        LA,
    )
    validate_error(res, ApiErrorId.ERR_ROOM_CONFLICT)


def test_parking_well_separated_reservation_allowed(api):
    """PRD 3.3: "When a `parking_space_id` is supplied, the reservation is held to a
    stricter standard: it must keep a gap of at least fifteen minutes from every
    existing reservation on that bay, treated as a closed interval extended by that
    cleaning buffer on each side."

    Complement of the buffer rejection: Visit B reserving 11:00-12:00 keeps a 60-minute
    gap after the first reservation ends at 10:00, well beyond the 15-minute cleaning
    buffer, so it is allowed (PREREGISTERED, bay reserved).

    Design: Difficulty/resource_temporal_overlap/rto_parking_closed_buffer_adjacency_rejected
    """
    site, floor, host = setup_site_floor_host()
    space = create_parking_space(site["id"], bay_label="P12")
    create_visit(
        site["id"], host["id"], floor["id"], parking_space_id=space["id"],
        visitor_full_name="Visitor A", visitor_company="ACo",
        scheduled_start="2026-06-16T09:00:00Z", scheduled_end="2026-06-16T10:00:00Z",
    )
    res = api.create_visit(
        {
            "site_id": site["id"], "host_id": host["id"], "floor_id": floor["id"],
            "parking_space_id": space["id"], "visitor_full_name": "Visitor B",
            "visitor_company": "BCo",
            "scheduled_start": "2026-06-16T11:00:00Z",
            "scheduled_end": "2026-06-16T12:00:00Z", "id_scanned": True,
        },
        LA,
    )
    visit_b = validate_success(res, 201)
    assert visit_b["status"] == "PREREGISTERED", (
        f"expected PREREGISTERED, got {visit_b['status']}"
    )
    assert visit_b["parking_space_id"] == space["id"]
