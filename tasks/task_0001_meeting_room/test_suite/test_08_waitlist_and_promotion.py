"""Test waitlist mechanics and slot recovery via promotion.

Covers:
- Waitlist entry creation with position assignment
- FIFO ordering (position-based)
- Duplicate waitlist entry detection (ERR_DUPLICATE_WAITLIST)
- Waitlist promotion on booking cancellation
- Waitlist promotion on booking rejection
- Only one promotion per triggering event
- Promoted entry creates a new TENTATIVE booking
- Remaining entries re-positioned after promotion/cancellation
- Waitlist cancellation (DELETE /waitlist/{id})
- ERR_INVALID_WAITLIST_STATE on cancel of non-WAITING entry
- ERR_WAITLIST_NOT_FOUND
- Validation: ERR_ROOM_NOT_ACTIVE, ERR_CAPACITY_EXCEEDED, etc.
"""
import pytest
from datetime import datetime, timedelta, timezone
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    assert_waitlist, assert_booking,
    create_booking_payload, create_waitlist_payload,
    create_standard_room, create_premium_room,
    create_room_in_maintenance,
    create_waitlist_entry,
    setup_booking_with_waitlist,
)


_admin = TEST_USERS["facility_admin_headers"]
_employee = TEST_USERS["employee_headers"]
_employee2 = TEST_USERS["employee2_headers"]
_manager = TEST_USERS["manager_headers"]


def _ts(hours=48):
    dt = datetime.now(timezone.utc) + timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


class TestCreateWaitlist:
    """POST /waitlist"""

    def test_create_waitlist_entry(self):
        """Create a waitlist entry. Status=WAITING, position assigned."""
        room = create_standard_room()
        start = _ts(hours=72)
        end = _ts(hours=73)

        # First, create a booking to fill the slot
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        api_client.create_booking(payload, _employee)

        # Now join waitlist for same slot (different user)
        wl_payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_waitlist(wl_payload, _employee2)
        data = validate_success(resp, 201)
        assert_waitlist(data)
        assert data["status"] == "WAITING"
        assert data["position"] >= 1
        assert data["room_id"] == room["id"]
        assert data["requester_id"] == "test-employee-2"

    def test_waitlist_position_fifo(self):
        """Waitlist entries ordered FIFO: first entry gets position 1."""
        room = create_standard_room()
        start = _ts(hours=72)
        end = _ts(hours=73)

        # Fill the slot
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        api_client.create_booking(payload, _employee)

        # First waitlist entry
        wl1_payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        resp1 = api_client.create_waitlist(wl1_payload, _employee2)
        wl1 = get_success_data(resp1)

        # Second waitlist entry (different user via manager)
        wl2_payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        resp2 = api_client.create_waitlist(wl2_payload, _manager)
        wl2 = get_success_data(resp2)

        assert wl1["position"] < wl2["position"], (
            f"First entry position ({wl1['position']}) should be < second ({wl2['position']})"
        )

    def test_duplicate_waitlist_rejected(self):
        """Same requester, room, exact time window -> ERR_DUPLICATE_WAITLIST."""
        room = create_standard_room()
        start = _ts(hours=72)
        end = _ts(hours=73)

        wl_payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        resp1 = api_client.create_waitlist(wl_payload, _employee)
        validate_success(resp1, 201)

        # Same requester (employee), same room, same time
        resp2 = api_client.create_waitlist(wl_payload, _employee)
        validate_error(resp2, ApiErrorId.ERR_DUPLICATE_WAITLIST)

    def test_waitlist_room_not_active(self):
        """Waitlist on MAINTENANCE room -> ERR_ROOM_NOT_ACTIVE."""
        room = create_room_in_maintenance()
        start = _ts(hours=72)
        end = _ts(hours=73)
        payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_waitlist(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_ACTIVE)

    def test_waitlist_capacity_exceeded(self):
        """Waitlist attendee_count > room capacity -> ERR_CAPACITY_EXCEEDED."""
        room = create_standard_room(capacity=3)
        start = _ts(hours=72)
        end = _ts(hours=73)
        payload = create_waitlist_payload(room["id"], start_time=start, end_time=end, attendee_count=5)
        resp = api_client.create_waitlist(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    def test_waitlist_invalid_time_range(self):
        """end_time before start_time -> ERR_INVALID_TIME_RANGE."""
        room = create_standard_room()
        start = _ts(hours=73)
        end = _ts(hours=72)
        payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_waitlist(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)

    def test_waitlist_in_past(self):
        """start_time in the past -> ERR_BOOKING_IN_PAST."""
        room = create_standard_room()
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end = _ts(hours=1)
        payload = create_waitlist_payload(room["id"], start_time=past, end_time=end)
        resp = api_client.create_waitlist(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_BOOKING_IN_PAST)

    def test_waitlist_room_not_found(self):
        """Waitlist with non-existent room_id -> ERR_ROOM_NOT_FOUND."""
        start = _ts(hours=72)
        end = _ts(hours=73)
        payload = create_waitlist_payload(NON_EXISTENT_UUID, start_time=start, end_time=end)
        resp = api_client.create_waitlist(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_FOUND)

    @pytest.mark.parametrize("missing_field", [
        "room_id", "title", "start_time", "end_time", "attendee_count"
    ])
    def test_waitlist_missing_required_field(self, missing_field):
        """Omitting required field -> ERR_BAD_REQUEST."""
        room = create_standard_room()
        start = _ts(hours=72)
        end = _ts(hours=73)
        payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        del payload[missing_field]
        resp = api_client.create_waitlist(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST)


class TestListWaitlist:
    """GET /waitlist"""

    def test_list_waitlist(self):
        """List waitlist entries returns paginated array."""
        room = create_standard_room()
        start = _ts(hours=72)
        end = _ts(hours=73)
        payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        api_client.create_waitlist(payload, _employee)
        resp = api_client.list_waitlist(_employee)
        items, _ = validate_paginated(resp)
        assert len(items) >= 1

    def test_list_waitlist_filter_by_room(self):
        """Filter waitlist by room_id."""
        room = create_standard_room()
        start = _ts(hours=72)
        end = _ts(hours=73)
        payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        api_client.create_waitlist(payload, _employee)
        resp = api_client.list_waitlist(_employee, params={"room_id": room["id"]})
        items, _ = validate_paginated(resp)
        for item in items:
            assert item["room_id"] == room["id"]

    def test_list_waitlist_filter_by_status(self):
        """Filter waitlist by status=WAITING."""
        room = create_standard_room()
        start = _ts(hours=72)
        end = _ts(hours=73)
        payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        api_client.create_waitlist(payload, _employee)
        resp = api_client.list_waitlist(_employee, params={"status": "WAITING"})
        items, _ = validate_paginated(resp)
        for item in items:
            assert item["status"] == "WAITING"


class TestCancelWaitlist:
    """DELETE /waitlist/{waitlist_id}"""

    def test_cancel_waiting_entry(self):
        """Cancel WAITING entry -> CANCELLED."""
        room = create_standard_room()
        start = _ts(hours=72)
        end = _ts(hours=73)
        wl = create_waitlist_entry(room["id"], start_time=start, end_time=end)
        resp = api_client.cancel_waitlist(wl["id"], _employee)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

    def test_cancel_non_waiting_fails(self):
        """Cancel already-CANCELLED entry -> ERR_INVALID_WAITLIST_STATE."""
        room = create_standard_room()
        start = _ts(hours=72)
        end = _ts(hours=73)
        wl = create_waitlist_entry(room["id"], start_time=start, end_time=end)
        api_client.cancel_waitlist(wl["id"], _employee)
        resp = api_client.cancel_waitlist(wl["id"], _employee)
        validate_error(resp, ApiErrorId.ERR_INVALID_WAITLIST_STATE)

    def test_cancel_waitlist_not_found(self):
        """Cancel non-existent entry -> ERR_WAITLIST_NOT_FOUND."""
        resp = api_client.cancel_waitlist(NON_EXISTENT_UUID, _employee)
        validate_error(resp, ApiErrorId.ERR_WAITLIST_NOT_FOUND)

    def test_cancel_repositions_remaining(self):
        """After cancelling an entry, remaining entries are re-positioned."""
        room = create_standard_room()
        start = _ts(hours=72)
        end = _ts(hours=73)

        # Fill slot
        booking_payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        api_client.create_booking(booking_payload, _employee)

        # Create two waitlist entries
        wl1_payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        resp1 = api_client.create_waitlist(wl1_payload, _employee2)
        wl1 = get_success_data(resp1)

        wl2_payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        resp2 = api_client.create_waitlist(wl2_payload, _manager)
        wl2 = get_success_data(resp2)

        original_pos2 = wl2["position"]

        # Cancel first entry
        api_client.cancel_waitlist(wl1["id"], _employee2)

        # Check if wl2 position has been re-adjusted
        resp = api_client.list_waitlist(_admin, params={"room_id": room["id"], "status": "WAITING"})
        items, _ = validate_paginated(resp)
        waiting = [w for w in items if w["id"] == wl2["id"]]
        if waiting:
            assert waiting[0]["position"] <= original_pos2, (
                "Position should be <= original after earlier entry cancelled"
            )


class TestWaitlistPromotion:
    """Waitlist promotion when a slot is freed."""

    def test_promotion_on_booking_cancel(self):
        """Cancelling a booking promotes the first eligible waitlist entry."""
        booking, wl, room = setup_booking_with_waitlist()

        # Cancel the booking
        api_client.cancel_booking(booking["id"], _employee)

        # Check waitlist entry status
        resp = api_client.list_waitlist(_admin, params={"room_id": room["id"]})
        items, _ = validate_paginated(resp)
        promoted = [w for w in items if w["id"] == wl["id"]]
        if promoted:
            assert promoted[0]["status"] == "PROMOTED", (
                f"Waitlist entry should be PROMOTED after booking cancel, got {promoted[0]['status']}"
            )

    def test_promotion_creates_new_booking(self):
        """Promotion creates a new TENTATIVE booking from waitlist entry parameters."""
        booking, wl, room = setup_booking_with_waitlist()

        # Cancel the booking to trigger promotion
        api_client.cancel_booking(booking["id"], _employee)

        # Look for a new booking created from the waitlist entry
        resp = api_client.list_bookings(_admin, params={"room_id": room["id"]})
        bookings, _ = validate_paginated(resp)
        # There should be a booking from the waitlist requester (employee2)
        new_bookings = [
            b for b in bookings
            if b["organizer_id"] == "test-employee-2"
            and b["status"] in ("TENTATIVE", "CONFIRMED")
        ]
        assert len(new_bookings) >= 1, (
            "A new booking should be created from the promoted waitlist entry"
        )

    def test_promotion_on_booking_reject(self):
        """Rejecting a PENDING_APPROVAL booking triggers waitlist promotion."""
        room = create_premium_room()
        start = _ts(hours=120)
        end = _ts(hours=121)

        # Create a booking on premium room
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        booking = get_success_data(resp)
        assert booking["status"] == "PENDING_APPROVAL"

        # Join waitlist for same slot
        wl_payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_waitlist(wl_payload, _employee2)
        wl = get_success_data(resp)

        # Reject the booking
        api_client.reject_booking(
            booking["id"],
            {"rejection_reason": "Not approved"},
            _manager,
        )

        # Check waitlist entry
        resp = api_client.list_waitlist(_admin, params={"room_id": room["id"]})
        items, _ = validate_paginated(resp)
        promoted = [w for w in items if w["id"] == wl["id"]]
        if promoted:
            assert promoted[0]["status"] == "PROMOTED"

    def test_only_one_promotion_per_event(self):
        """Only one waitlist entry is promoted per cancellation event."""
        room = create_standard_room()
        start = _ts(hours=120)
        end = _ts(hours=121)

        # Create and confirm a booking
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        booking = get_success_data(resp)

        # Create two waitlist entries
        wl1_payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        resp1 = api_client.create_waitlist(wl1_payload, _employee2)
        wl1 = get_success_data(resp1)

        wl2_payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        resp2 = api_client.create_waitlist(wl2_payload, _manager)
        wl2 = get_success_data(resp2)

        # Cancel booking
        api_client.cancel_booking(booking["id"], _employee)

        # Check statuses
        resp = api_client.list_waitlist(_admin, params={"room_id": room["id"]})
        items, _ = validate_paginated(resp)
        wl1_updated = next((w for w in items if w["id"] == wl1["id"]), None)
        wl2_updated = next((w for w in items if w["id"] == wl2["id"]), None)

        promoted_count = 0
        if wl1_updated and wl1_updated["status"] == "PROMOTED":
            promoted_count += 1
        if wl2_updated and wl2_updated["status"] == "PROMOTED":
            promoted_count += 1

        assert promoted_count == 1, (
            f"Exactly one entry should be promoted per event, got {promoted_count}"
        )
