"""Capture-slot scheduling and the dual-geometry double-booking checks: half-open
backdrop intervals (adjacency allowed) vs buffered photographer intervals
(adjacency disallowed) (PRD §3.2).

Queue A: resource_temporal_overlap.
Queue B: entities, state_machines sections.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_capture_slot_payload,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_session, add_student, add_package, add_backdrop, add_photographer,
    add_capture_slot,
)
from test_helpers.api_client import api_client

COORD = TEST_USERS["coordinator_headers"]
PHOTOG = TEST_USERS["photographer_headers"]


# --------------------------------------------------------------------------- #
# resource_temporal_overlap / backdrop_halfopen_overlap_rejected  (queue A)
# --------------------------------------------------------------------------- #
def test_backdrop_overlap_rejected(api):
    """PRD §3.2: "Two windows on the same backdrop_id are treated as half-open
    intervals: the candidate conflicts with an existing scheduled slot when the
    candidate's start is earlier than the existing slot's end and the existing
    slot's start is earlier than the candidate's end."
    PRD §3.2: "Any backdrop conflict is rejected with ERR_BACKDROP_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/backdrop_halfopen_overlap_rejected
    """
    session = create_session()
    bd = add_backdrop(session["id"], label="Blue")
    phr1 = add_photographer(session["id"], full_name="Lee")
    phr2 = add_photographer(session["id"], full_name="Moe")
    add_capture_slot(session["id"], bd["id"], phr1["id"], homeroom="A",
                     start_minute=600, end_minute=660)
    # [650,720) overlaps [600,660) on the same backdrop; different photographer so
    # only the backdrop rule can fire.
    res = api.create_capture_slot(create_capture_slot_payload(
        session["id"], bd["id"], phr2["id"], homeroom="B",
        start_minute=650, end_minute=720), COORD)
    validate_error(res, "ERR_BACKDROP_DOUBLE_BOOKED", expected_status=409)


def test_backdrop_adjacency_allowed(api):
    """PRD §3.2: "Crucially, exact adjacency is permitted — a candidate whose start
    equals an existing slot's end does not conflict, because a zero-length gap is
    allowed on a backdrop."

    Design: Difficulty/resource_temporal_overlap/backdrop_halfopen_overlap_rejected
    """
    session = create_session()
    bd = add_backdrop(session["id"], label="Blue")
    phr1 = add_photographer(session["id"], full_name="Lee")
    phr2 = add_photographer(session["id"], full_name="Moe")
    add_capture_slot(session["id"], bd["id"], phr1["id"], homeroom="A",
                     start_minute=600, end_minute=660)
    # [660,720) is adjacent on the same backdrop (gap 0): allowed. Different
    # photographer so the photographer buffer rule does not interfere.
    res = api.create_capture_slot(create_capture_slot_payload(
        session["id"], bd["id"], phr2["id"], homeroom="B",
        start_minute=660, end_minute=720), COORD)
    slot = validate_success(res, 201)
    assert slot["status"] == "SCHEDULED"


# --------------------------------------------------------------------------- #
# resource_temporal_overlap / photographer_buffer_adjacency_rejected  (queue A)
# --------------------------------------------------------------------------- #
def test_photographer_buffer_adjacency_rejected(api):
    """PRD §3.2: "A photographer needs a mandatory ten-minute buffer between
    consecutive slots for set changes, so each existing photographer window is
    inflated by that buffer on both sides before the overlap test."
    PRD §3.2: "Two of a photographer's slots must therefore be separated by at least
    ten minutes of clear gap; exact adjacency, which the backdrop tolerates, is a
    conflict here. Any photographer conflict is rejected with
    ERR_PHOTOGRAPHER_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/photographer_buffer_adjacency_rejected
    """
    session = create_session()
    bd1 = add_backdrop(session["id"], label="Red")
    bd2 = add_backdrop(session["id"], label="Green")
    phr = add_photographer(session["id"], full_name="Ray")
    add_capture_slot(session["id"], bd1["id"], phr["id"], homeroom="A",
                     start_minute=600, end_minute=660)
    # adjacent [660,720) on the SAME photographer but a DIFFERENT backdrop:
    # backdrop rule passes, photographer buffer rule fires (660 < 660 + 10).
    res = api.create_capture_slot(create_capture_slot_payload(
        session["id"], bd2["id"], phr["id"], homeroom="B",
        start_minute=660, end_minute=720), COORD)
    validate_error(res, "ERR_PHOTOGRAPHER_DOUBLE_BOOKED", expected_status=409)


def test_photographer_gap_at_buffer_allowed(api):
    """PRD §3.2: "Concretely, for any existing scheduled slot sharing the
    candidate's photographer_id, the candidate conflicts when the candidate's start
    is earlier than the existing slot's end plus ten minutes and the existing slot's
    start is earlier than the candidate's end plus ten minutes."
    PRD §3.2: "Two of a photographer's slots must therefore be separated by at least
    ten minutes of clear gap"

    Design: Difficulty/resource_temporal_overlap/photographer_buffer_adjacency_rejected
    """
    session = create_session()
    bd1 = add_backdrop(session["id"], label="Red")
    bd2 = add_backdrop(session["id"], label="Green")
    phr = add_photographer(session["id"], full_name="Ray")
    add_capture_slot(session["id"], bd1["id"], phr["id"], homeroom="A",
                     start_minute=600, end_minute=660)
    # start 670 == end 660 + 10 buffer: candidate.start (670) is NOT < 660+10 (670),
    # so no conflict. A clear ten-minute gap is allowed.
    res = api.create_capture_slot(create_capture_slot_payload(
        session["id"], bd2["id"], phr["id"], homeroom="B",
        start_minute=670, end_minute=720), COORD)
    slot = validate_success(res, 201)
    assert slot["status"] == "SCHEDULED"


# --------------------------------------------------------------------------- #
# Queue B / entities / capture_slot_end_before_start_422
# --------------------------------------------------------------------------- #
def test_capture_slot_end_not_after_start_invalid(api):
    """PRD §2.7: "A capture slot's end_minute must be strictly greater than its
    start_minute"

    Design: Corner/entities/capture_slot_end_before_start_422
    """
    session = create_session()
    bd = add_backdrop(session["id"], label="B")
    phr = add_photographer(session["id"], full_name="P")
    res = api.create_capture_slot(create_capture_slot_payload(
        session["id"], bd["id"], phr["id"], homeroom="A",
        start_minute=700, end_minute=700), COORD)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=422)


# --------------------------------------------------------------------------- #
# Queue B / state_machines / complete_slot_not_scheduled_rejected
# --------------------------------------------------------------------------- #
def test_complete_cancelled_slot_rejected(api):
    """PRD §3.2: "While the session is in CAPTURE_OPEN, a StudioPhotographer may
    mark a scheduled slot completed, advancing it SCHEDULED → COMPLETED; attempting
    this when the session is not capturing yields ERR_SESSION_NOT_CAPTURING, and
    attempting it on a slot that is not SCHEDULED yields ERR_SLOT_NOT_SCHEDULED."

    Design: Corner/state_machines/complete_slot_not_scheduled_rejected
    """
    session = create_session()
    add_package(session["id"])
    add_student(session["id"])
    bd = add_backdrop(session["id"], label="B1")
    phr = add_photographer(session["id"], full_name="P1")
    api_client.lock_roster(session["id"], COORD)
    api_client.open_capture(session["id"], PHOTOG)
    slot = add_capture_slot(session["id"], bd["id"], phr["id"], homeroom="A",
                            start_minute=600, end_minute=660)
    api_client.cancel_capture_slot(slot["id"], PHOTOG)  # slot -> CANCELLED
    res = api.complete_capture_slot(slot["id"], PHOTOG)
    validate_error(res, "ERR_SLOT_NOT_SCHEDULED", expected_status=409)
