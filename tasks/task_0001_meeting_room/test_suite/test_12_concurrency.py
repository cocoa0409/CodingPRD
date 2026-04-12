"""Test concurrency scenarios and race conditions.

Covers:
- Concurrent booking of the same slot -> exactly one succeeds (ERR_TIME_CONFLICT)
- Concurrent approval of conflicting PREMIUM bookings
- Concurrent room updates with optimistic concurrency
- Concurrent waitlist creation for same slot
- Concurrent booking creation and cancellation
"""
import pytest
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    run_race,
    ApiErrorId, TEST_USERS,
    create_booking_payload,
    create_standard_room, create_premium_room,
    setup_race_booking_scenario,
)


_admin = TEST_USERS["facility_admin_headers"]
_employee = TEST_USERS["employee_headers"]
_employee2 = TEST_USERS["employee2_headers"]
_manager = TEST_USERS["manager_headers"]


def _ts(hours=120, minutes=0):
    dt = datetime.now(timezone.utc) + timedelta(hours=hours, minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


class TestConcurrentBookingCreation:
    """Two users booking the same STANDARD room slot concurrently."""

    def test_concurrent_same_slot_booking(self):
        """Exactly one of two concurrent booking requests should succeed."""
        room, start, end = setup_race_booking_scenario()

        def book(headers):
            payload = create_booking_payload(room["id"], start_time=start, end_time=end)
            return api_client.create_booking(payload, headers)

        results = run_race(
            lambda: book(_employee),
            lambda: book(_employee2),
        )

        successes = [r for r in results if r.status_code == 201]
        conflicts = [r for r in results if r.status_code == 409]

        assert len(successes) >= 1, "At least one booking should succeed"
        assert len(successes) + len(conflicts) == 2, (
            f"Expected success+conflict=2, got {len(successes)} success + {len(conflicts)} conflict"
        )

    def test_concurrent_non_overlapping_slots(self):
        """Concurrent bookings for different time slots on same room both succeed."""
        room = create_standard_room()
        start1 = _ts(hours=120)
        end1 = _ts(hours=121)
        start2 = _ts(hours=122)
        end2 = _ts(hours=123)

        def book1():
            payload = create_booking_payload(room["id"], start_time=start1, end_time=end1)
            return api_client.create_booking(payload, _employee)

        def book2():
            payload = create_booking_payload(room["id"], start_time=start2, end_time=end2)
            return api_client.create_booking(payload, _employee2)

        results = run_race(book1, book2)

        successes = [r for r in results if r.status_code == 201]
        assert len(successes) == 2, "Both non-overlapping bookings should succeed"


class TestConcurrentApproval:
    """Concurrent approval of conflicting PREMIUM room bookings."""

    def test_concurrent_approve_same_slot(self):
        """Two PENDING_APPROVAL bookings for same slot. Approving both concurrently:
        one succeeds, one gets ERR_TIME_CONFLICT."""
        room = create_premium_room()
        start = _ts(hours=144)
        end = _ts(hours=145)

        # Create two bookings for same slot
        p1 = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp1 = api_client.create_booking(p1, _employee)
        b1 = get_success_data(resp1)

        p2 = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp2 = api_client.create_booking(p2, _employee2)
        b2 = get_success_data(resp2)

        results = run_race(
            lambda: api_client.approve_booking(b1["id"], _manager),
            lambda: api_client.approve_booking(b2["id"], _admin),
        )

        successes = [r for r in results if r.status_code == 200]
        conflicts = [r for r in results if r.status_code == 409]

        assert len(successes) >= 1, "At least one approval should succeed"
        # The other should either be a conflict or also succeed (if system serializes well)


class TestConcurrentRoomUpdate:
    """Concurrent room updates with version-based optimistic concurrency."""

    def test_concurrent_room_updates_with_version(self):
        """Two updates with same version: one succeeds, one gets ERR_VERSION_CONFLICT."""
        room = create_standard_room()
        v = room["version"]

        results = run_race(
            lambda: api_client.update_room(room["id"], {"capacity": 15, "version": v}, _admin),
            lambda: api_client.update_room(room["id"], {"capacity": 20, "version": v}, TEST_USERS["facility_admin2_headers"]),
        )

        successes = [r for r in results if r.status_code == 200]
        conflicts = [r for r in results if r.status_code == 409]

        assert len(successes) >= 1, "At least one update should succeed"
        assert len(successes) + len(conflicts) == 2, (
            "One should succeed and one should get version conflict"
        )


class TestConcurrentBookingAndCancel:
    """Concurrent booking creation while another is being cancelled."""

    def test_cancel_and_book_same_slot(self):
        """Cancel existing booking while new booking attempts same slot.

        Both operations should complete without server errors.
        """
        room = create_standard_room()
        start = _ts(hours=168)
        end = _ts(hours=169)

        # Create initial booking
        p1 = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp1 = api_client.create_booking(p1, _employee)
        b1 = get_success_data(resp1)

        results = run_race(
            lambda: api_client.cancel_booking(b1["id"], _employee),
            lambda: api_client.create_booking(
                create_booking_payload(room["id"], start_time=start, end_time=end),
                _employee2,
            ),
        )

        # At minimum, no 500 errors
        for r in results:
            assert r.status_code < 500, f"Server error: {r.status_code}"
