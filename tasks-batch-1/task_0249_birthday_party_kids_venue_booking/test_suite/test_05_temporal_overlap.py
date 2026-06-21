"""Room and staff window overlap geometry: half-open room intervals (adjacency is
free) versus closed staff intervals (back-to-back adjacency conflicts).
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_config, create_venue, create_room, create_package, create_staff,
    create_quote_draft_booking, hold_booking, assign_staff, reset_clock_base,
)

COORD = "coordinator_headers"


# ─── Difficulty: resource_temporal_overlap / rto_room_half_open_buffer_overlap ─

def test_room_hold_inside_buffer_window_rejected(api, coordinator_headers):
    """PRD 3.7: "Two such occupancies conflict when the first starts strictly before
    the second's buffered end and the second starts strictly before the first's
    buffered end."

    Design: Difficulty/resource_temporal_overlap/rto_room_half_open_buffer_overlap
    """
    venue, room, package = setup_config(buffer_minutes=30, base_duration_minutes=120,
                                        max_capacity=20)
    a = create_quote_draft_booking(room["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T10:00:00Z")
    hold_booking(a["id"])  # occupies [10:00, 12:30)
    b = create_quote_draft_booking(room["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T12:15:00Z")  # inside buffer
    res = api.hold_booking(b["id"], coordinator_headers)
    validate_error(res, "ERR_ROOM_WINDOW_CONFLICT")
    booking = validate_success(api.get_booking(b["id"], coordinator_headers), 200)
    assert booking["status"] == "QUOTE_DRAFT"


def test_room_hold_adjacent_at_buffer_edge_accepted(api, coordinator_headers):
    """PRD 3.7: "Because the intervals are half-open, exact adjacency — one booking's
    buffered end equal to the next's start — is not a conflict, so a room can host
    back-to-back parties as long as the cleanup buffer fits between them."

    Design: Difficulty/resource_temporal_overlap/rto_room_half_open_buffer_overlap
    """
    venue, room, package = setup_config(buffer_minutes=30, base_duration_minutes=120,
                                        max_capacity=20)
    a = create_quote_draft_booking(room["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T10:00:00Z")
    hold_booking(a["id"])  # occupies [10:00, 12:30)
    b = create_quote_draft_booking(room["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T12:30:00Z")  # exactly at edge
    held_b = validate_success(api.hold_booking(b["id"], coordinator_headers), 200)
    assert held_b["status"] == "HELD"


# ─── Difficulty: resource_temporal_overlap / rto_staff_closed_adjacency_conflict

def test_staff_back_to_back_adjacency_conflicts(api, coordinator_headers):
    """PRD 3.6: "Because the interval is closed and inclusive of the buffer, two
    bookings whose windows merely touch end-to-end — where one window's end-plus-buffer
    equals the next window's start — do conflict for staff, since a person cannot
    teleport between back-to-back parties."

    Design: Difficulty/resource_temporal_overlap/rto_staff_closed_adjacency_conflict
    """
    venue = create_venue(weather_dependent=False)
    room1 = create_room(venue["id"], name="Rr2a", max_capacity=20, buffer_minutes=30)
    room2 = create_room(venue["id"], name="Rr2b", max_capacity=20, buffer_minutes=30)
    package = create_package(venue["id"], base_price_cents=30000, included_children=8,
                             per_extra_child_cents=1500, base_duration_minutes=120,
                             deposit_pct=0.25)
    reset_clock_base()
    staff = create_staff(venue["id"], "Host S", ["HOST"])

    a = create_quote_draft_booking(room1["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T10:00:00Z")
    hold_booking(a["id"])  # closed staff occupancy [10:00, 12:30]
    assign_staff(a["id"], staff["id"], "HOST")

    c = create_quote_draft_booking(room2["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T12:30:00Z")  # back-to-back
    hold_booking(c["id"])
    res = api.create_staff_assignment(
        c["id"], {"staff_member_id": staff["id"], "role_on_event": "HOST"}, coordinator_headers)
    validate_error(res, "ERR_STAFF_WINDOW_CONFLICT")


def test_staff_assignment_succeeds_when_no_overlap(api, coordinator_headers):
    """PRD 3.6: "The candidate set for this check is every other `ASSIGNED` assignment
    for the same staff member across any room whose parent booking is in `HELD`,
    `CONFIRMED`, `WEATHER_HOLD`, or `RESCHEDULED`. A conflict is rejected with
    `ERR_STAFF_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rto_staff_closed_adjacency_conflict
    """
    venue = create_venue(weather_dependent=False)
    room1 = create_room(venue["id"], name="Rg1", max_capacity=20, buffer_minutes=30)
    room2 = create_room(venue["id"], name="Rg2", max_capacity=20, buffer_minutes=30)
    package = create_package(venue["id"], base_price_cents=30000, included_children=8,
                             per_extra_child_cents=1500, base_duration_minutes=120,
                             deposit_pct=0.25)
    reset_clock_base()
    staff = create_staff(venue["id"], "Host S", ["HOST"])

    a = create_quote_draft_booking(room1["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-01T10:00:00Z")
    hold_booking(a["id"])  # [10:00, 12:30]
    assign_staff(a["id"], staff["id"], "HOST")

    # A clearly separated window on a later day cannot conflict.
    c = create_quote_draft_booking(room2["id"], package["id"], children_count=8,
                                   event_start_utc="2026-07-05T10:00:00Z")
    hold_booking(c["id"])
    assignment = validate_success(api.create_staff_assignment(
        c["id"], {"staff_member_id": staff["id"], "role_on_event": "HOST"},
        coordinator_headers), 201)
    assert assignment["status"] == "ASSIGNED"
