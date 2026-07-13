"""Resource temporal-overlap conflicts: courtroom buffer vs service-site capacity.

Translates queue-A resource_temporal_overlap instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS, make_probation_officer_headers,
    create_arraignment_payload, create_service_site_payload,
    create_service_assignment_payload,
    setup_room_with_booking, setup_accepted_diversion,
)

CLERK = "court_clerk_headers"
ADMIN = "court_admin_headers"


# ===========================================================================
# Rule 8a — courtroom buffer-expanded overlap.
# ===========================================================================

def test_courtroom_buffer_gap_booking_rejected(api):
    """PRD §3.3: "Each hearing reserves not just its own interval but that interval
    expanded by the room's changeover_buffer_minutes on both sides ... Two hearings
    in the same courtroom conflict when their buffer-expanded intervals overlap.
    If a requested booking's buffer-expanded interval overlaps that of any existing
    hearing in the same room, the request is rejected with ERR_COURTROOM_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/courtroom_buffer_overlap_rejected
    """
    room, case = setup_room_with_booking(
        api, buffer_minutes=15,
        existing_start="2026-03-20T10:00:00Z", existing_end="2026-03-20T10:30:00Z")
    # Raw gap 10:30->10:40 is 10 min < 15 buffer; buffer-expanded intervals overlap.
    resp = api.create_arraignment(
        case["id"],
        create_arraignment_payload(room["id"], scheduled_start="2026-03-20T10:40:00Z",
                                   scheduled_end="2026-03-20T11:00:00Z"),
        TEST_USERS[CLERK])
    validate_error(resp, ApiErrorId.ERR_COURTROOM_DOUBLE_BOOKED, 409)


def test_courtroom_raw_overlap_booking_rejected(api):
    """PRD §3.3: "Two hearings in the same courtroom conflict when their
    buffer-expanded intervals overlap ... the request is rejected with
    ERR_COURTROOM_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/courtroom_buffer_overlap_rejected
    """
    room, case = setup_room_with_booking(
        api, buffer_minutes=15,
        existing_start="2026-03-20T10:00:00Z", existing_end="2026-03-20T10:30:00Z")
    # A hearing whose own interval directly overlaps the existing [10:00,10:30).
    resp = api.create_arraignment(
        case["id"],
        create_arraignment_payload(room["id"], scheduled_start="2026-03-20T10:15:00Z",
                                   scheduled_end="2026-03-20T10:45:00Z"),
        TEST_USERS[CLERK])
    validate_error(resp, ApiErrorId.ERR_COURTROOM_DOUBLE_BOOKED, 409)


# ===========================================================================
# Rule 8b — service-site concurrent-capacity overlap.
# ===========================================================================

def _site_with_one_session(api):
    ctx = setup_accepted_diversion(api, diversion_overrides={"mandated_service_hours": 10})
    officer = make_probation_officer_headers("po_1")
    site = validate_success(api.create_service_site(
        create_service_site_payload(site_type="COMMUNITY_SERVICE", concurrent_capacity=1),
        TEST_USERS[ADMIN]), 201)
    validate_success(api.create_service_assignment(
        ctx["diversion"]["id"],
        create_service_assignment_payload(
            site["id"], assignment_type="COMMUNITY_SERVICE", required_hours=2,
            session_start="2026-03-21T10:00:00Z", session_end="2026-03-21T12:00:00Z"),
        officer), 201)
    ctx["site"] = site
    ctx["officer"] = officer
    return ctx


def test_service_site_overlap_at_capacity_rejected(api):
    """PRD §3.6: "the number of the site's assignments whose session windows overlap
    in time may not exceed the site's concurrent_capacity. If adding this assignment
    would push the count of time-overlapping sessions at the site above that
    capacity, it is rejected with ERR_SERVICE_SITE_AT_CAPACITY."

    Design: Difficulty/resource_temporal_overlap/service_site_capacity_overlap_rejected
    """
    ctx = _site_with_one_session(api)
    # capacity 1 already occupied by [10:00,12:00); an overlapping [11:00,13:00) exceeds it.
    resp = api.create_service_assignment(
        ctx["diversion"]["id"],
        create_service_assignment_payload(
            ctx["site"]["id"], assignment_type="COMMUNITY_SERVICE", required_hours=2,
            session_start="2026-03-21T11:00:00Z", session_end="2026-03-21T13:00:00Z"),
        ctx["officer"])
    validate_error(resp, ApiErrorId.ERR_SERVICE_SITE_AT_CAPACITY, 409)


def test_service_site_adjacent_session_allowed(api):
    """PRD §3.6: "the required_hours the assignment covers ... and the half-open
    session window given by session_start and session_end, where the end must be
    strictly after the start."
    PRD §3.6: "the number of the site's assignments whose session windows overlap
    in time may not exceed the site's concurrent_capacity."

    Design: Difficulty/resource_temporal_overlap/service_site_capacity_overlap_rejected
    """
    ctx = _site_with_one_session(api)
    # A half-open-adjacent [12:00,14:00) does not overlap [10:00,12:00); it is allowed.
    resp = api.create_service_assignment(
        ctx["diversion"]["id"],
        create_service_assignment_payload(
            ctx["site"]["id"], assignment_type="COMMUNITY_SERVICE", required_hours=2,
            session_start="2026-03-21T12:00:00Z", session_end="2026-03-21T14:00:00Z"),
        ctx["officer"])
    assignment = validate_success(resp, 201)
    assert assignment["status"] == "ASSIGNED"
