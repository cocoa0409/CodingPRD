"""Test Room state machine transitions and cascading side effects.

Covers:
- ACTIVE -> MAINTENANCE (Table 2: Room state machine)
- MAINTENANCE -> ACTIVE
- ACTIVE -> DECOMMISSIONED
- MAINTENANCE -> DECOMMISSIONED
- DECOMMISSIONED is terminal (no transitions out)
- Cascading cancellations on MAINTENANCE transition
- Cascading cancellations + waitlist expiry on DECOMMISSIONED transition
- ERR_ROOM_HAS_ACTIVE_BOOKINGS blocks decommission with CHECKED_IN bookings
"""
import pytest
from datetime import datetime, timedelta, timezone
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    assert_room, assert_booking,
    create_room_payload, create_booking_payload, create_waitlist_payload,
    create_standard_room, create_premium_room,
    create_room_in_maintenance, create_room_decommissioned,
    create_confirmed_booking, create_checked_in_booking,
    create_pending_approval_booking,
)


_admin = TEST_USERS["facility_admin_headers"]
_employee = TEST_USERS["employee_headers"]


class TestRoomStateTransitions:
    """Room state machine: ACTIVE <-> MAINTENANCE, {ACTIVE, MAINTENANCE} -> DECOMMISSIONED."""

    def test_active_to_maintenance(self):
        """ACTIVE -> MAINTENANCE transition succeeds."""
        room = create_standard_room()
        resp = api_client.update_room(room["id"], {"status": "MAINTENANCE"}, _admin)
        data = validate_success(resp, 200)
        assert data["status"] == "MAINTENANCE"
        assert data["version"] > room["version"]

    def test_maintenance_to_active(self):
        """MAINTENANCE -> ACTIVE transition succeeds."""
        room = create_room_in_maintenance()
        resp = api_client.update_room(room["id"], {"status": "ACTIVE"}, _admin)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVE"

    def test_active_to_decommissioned(self):
        """ACTIVE -> DECOMMISSIONED transition succeeds (no checked-in bookings)."""
        room = create_standard_room()
        resp = api_client.update_room(room["id"], {"status": "DECOMMISSIONED"}, _admin)
        data = validate_success(resp, 200)
        assert data["status"] == "DECOMMISSIONED"

    def test_maintenance_to_decommissioned(self):
        """MAINTENANCE -> DECOMMISSIONED transition succeeds."""
        room = create_room_in_maintenance()
        resp = api_client.update_room(room["id"], {"status": "DECOMMISSIONED"}, _admin)
        data = validate_success(resp, 200)
        assert data["status"] == "DECOMMISSIONED"

    def test_decommissioned_is_terminal(self):
        """DECOMMISSIONED -> any other state fails."""
        room = create_room_decommissioned()
        for target in ["ACTIVE", "MAINTENANCE"]:
            resp = api_client.update_room(room["id"], {"status": target}, _admin)
            validate_error_is_one_of(resp, [ApiErrorId.ERR_INVALID_BOOKING_STATE, ApiErrorId.ERR_BAD_REQUEST, ApiErrorId.ERR_ROOM_NOT_ACTIVE])

    def test_decommissioned_to_active_fails(self):
        """DECOMMISSIONED room cannot return to ACTIVE."""
        room = create_room_decommissioned()
        resp = api_client.update_room(room["id"], {"status": "ACTIVE"}, _admin)
        # Should be some error - either invalid state or bad request
        assert resp.status_code >= 400, f"Expected error, got {resp.status_code}"

    def test_decommissioned_to_maintenance_fails(self):
        """DECOMMISSIONED room cannot return to MAINTENANCE."""
        room = create_room_decommissioned()
        resp = api_client.update_room(room["id"], {"status": "MAINTENANCE"}, _admin)
        assert resp.status_code >= 400, f"Expected error, got {resp.status_code}"


class TestMaintenanceCascade:
    """Side effects of transitioning room to MAINTENANCE."""

    def test_maintenance_cancels_future_tentative_bookings(self):
        """ACTIVE -> MAINTENANCE cancels future TENTATIVE bookings."""
        room = create_premium_room()
        # Create a PENDING_APPROVAL booking (PREMIUM room)
        start = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end = (datetime.now(timezone.utc) + timedelta(days=5, hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        booking = get_success_data(resp)
        assert booking["status"] == "PENDING_APPROVAL"

        # Transition to MAINTENANCE
        api_client.update_room(room["id"], {"status": "MAINTENANCE"}, _admin)

        # Booking should now be CANCELLED
        resp = api_client.get_booking(booking["id"], _employee)
        updated_booking = get_success_data(resp)
        assert updated_booking["status"] == "CANCELLED", (
            f"Expected CANCELLED after MAINTENANCE cascade, got {updated_booking['status']}"
        )

    def test_maintenance_cancels_future_confirmed_bookings(self):
        """ACTIVE -> MAINTENANCE cancels future CONFIRMED bookings."""
        room = create_standard_room()
        start = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end = (datetime.now(timezone.utc) + timedelta(days=5, hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        booking = get_success_data(resp)
        assert booking["status"] == "CONFIRMED"

        api_client.update_room(room["id"], {"status": "MAINTENANCE"}, _admin)

        resp = api_client.get_booking(booking["id"], _employee)
        updated = get_success_data(resp)
        assert updated["status"] == "CANCELLED"


class TestDecommissionCascade:
    """Side effects of transitioning room to DECOMMISSIONED."""

    def test_decommission_blocked_by_checked_in_booking(self):
        """Cannot decommission room with CHECKED_IN booking -> ERR_ROOM_HAS_ACTIVE_BOOKINGS."""
        booking, room = create_checked_in_booking()
        resp = api_client.update_room(room["id"], {"status": "DECOMMISSIONED"}, _admin)
        validate_error(resp, ApiErrorId.ERR_ROOM_HAS_ACTIVE_BOOKINGS)

    def test_decommission_cancels_all_future_bookings(self):
        """DECOMMISSIONED cancels all future non-terminal bookings."""
        room = create_standard_room()
        start = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end = (datetime.now(timezone.utc) + timedelta(days=5, hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        booking = get_success_data(resp)

        api_client.update_room(room["id"], {"status": "DECOMMISSIONED"}, _admin)

        resp = api_client.get_booking(booking["id"], _employee)
        updated = get_success_data(resp)
        assert updated["status"] == "CANCELLED"

    def test_decommission_expires_waiting_waitlist(self):
        """DECOMMISSIONED expires all WAITING waitlist entries."""
        room = create_standard_room()

        # Create a confirmed booking to make the slot busy
        start = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end = (datetime.now(timezone.utc) + timedelta(days=5, hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        api_client.create_booking(payload, _employee)

        # Create waitlist entry for same slot (different user)
        wl_payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_waitlist(wl_payload, TEST_USERS["employee2_headers"])
        wl = get_success_data(resp)
        assert wl["status"] == "WAITING"

        # Decommission room
        api_client.update_room(room["id"], {"status": "DECOMMISSIONED"}, _admin)

        # Waitlist entry should be EXPIRED
        resp = api_client.list_waitlist(_admin, params={"room_id": room["id"], "status": "EXPIRED"})
        from test_helpers import validate_paginated
        items, _ = validate_paginated(resp)
        expired_ids = [w["id"] for w in items]
        assert wl["id"] in expired_ids, "Waitlist entry should be EXPIRED after decommission"

    def test_cannot_book_decommissioned_room(self):
        """Booking a DECOMMISSIONED room -> ERR_ROOM_NOT_ACTIVE."""
        room = create_room_decommissioned()
        start = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end = (datetime.now(timezone.utc) + timedelta(days=5, hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_ACTIVE)

    def test_cannot_book_maintenance_room(self):
        """Booking a MAINTENANCE room -> ERR_ROOM_NOT_ACTIVE."""
        room = create_room_in_maintenance()
        start = (datetime.now(timezone.utc) + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end = (datetime.now(timezone.utc) + timedelta(days=5, hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_ACTIVE)
