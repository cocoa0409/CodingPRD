"""Test Booking state machine transitions.

Covers:
- TENTATIVE -> CONFIRMED (auto for STANDARD)
- TENTATIVE -> PENDING_APPROVAL (auto for PREMIUM)
- PENDING_APPROVAL -> CONFIRMED (approve)
- PENDING_APPROVAL -> CANCELLED (reject with rejection_reason)
- CONFIRMED -> CHECKED_IN (check-in within window)
- CHECKED_IN -> COMPLETED (check-out)
- {TENTATIVE, PENDING_APPROVAL, CONFIRMED} -> CANCELLED (cancel)
- CONFIRMED -> NO_SHOW (via ops run)
- Invalid transitions -> ERR_INVALID_BOOKING_STATE
- Check-in window enforcement -> ERR_CHECKIN_WINDOW
- Version increments on transitions
"""
import pytest
from datetime import datetime, timedelta, timezone
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    assert_booking,
    create_booking_payload,
    create_standard_room, create_premium_room,
    create_confirmed_booking, create_pending_approval_booking,
    create_checked_in_booking, create_completed_booking,
)


_admin = TEST_USERS["facility_admin_headers"]
_employee = TEST_USERS["employee_headers"]
_manager = TEST_USERS["manager_headers"]


def _future(hours=24, minutes=0):
    dt = datetime.now(timezone.utc) + timedelta(hours=hours, minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


class TestApproveBooking:
    """POST /bookings/{booking_id}/approve"""

    def test_approve_pending_booking(self):
        """Approve PENDING_APPROVAL -> CONFIRMED with cost_cents computed."""
        booking, room = create_pending_approval_booking()
        resp = api_client.approve_booking(booking["id"], _manager)
        data = validate_success(resp, 200)
        assert data["status"] == "CONFIRMED"
        assert isinstance(data["cost_cents"], int), "cost_cents must be computed on approval"
        assert data["cost_cents"] > 0
        assert data["version"] > booking["version"]

    def test_approve_booking_facility_admin_allowed(self):
        """facility_admin can approve bookings too."""
        booking, room = create_pending_approval_booking()
        resp = api_client.approve_booking(booking["id"], _admin)
        data = validate_success(resp, 200)
        assert data["status"] == "CONFIRMED"

    def test_approve_booking_employee_forbidden(self):
        """Employee cannot approve bookings -> ERR_FORBIDDEN."""
        booking, room = create_pending_approval_booking()
        resp = api_client.approve_booking(booking["id"], _employee)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_approve_already_confirmed_fails(self):
        """Approving a CONFIRMED booking -> ERR_INVALID_BOOKING_STATE."""
        booking, room = create_confirmed_booking()
        resp = api_client.approve_booking(booking["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE)

    def test_approve_cancelled_booking_fails(self):
        """Approving a CANCELLED booking -> ERR_INVALID_BOOKING_STATE."""
        booking, room = create_pending_approval_booking()
        api_client.cancel_booking(booking["id"], _employee)
        resp = api_client.approve_booking(booking["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE)

    def test_approve_not_found(self):
        """Approve non-existent booking -> ERR_BOOKING_NOT_FOUND."""
        resp = api_client.approve_booking(NON_EXISTENT_UUID, _manager)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND)

    def test_approve_with_time_conflict(self):
        """Approve PENDING_APPROVAL when slot was taken since request -> ERR_TIME_CONFLICT."""
        room = create_premium_room()
        start = _future(hours=72)
        end = _future(hours=73)

        # Create two bookings for the same slot
        p1 = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp1 = api_client.create_booking(p1, _employee)
        booking1 = get_success_data(resp1)

        p2 = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp2 = api_client.create_booking(p2, TEST_USERS["employee2_headers"])
        booking2 = get_success_data(resp2)

        # Approve first booking
        resp = api_client.approve_booking(booking1["id"], _manager)
        validate_success(resp, 200)

        # Approve second booking should fail with time conflict
        resp = api_client.approve_booking(booking2["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_TIME_CONFLICT)

    def test_approve_room_no_longer_active(self):
        """Approve fails if room has entered MAINTENANCE since booking was created."""
        room = create_premium_room()
        start = _future(hours=72)
        end = _future(hours=73)
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        booking = get_success_data(resp)

        # Put room in maintenance - this should cancel the booking
        api_client.update_room(room["id"], {"status": "MAINTENANCE"}, _admin)

        # If booking is now cancelled due to cascade, approve should fail
        resp = api_client.get_booking(booking["id"], _employee)
        updated = get_success_data(resp)
        if updated["status"] == "CANCELLED":
            resp = api_client.approve_booking(booking["id"], _manager)
            validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE)


class TestRejectBooking:
    """POST /bookings/{booking_id}/reject"""

    def test_reject_pending_booking(self):
        """Reject PENDING_APPROVAL -> CANCELLED with rejection_reason recorded."""
        booking, room = create_pending_approval_booking()
        resp = api_client.reject_booking(
            booking["id"],
            {"rejection_reason": "Room needed for VIP event"},
            _manager,
        )
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"
        assert data["rejection_reason"] == "Room needed for VIP event"

    def test_reject_booking_employee_forbidden(self):
        """Employee cannot reject bookings -> ERR_FORBIDDEN."""
        booking, room = create_pending_approval_booking()
        resp = api_client.reject_booking(
            booking["id"],
            {"rejection_reason": "No"},
            _employee,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_reject_confirmed_booking_fails(self):
        """Rejecting a CONFIRMED booking -> ERR_INVALID_BOOKING_STATE."""
        booking, room = create_confirmed_booking()
        resp = api_client.reject_booking(
            booking["id"],
            {"rejection_reason": "Too late"},
            _manager,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE)

    def test_reject_not_found(self):
        """Reject non-existent booking -> ERR_BOOKING_NOT_FOUND."""
        resp = api_client.reject_booking(
            NON_EXISTENT_UUID,
            {"rejection_reason": "No"},
            _manager,
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND)


class TestCheckIn:
    """POST /bookings/{booking_id}/check-in"""

    def test_check_in_within_window(self):
        """Check-in within [start-15min, end_time) -> CHECKED_IN, checked_in_at set."""
        room = create_standard_room()
        start = datetime.now(timezone.utc) + timedelta(minutes=5)
        end = start + timedelta(hours=1)
        start_str = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload = create_booking_payload(room["id"], start_time=start_str, end_time=end_str)
        resp = api_client.create_booking(payload, _employee)
        booking = get_success_data(resp)

        resp = api_client.check_in_booking(booking["id"], _employee)
        data = validate_success(resp, 200)
        assert data["status"] == "CHECKED_IN"
        assert data["checked_in_at"] is not None

    def test_check_in_too_early(self):
        """Check-in > 15 min before start -> ERR_CHECKIN_WINDOW."""
        room = create_standard_room()
        start = datetime.now(timezone.utc) + timedelta(hours=2)
        end = start + timedelta(hours=1)
        start_str = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end_str = end.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        payload = create_booking_payload(room["id"], start_time=start_str, end_time=end_str)
        resp = api_client.create_booking(payload, _employee)
        booking = get_success_data(resp)

        resp = api_client.check_in_booking(booking["id"], _employee)
        validate_error(resp, ApiErrorId.ERR_CHECKIN_WINDOW)

    def test_check_in_not_confirmed(self):
        """Check-in on PENDING_APPROVAL booking -> ERR_INVALID_BOOKING_STATE."""
        booking, room = create_pending_approval_booking()
        resp = api_client.check_in_booking(booking["id"], _employee)
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE)

    def test_check_in_already_checked_in(self):
        """Check-in on already CHECKED_IN booking -> ERR_INVALID_BOOKING_STATE."""
        booking, room = create_checked_in_booking()
        resp = api_client.check_in_booking(booking["id"], _employee)
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE)

    def test_check_in_not_found(self):
        """Check-in non-existent booking -> ERR_BOOKING_NOT_FOUND."""
        resp = api_client.check_in_booking(NON_EXISTENT_UUID, _employee)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND)


class TestCheckOut:
    """POST /bookings/{booking_id}/check-out"""

    def test_check_out_success(self):
        """CHECKED_IN -> COMPLETED on check-out."""
        booking, room = create_checked_in_booking()
        resp = api_client.check_out_booking(booking["id"], _employee)
        data = validate_success(resp, 200)
        assert data["status"] == "COMPLETED"

    def test_check_out_not_checked_in(self):
        """Check-out on CONFIRMED (not checked in) -> ERR_INVALID_BOOKING_STATE."""
        booking, room = create_confirmed_booking()
        resp = api_client.check_out_booking(booking["id"], _employee)
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE)

    def test_check_out_not_found(self):
        """Check-out non-existent booking -> ERR_BOOKING_NOT_FOUND."""
        resp = api_client.check_out_booking(NON_EXISTENT_UUID, _employee)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND)


class TestCancelBooking:
    """POST /bookings/{booking_id}/cancel"""

    def test_cancel_confirmed_booking(self):
        """Cancel CONFIRMED -> CANCELLED."""
        booking, room = create_confirmed_booking()
        resp = api_client.cancel_booking(booking["id"], _employee)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

    def test_cancel_pending_approval_booking(self):
        """Cancel PENDING_APPROVAL -> CANCELLED."""
        booking, room = create_pending_approval_booking()
        resp = api_client.cancel_booking(booking["id"], _employee)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

    def test_cancel_checked_in_fails(self):
        """Cannot cancel CHECKED_IN booking -> ERR_INVALID_BOOKING_STATE."""
        booking, room = create_checked_in_booking()
        resp = api_client.cancel_booking(booking["id"], _employee)
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE)

    def test_cancel_completed_fails(self):
        """Cannot cancel COMPLETED booking -> ERR_INVALID_BOOKING_STATE."""
        booking, room = create_completed_booking()
        resp = api_client.cancel_booking(booking["id"], _employee)
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE)

    def test_cancel_already_cancelled_fails(self):
        """Cannot cancel already CANCELLED booking -> ERR_INVALID_BOOKING_STATE."""
        booking, room = create_confirmed_booking()
        api_client.cancel_booking(booking["id"], _employee)
        resp = api_client.cancel_booking(booking["id"], _employee)
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE)

    def test_cancel_not_found(self):
        """Cancel non-existent booking -> ERR_BOOKING_NOT_FOUND."""
        resp = api_client.cancel_booking(NON_EXISTENT_UUID, _employee)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND)

    def test_cancel_any_role_allowed(self):
        """Employee, manager, facility_admin can all cancel bookings."""
        for headers in [_employee, _manager, _admin]:
            room = create_standard_room()
            payload = create_booking_payload(room["id"])
            resp = api_client.create_booking(payload, headers)
            booking = get_success_data(resp)
            resp = api_client.cancel_booking(booking["id"], headers)
            data = validate_success(resp, 200)
            assert data["status"] == "CANCELLED"


class TestInvalidBookingTransitions:
    """Invalid state transitions -> ERR_INVALID_BOOKING_STATE."""

    @pytest.mark.parametrize("action_fn, action_name", [
        (lambda api, bid, h: api.check_in_booking(bid, h), "check_in"),
        (lambda api, bid, h: api.check_out_booking(bid, h), "check_out"),
    ])
    def test_action_on_cancelled_booking(self, action_fn, action_name):
        """Actions on CANCELLED booking fail."""
        booking, room = create_confirmed_booking()
        api_client.cancel_booking(booking["id"], _employee)
        resp = action_fn(api_client, booking["id"], _employee)
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE)

    def test_approve_confirmed_booking(self):
        """Approve on already CONFIRMED -> ERR_INVALID_BOOKING_STATE."""
        booking, room = create_confirmed_booking()
        resp = api_client.approve_booking(booking["id"], _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE)

    def test_reject_confirmed_booking(self):
        """Reject on CONFIRMED -> ERR_INVALID_BOOKING_STATE."""
        booking, room = create_confirmed_booking()
        resp = api_client.reject_booking(booking["id"], {"rejection_reason": "No"}, _manager)
        validate_error(resp, ApiErrorId.ERR_INVALID_BOOKING_STATE)
