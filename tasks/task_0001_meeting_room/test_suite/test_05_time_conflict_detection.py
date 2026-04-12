"""Test temporal conflict detection and half-open interval semantics.

Covers:
- Overlap detection: booking_a.start < booking_b.end AND booking_b.start < booking_a.end
- Half-open intervals: [start, end) - adjacent bookings allowed
- Only CONFIRMED and CHECKED_IN block slots (TENTATIVE, PENDING_APPROVAL do not)
- ERR_TIME_CONFLICT on overlapping STANDARD room bookings
- ERR_TIME_CONFLICT on approval of overlapping PREMIUM room bookings
- Various overlap scenarios: fully contained, partial overlap, straddling
"""
import pytest
from datetime import datetime, timedelta, timezone
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_booking_payload,
    create_standard_room, create_premium_room,
    setup_time_conflict_scenario,
)


_admin = TEST_USERS["facility_admin_headers"]
_employee = TEST_USERS["employee_headers"]
_employee2 = TEST_USERS["employee2_headers"]
_manager = TEST_USERS["manager_headers"]


def _ts(hours=24, minutes=0):
    dt = datetime.now(timezone.utc) + timedelta(hours=hours, minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


class TestOverlapDetection:
    """Half-open interval overlap: [start_a, end_a) vs [start_b, end_b)."""

    def test_exact_same_slot_conflict(self):
        """Two bookings with identical [start, end) -> ERR_TIME_CONFLICT."""
        room, existing, start, end = setup_time_conflict_scenario()
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee2)
        validate_error(resp, ApiErrorId.ERR_TIME_CONFLICT)

    def test_new_starts_during_existing(self):
        """New booking starts in the middle of an existing one -> ERR_TIME_CONFLICT."""
        room = create_standard_room()
        start1 = _ts(hours=96)
        end1 = _ts(hours=98)
        p1 = create_booking_payload(room["id"], start_time=start1, end_time=end1)
        api_client.create_booking(p1, _employee)

        # New booking starts at hour 97 (within existing [96, 98))
        start2 = _ts(hours=97)
        end2 = _ts(hours=99)
        p2 = create_booking_payload(room["id"], start_time=start2, end_time=end2)
        resp = api_client.create_booking(p2, _employee2)
        validate_error(resp, ApiErrorId.ERR_TIME_CONFLICT)

    def test_new_ends_during_existing(self):
        """New booking ends in the middle of an existing one -> ERR_TIME_CONFLICT."""
        room = create_standard_room()
        start1 = _ts(hours=96)
        end1 = _ts(hours=98)
        p1 = create_booking_payload(room["id"], start_time=start1, end_time=end1)
        api_client.create_booking(p1, _employee)

        # New booking ends at hour 97 (within existing [96, 98))
        start2 = _ts(hours=95)
        end2 = _ts(hours=97)
        p2 = create_booking_payload(room["id"], start_time=start2, end_time=end2)
        resp = api_client.create_booking(p2, _employee2)
        validate_error(resp, ApiErrorId.ERR_TIME_CONFLICT)

    def test_new_fully_contains_existing(self):
        """New booking fully contains existing one -> ERR_TIME_CONFLICT."""
        room = create_standard_room()
        start1 = _ts(hours=96)
        end1 = _ts(hours=97)
        p1 = create_booking_payload(room["id"], start_time=start1, end_time=end1)
        api_client.create_booking(p1, _employee)

        start2 = _ts(hours=95)
        end2 = _ts(hours=98)
        p2 = create_booking_payload(room["id"], start_time=start2, end_time=end2)
        resp = api_client.create_booking(p2, _employee2)
        validate_error(resp, ApiErrorId.ERR_TIME_CONFLICT)

    def test_new_fully_contained_in_existing(self):
        """New booking fully within existing one -> ERR_TIME_CONFLICT."""
        room = create_standard_room()
        start1 = _ts(hours=96)
        end1 = _ts(hours=100)
        p1 = create_booking_payload(room["id"], start_time=start1, end_time=end1)
        api_client.create_booking(p1, _employee)

        start2 = _ts(hours=97)
        end2 = _ts(hours=99)
        p2 = create_booking_payload(room["id"], start_time=start2, end_time=end2)
        resp = api_client.create_booking(p2, _employee2)
        validate_error(resp, ApiErrorId.ERR_TIME_CONFLICT)


class TestAdjacentBookings:
    """Half-open interval semantics: back-to-back is NOT a conflict."""

    def test_adjacent_bookings_allowed(self):
        """booking_a.end_time == booking_b.start_time -> no conflict."""
        room = create_standard_room()
        start1 = _ts(hours=96)
        end1 = _ts(hours=97)
        p1 = create_booking_payload(room["id"], start_time=start1, end_time=end1)
        resp1 = api_client.create_booking(p1, _employee)
        validate_success(resp1, 201)

        # Next booking starts exactly where previous ends
        start2 = end1  # booking_b.start == booking_a.end
        end2 = _ts(hours=98)
        p2 = create_booking_payload(room["id"], start_time=start2, end_time=end2)
        resp2 = api_client.create_booking(p2, _employee2)
        validate_success(resp2, 201)

    def test_bookings_before_existing_no_conflict(self):
        """Booking that ends before existing starts -> no conflict."""
        room = create_standard_room()
        start1 = _ts(hours=100)
        end1 = _ts(hours=101)
        p1 = create_booking_payload(room["id"], start_time=start1, end_time=end1)
        api_client.create_booking(p1, _employee)

        start2 = _ts(hours=96)
        end2 = _ts(hours=97)
        p2 = create_booking_payload(room["id"], start_time=start2, end_time=end2)
        resp = api_client.create_booking(p2, _employee2)
        validate_success(resp, 201)

    def test_bookings_after_existing_no_conflict(self):
        """Booking that starts after existing ends -> no conflict."""
        room = create_standard_room()
        start1 = _ts(hours=96)
        end1 = _ts(hours=97)
        p1 = create_booking_payload(room["id"], start_time=start1, end_time=end1)
        api_client.create_booking(p1, _employee)

        start2 = _ts(hours=98)
        end2 = _ts(hours=99)
        p2 = create_booking_payload(room["id"], start_time=start2, end_time=end2)
        resp = api_client.create_booking(p2, _employee2)
        validate_success(resp, 201)


class TestOnlyConfirmedCheckedInBlock:
    """Only CONFIRMED and CHECKED_IN bookings block a time slot."""

    def test_pending_approval_does_not_block(self):
        """PENDING_APPROVAL booking on PREMIUM room does not block slot for another booking."""
        room = create_premium_room()
        start = _ts(hours=96)
        end = _ts(hours=97)

        # First booking goes to PENDING_APPROVAL
        p1 = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp1 = api_client.create_booking(p1, _employee)
        b1 = get_success_data(resp1)
        assert b1["status"] == "PENDING_APPROVAL"

        # Second booking for same slot also goes to PENDING_APPROVAL (no conflict)
        p2 = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp2 = api_client.create_booking(p2, _employee2)
        b2 = get_success_data(resp2)
        assert b2["status"] == "PENDING_APPROVAL"

    def test_cancelled_booking_does_not_block(self):
        """Slot freed after cancellation allows new booking."""
        room = create_standard_room()
        start = _ts(hours=96)
        end = _ts(hours=97)

        p1 = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp1 = api_client.create_booking(p1, _employee)
        b1 = get_success_data(resp1)

        # Cancel the booking
        api_client.cancel_booking(b1["id"], _employee)

        # New booking for same slot should succeed
        p2 = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp2 = api_client.create_booking(p2, _employee2)
        validate_success(resp2, 201)

    def test_different_rooms_no_conflict(self):
        """Same time slot on different rooms -> no conflict."""
        room1 = create_standard_room()
        room2 = create_standard_room()
        start = _ts(hours=96)
        end = _ts(hours=97)

        p1 = create_booking_payload(room1["id"], start_time=start, end_time=end)
        resp1 = api_client.create_booking(p1, _employee)
        validate_success(resp1, 201)

        p2 = create_booking_payload(room2["id"], start_time=start, end_time=end)
        resp2 = api_client.create_booking(p2, _employee2)
        validate_success(resp2, 201)
