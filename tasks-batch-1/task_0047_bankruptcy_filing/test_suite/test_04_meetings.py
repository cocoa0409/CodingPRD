"""341 meeting scheduling: the trustee half-open overlap check and the room
padded-buffer check, including the adjacency cases that distinguish the two
interval semantics.

PRD §3.5 governs every assertion in this file.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error,
    create_meeting_payload,
    register_trustee, setup_filed_case, schedule_meeting,
    make_trustee_headers,
)


def test_trustee_double_booked_half_open_overlap_rejected(api):
    """PRD §3.5: "The proposed slot ... must not overlap any other SCHEDULED
    meeting assigned to the same trustee_id. Two such meetings conflict precisely
    when the new start is before the existing end and the existing start is before
    the new end ... A trustee overlap is rejected with ERR_TRUSTEE_DOUBLE_BOOKED
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/trustee_double_booked_half_open_overlap
    """
    trustee = register_trustee(name="T1")
    _, case_a = setup_filed_case(filed_chapter="CHAPTER_13")
    _, case_b = setup_filed_case(filed_chapter="CHAPTER_13")
    schedule_meeting(trustee, case_a, room_code="ROOM-A",
                     scheduled_start="2026-08-01T09:00:00Z",
                     scheduled_end="2026-08-01T10:00:00Z")
    t_headers = make_trustee_headers(trustee["id"])
    # New [09:30,10:30) strictly overlaps existing [09:00,10:00) on the same trustee.
    res = api.create_meeting(create_meeting_payload(
        case_b["id"], trustee["id"], room_code="ROOM-B",
        scheduled_start="2026-08-01T09:30:00Z",
        scheduled_end="2026-08-01T10:30:00Z"), t_headers)
    validate_error(res, "ERR_TRUSTEE_DOUBLE_BOOKED")


def test_trustee_back_to_back_endpoints_do_not_conflict(api):
    """PRD §3.5: "under these strict comparisons, two back-to-back meetings that
    merely share an endpoint (one ending exactly when the next begins) do not
    conflict."

    Design: Difficulty/resource_temporal_overlap/trustee_double_booked_half_open_overlap
    """
    trustee = register_trustee(name="T1-adj")
    _, case_a = setup_filed_case(filed_chapter="CHAPTER_13")
    _, case_b = setup_filed_case(filed_chapter="CHAPTER_13")
    schedule_meeting(trustee, case_a, room_code="ROOM-ADJ-A",
                     scheduled_start="2026-08-03T09:00:00Z",
                     scheduled_end="2026-08-03T10:00:00Z")
    t_headers = make_trustee_headers(trustee["id"])
    # New [10:00,11:00) shares only the endpoint 10:00 with existing [09:00,10:00);
    # a different room avoids the room-buffer rule, so the trustee check passes.
    res = api.create_meeting(create_meeting_payload(
        case_b["id"], trustee["id"], room_code="ROOM-ADJ-B",
        scheduled_start="2026-08-03T10:00:00Z",
        scheduled_end="2026-08-03T11:00:00Z"), t_headers)
    validate_success(res, 201)


def test_room_buffer_conflict_padded_interval_rejected(api):
    """PRD §3.5: "the room is treated as busy ... for a window padded by a
    thirty-minute cleanup buffer on each side ... a conflict exists when the new
    start is before the padded end and the padded start is before the new end ...
    A room conflict is rejected with ERR_ROOM_BUFFER_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/room_buffer_conflict_padded_interval
    """
    trustee1 = register_trustee(name="T1-room")
    trustee2 = register_trustee(name="T2-room")
    _, case_a = setup_filed_case(filed_chapter="CHAPTER_13")
    _, case_b = setup_filed_case(filed_chapter="CHAPTER_13")
    schedule_meeting(trustee1, case_a, room_code="ROOM-X",
                     scheduled_start="2026-08-02T09:00:00Z",
                     scheduled_end="2026-08-02T10:00:00Z")
    t2_headers = make_trustee_headers(trustee2["id"])
    # ROOM-X again, only 15 minutes after the prior end -> inside the 30-min buffer.
    res = api.create_meeting(create_meeting_payload(
        case_b["id"], trustee2["id"], room_code="ROOM-X",
        scheduled_start="2026-08-02T10:15:00Z",
        scheduled_end="2026-08-02T11:15:00Z"), t2_headers)
    validate_error(res, "ERR_ROOM_BUFFER_CONFLICT")


def test_room_with_full_thirty_minute_gap_allowed(api):
    """PRD §3.5: "there must be a gap of at least thirty minutes between
    consecutive meetings in the same room". A meeting starting exactly thirty
    minutes after the prior one ends clears the buffer.

    Design: Difficulty/resource_temporal_overlap/room_buffer_conflict_padded_interval
    """
    trustee1 = register_trustee(name="T1-gap")
    trustee2 = register_trustee(name="T2-gap")
    _, case_a = setup_filed_case(filed_chapter="CHAPTER_13")
    _, case_b = setup_filed_case(filed_chapter="CHAPTER_13")
    schedule_meeting(trustee1, case_a, room_code="ROOM-GAP",
                     scheduled_start="2026-08-04T09:00:00Z",
                     scheduled_end="2026-08-04T10:00:00Z")
    t2_headers = make_trustee_headers(trustee2["id"])
    # New start 10:30 == prior end 10:00 + 30-min buffer; padded busy window is
    # [08:30,10:30), and the new [10:30,11:30) does not intersect it.
    res = api.create_meeting(create_meeting_payload(
        case_b["id"], trustee2["id"], room_code="ROOM-GAP",
        scheduled_start="2026-08-04T10:30:00Z",
        scheduled_end="2026-08-04T11:30:00Z"), t2_headers)
    validate_success(res, 201)
