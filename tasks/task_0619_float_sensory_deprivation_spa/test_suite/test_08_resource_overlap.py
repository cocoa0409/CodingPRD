"""Resource temporal overlap: tank occupancy includes the turnover buffer (half-open), while
attendant orientation windows are raw half-open intervals with no buffer."""
from test_helpers import (
    validate_success, validate_error,
    setup_single_tank_with_first_booking, setup_attendant_with_orientation,
    create_booking_payload, create_orientation_payload,
    api_client, TEST_USERS,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]


# ─── Tank buffer overlap (rto_tank_buffer_overlap) ────────────────────────
def test_second_booking_inside_buffer_rejected(api):
    """PRD §3.5: "the tank is treated as occupied across the half-open span from `start_utc`
    to `end_utc` plus the tank's `turnover_buffer_minutes`, so that the cleaning buffer is
    reserved along with the session itself." PRD §3.5: "if the new occupancy span (session plus
    turnover buffer) overlaps the span of another live booking on that tank, creation is
    rejected with `ERR_TANK_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rto_tank_buffer_overlap
    """
    # Booking#1 occupies [10:00, 11:00 + 30m = 11:30). A start at 11:15 is inside the buffer.
    ctx = setup_single_tank_with_first_booking(buffer=30)
    member, tank = ctx["member"], ctx["tank"]
    res = api.create_booking(create_booking_payload(
        member["id"], tank["id"], 60, "2026-12-02T11:15:00Z", "CASH"), FRONTDESK)
    validate_error(res, "ERR_TANK_TIME_CONFLICT", expected_status=409)


def test_second_booking_at_buffer_end_allowed(api):
    """PRD §3.5: "the tank is treated as occupied across the half-open span from `start_utc`
    to `end_utc` plus the tank's `turnover_buffer_minutes`, so that the cleaning buffer is
    reserved along with the session itself."

    Design: Difficulty/resource_temporal_overlap/rto_tank_buffer_overlap
    """
    # Booking#1 occupies [10:00, 11:30) (half-open). A start at exactly 11:30 does not overlap.
    ctx = setup_single_tank_with_first_booking(buffer=30)
    member, tank = ctx["member"], ctx["tank"]
    booking = validate_success(api.create_booking(create_booking_payload(
        member["id"], tank["id"], 60, "2026-12-02T11:30:00Z", "CASH"), FRONTDESK), 201)
    assert booking["status"] == "RESERVED"


# ─── Attendant overlap (rto_attendant_no_buffer_overlap) ──────────────────
def test_overlapping_orientation_on_attendant_rejected(api):
    """PRD §3.2: "The platform refuses to schedule an orientation whose `[start_utc, end_utc)`
    interval overlaps another `SCHEDULED` orientation already booked on the same attendant,
    rejecting the clash with `ERR_ATTENDANT_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rto_attendant_no_buffer_overlap
    """
    # Orientation A is 09:00-10:00. A second at 09:30-10:30 overlaps it.
    ctx = setup_attendant_with_orientation()
    member_b, att = ctx["member_b"], ctx["attendant"]
    res = api.create_orientation(create_orientation_payload(
        member_b["id"], att["id"], "2026-12-05T09:30:00Z", "2026-12-05T10:30:00Z"), FRONTDESK)
    validate_error(res, "ERR_ATTENDANT_TIME_CONFLICT", expected_status=409)


def test_back_to_back_orientation_at_end_allowed(api):
    """PRD §3.2: "The platform refuses to schedule an orientation whose `[start_utc, end_utc)`
    interval overlaps another `SCHEDULED` orientation already booked on the same attendant".

    Design: Difficulty/resource_temporal_overlap/rto_attendant_no_buffer_overlap
    """
    # Orientation A is [09:00, 10:00). A back-to-back at exactly 10:00 does not overlap (half-open).
    ctx = setup_attendant_with_orientation()
    member_b, att = ctx["member_b"], ctx["attendant"]
    orientation = validate_success(api.create_orientation(create_orientation_payload(
        member_b["id"], att["id"], "2026-12-05T10:00:00Z", "2026-12-05T11:00:00Z"),
        FRONTDESK), 201)
    assert orientation["status"] == "SCHEDULED"
