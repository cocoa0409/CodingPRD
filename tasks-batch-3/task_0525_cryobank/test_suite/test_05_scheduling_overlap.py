"""Collection-room and dewar-maintenance overlap semantics.

Queue-A (Difficulty) translations for resource_temporal_overlap (room half-open
no buffer; dewar closed with symmetric 24h buffer).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_approved_donor,
)

SO = TEST_USERS["screening_officer_headers"]
LT = TEST_USERS["lab_tech_headers"]


def test_room_touching_endpoint_ok_but_interior_overlap_rejected(api):
    """PRD §3.9: "Room windows use half-open interval semantics with no buffer: a
    new appointment conflicts with an existing BOOKED appointment on the same
    room_code when the new window's start falls before the existing window's end and
    the existing window's start falls before the new window's end. Two windows that
    merely touch at an endpoint — where one's end equals the other's start — do not
    conflict. A conflicting booking is rejected with ERR_ROOM_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/collection_room_half_open_overlap
    """
    donor_id, _ = create_approved_donor(display_code="D-15")
    validate_success(api.create_collection_appointment({
        "donor_id": donor_id, "room_code": "ROOM-A",
        "window_start": "2026-05-02T09:00:00Z", "window_end": "2026-05-02T10:00:00Z",
    }, LT), expected_status=201)
    # Touching at 10:00 — half-open, no conflict.
    validate_success(api.create_collection_appointment({
        "donor_id": donor_id, "room_code": "ROOM-A",
        "window_start": "2026-05-02T10:00:00Z", "window_end": "2026-05-02T11:00:00Z",
    }, LT), expected_status=201)
    # 09:30 falls inside [09:00,10:00) — conflict.
    resp = api.create_collection_appointment({
        "donor_id": donor_id, "room_code": "ROOM-A",
        "window_start": "2026-05-02T09:30:00Z", "window_end": "2026-05-02T10:30:00Z",
    }, LT)
    validate_error(resp, ApiErrorId.ERR_ROOM_WINDOW_CONFLICT.value)


def test_room_different_room_code_does_not_conflict(api):
    """PRD §3.9: "a new appointment conflicts with an existing BOOKED appointment on
    the same room_code when the new window's start falls before the existing window's
    end and the existing window's start falls before the new window's end."

    Overlap only constrains appointments sharing a room_code; an identical time on a
    different room_code books cleanly.

    Design: Difficulty/resource_temporal_overlap/collection_room_half_open_overlap
    """
    donor_id, _ = create_approved_donor(display_code="D-15b")
    validate_success(api.create_collection_appointment({
        "donor_id": donor_id, "room_code": "ROOM-A",
        "window_start": "2026-05-02T09:00:00Z", "window_end": "2026-05-02T10:00:00Z",
    }, LT), expected_status=201)
    # Same interval, different room — no conflict.
    validate_success(api.create_collection_appointment({
        "donor_id": donor_id, "room_code": "ROOM-B",
        "window_start": "2026-05-02T09:00:00Z", "window_end": "2026-05-02T10:00:00Z",
    }, LT), expected_status=201)


def test_dewar_window_within_buffer_conflicts(api):
    """PRD §3.9: "Dewar windows use closed-interval semantics with a symmetric buffer
    of 24 hours applied to both ends (SETTLE_BUFFER_HOURS is 24). A new window
    conflicts with an existing SCHEDULED window on the same dewar_code when the new
    window's start minus the 24-hour buffer is at or before the existing window's
    end, and the existing window's start is at or before the new window's end plus
    the 24-hour buffer — so that windows which touch, or fall within a day of each
    other on either side, do conflict. A conflicting schedule is rejected with
    ERR_DEWAR_WINDOW_CONFLICT."

    First window ends 06:00; second starts 18:00 (12h later, within the 24h buffer).

    Design: Difficulty/resource_temporal_overlap/dewar_maintenance_buffered_closed_overlap
    """
    validate_success(api.create_dewar_maintenance_window({
        "dewar_code": "TANK-1", "service_start": "2026-05-03T00:00:00Z",
        "service_end": "2026-05-03T06:00:00Z",
    }, LT), expected_status=201)
    resp = api.create_dewar_maintenance_window({
        "dewar_code": "TANK-1", "service_start": "2026-05-03T18:00:00Z",
        "service_end": "2026-05-03T20:00:00Z",
    }, LT)
    validate_error(resp, ApiErrorId.ERR_DEWAR_WINDOW_CONFLICT.value)


def test_dewar_window_beyond_buffer_does_not_conflict(api):
    """PRD §3.9: "A new window conflicts with an existing SCHEDULED window on the
    same dewar_code when the new window's start minus the 24-hour buffer is at or
    before the existing window's end, and the existing window's start is at or before
    the new window's end plus the 24-hour buffer".

    First window ends 06:00 on 2026-05-03; a second starting 07:00 on 2026-05-04
    (25h later, beyond the 24h buffer: start-24h = 07:00 on 2026-05-03, strictly
    after the first end 06:00) does not conflict.

    Design: Difficulty/resource_temporal_overlap/dewar_maintenance_buffered_closed_overlap
    """
    validate_success(api.create_dewar_maintenance_window({
        "dewar_code": "TANK-2", "service_start": "2026-05-03T00:00:00Z",
        "service_end": "2026-05-03T06:00:00Z",
    }, LT), expected_status=201)
    validate_success(api.create_dewar_maintenance_window({
        "dewar_code": "TANK-2", "service_start": "2026-05-04T07:00:00Z",
        "service_end": "2026-05-04T09:00:00Z",
    }, LT), expected_status=201)
