"""Test Booking creation, retrieval, listing, and input validation.

Covers:
- Booking creation on STANDARD room (auto-confirm)
- Booking creation on PREMIUM room (pending approval)
- Booking retrieval and listing with filters
- Temporal validation: ERR_INVALID_TIME_RANGE, ERR_BOOKING_TOO_SHORT,
  ERR_BOOKING_TOO_LONG, ERR_BOOKING_IN_PAST
- Capacity validation: ERR_CAPACITY_EXCEEDED
- Room state validation: ERR_ROOM_NOT_ACTIVE
- Missing required fields: ERR_BAD_REQUEST
- Not-found: ERR_BOOKING_NOT_FOUND, ERR_ROOM_NOT_FOUND
- organizer_id set from X-User-ID header
"""
import pytest
from datetime import datetime, timedelta, timezone
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    assert_booking,
    create_booking_payload,
    create_standard_room, create_premium_room,
    create_room_in_maintenance, create_room_decommissioned,
)


_admin = TEST_USERS["facility_admin_headers"]
_employee = TEST_USERS["employee_headers"]
_manager = TEST_USERS["manager_headers"]


def _future(hours=24, minutes=0):
    dt = datetime.now(timezone.utc) + timedelta(hours=hours, minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


class TestCreateBooking:
    """POST /bookings"""

    def test_create_booking_standard_auto_confirmed(self):
        """STANDARD room booking auto-confirms. Status=CONFIRMED, cost_cents computed."""
        room = create_standard_room()
        payload = create_booking_payload(room["id"])
        resp = api_client.create_booking(payload, _employee)
        data = validate_success(resp, 201)
        assert_booking(data)
        assert data["status"] == "CONFIRMED"
        assert data["room_id"] == room["id"]
        assert data["organizer_id"] == "test-employee-1", (
            f"organizer_id should be set from X-User-ID, got {data['organizer_id']}"
        )
        assert isinstance(data["cost_cents"], int), "cost_cents must be computed on confirmation"
        assert data["cost_cents"] > 0
        assert data["version"] >= 1

    def test_create_booking_premium_pending_approval(self):
        """PREMIUM room booking -> PENDING_APPROVAL, no cost_cents yet."""
        room = create_premium_room()
        payload = create_booking_payload(room["id"])
        resp = api_client.create_booking(payload, _employee)
        data = validate_success(resp, 201)
        assert_booking(data)
        assert data["status"] == "PENDING_APPROVAL"

    def test_create_booking_sets_organizer_from_header(self):
        """organizer_id is derived from X-User-ID header."""
        room = create_standard_room()
        payload = create_booking_payload(room["id"])
        resp = api_client.create_booking(payload, _manager)
        data = validate_success(resp, 201)
        assert data["organizer_id"] == "test-manager-1"

    def test_create_booking_all_roles_allowed(self):
        """employee, manager, facility_admin can all create bookings."""
        room = create_standard_room(capacity=50)
        for headers in [_employee, _manager, _admin]:
            start = _future(hours=48 + list([_employee, _manager, _admin]).index(headers) * 2)
            end = _future(hours=49 + list([_employee, _manager, _admin]).index(headers) * 2)
            payload = create_booking_payload(room["id"], start_time=start, end_time=end)
            resp = api_client.create_booking(payload, headers)
            validate_success(resp, 201)

    @pytest.mark.parametrize("missing_field", [
        "room_id", "title", "start_time", "end_time", "attendee_count"
    ])
    def test_create_booking_missing_required_field(self, missing_field):
        """Omitting required field -> ERR_BAD_REQUEST."""
        room = create_standard_room()
        payload = create_booking_payload(room["id"])
        del payload[missing_field]
        resp = api_client.create_booking(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST)

    def test_create_booking_room_not_found(self):
        """Booking with non-existent room_id -> ERR_ROOM_NOT_FOUND."""
        payload = create_booking_payload(NON_EXISTENT_UUID)
        resp = api_client.create_booking(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_FOUND)


class TestBookingTemporalValidation:
    """Temporal guards on booking creation."""

    def test_end_before_start(self):
        """end_time <= start_time -> ERR_INVALID_TIME_RANGE."""
        room = create_standard_room()
        start = _future(hours=24)
        end = _future(hours=23)  # before start
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)

    def test_end_equals_start(self):
        """end_time == start_time (zero duration) -> ERR_INVALID_TIME_RANGE or ERR_BOOKING_TOO_SHORT."""
        room = create_standard_room()
        t = _future(hours=24)
        payload = create_booking_payload(room["id"], start_time=t, end_time=t)
        resp = api_client.create_booking(payload, _employee)
        # Either error is acceptable per scaffold
        assert resp.status_code == 400

    def test_booking_too_short_14_minutes(self):
        """Duration < 15 minutes -> ERR_BOOKING_TOO_SHORT."""
        room = create_standard_room()
        start = _future(hours=24)
        end = _future(hours=24, minutes=14)
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_BOOKING_TOO_SHORT)

    def test_booking_exactly_15_minutes_ok(self):
        """Duration == 15 minutes is valid (boundary)."""
        room = create_standard_room()
        start = _future(hours=24)
        end = _future(hours=24, minutes=15)
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        validate_success(resp, 201)

    def test_booking_too_long_over_8_hours(self):
        """Duration > 8 hours -> ERR_BOOKING_TOO_LONG."""
        room = create_standard_room()
        start = _future(hours=24)
        end = _future(hours=24 + 8, minutes=1)  # 8h1m
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_BOOKING_TOO_LONG)

    def test_booking_exactly_8_hours_ok(self):
        """Duration == 8 hours is valid (boundary)."""
        room = create_standard_room()
        start = _future(hours=24)
        end = _future(hours=32)  # exactly 8h
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        validate_success(resp, 201)

    def test_booking_in_past(self):
        """start_time in the past -> ERR_BOOKING_IN_PAST."""
        room = create_standard_room()
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end = _future(hours=1)
        payload = create_booking_payload(room["id"], start_time=past, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_BOOKING_IN_PAST)


class TestBookingCapacityAndState:
    """Capacity and room-state validations."""

    def test_attendee_count_exceeds_capacity(self):
        """attendee_count > room.capacity -> ERR_CAPACITY_EXCEEDED."""
        room = create_standard_room(capacity=5)
        payload = create_booking_payload(room["id"], attendee_count=6)
        resp = api_client.create_booking(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    def test_attendee_count_exactly_at_capacity(self):
        """attendee_count == room.capacity -> success (boundary)."""
        room = create_standard_room(capacity=5)
        payload = create_booking_payload(room["id"], attendee_count=5)
        resp = api_client.create_booking(payload, _employee)
        validate_success(resp, 201)

    def test_booking_maintenance_room_rejected(self):
        """Booking a MAINTENANCE room -> ERR_ROOM_NOT_ACTIVE."""
        room = create_room_in_maintenance()
        payload = create_booking_payload(room["id"])
        resp = api_client.create_booking(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_ACTIVE)

    def test_booking_decommissioned_room_rejected(self):
        """Booking a DECOMMISSIONED room -> ERR_ROOM_NOT_ACTIVE."""
        room = create_room_decommissioned()
        payload = create_booking_payload(room["id"])
        resp = api_client.create_booking(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_ACTIVE)


class TestGetBooking:
    """GET /bookings/{booking_id}"""

    def test_get_booking_success(self):
        """Retrieve a booking by ID."""
        room = create_standard_room()
        payload = create_booking_payload(room["id"])
        resp = api_client.create_booking(payload, _employee)
        booking = get_success_data(resp)

        resp = api_client.get_booking(booking["id"], _employee)
        data = validate_success(resp, 200)
        assert_booking(data)
        assert data["id"] == booking["id"]

    def test_get_booking_not_found(self):
        """Non-existent booking_id -> ERR_BOOKING_NOT_FOUND."""
        resp = api_client.get_booking(NON_EXISTENT_UUID, _employee)
        validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND)


class TestListBookings:
    """GET /bookings"""

    def test_list_bookings_paginated(self):
        """List bookings returns paginated array."""
        room = create_standard_room()
        payload = create_booking_payload(room["id"])
        api_client.create_booking(payload, _employee)
        resp = api_client.list_bookings(_employee)
        items, _ = validate_paginated(resp)
        assert len(items) >= 1

    def test_list_bookings_filter_by_room_id(self):
        """Filter bookings by room_id."""
        room = create_standard_room()
        payload = create_booking_payload(room["id"])
        api_client.create_booking(payload, _employee)
        resp = api_client.list_bookings(_employee, params={"room_id": room["id"]})
        items, _ = validate_paginated(resp)
        for item in items:
            assert item["room_id"] == room["id"]

    def test_list_bookings_filter_by_status(self):
        """Filter bookings by status."""
        room = create_standard_room()
        payload = create_booking_payload(room["id"])
        api_client.create_booking(payload, _employee)
        resp = api_client.list_bookings(_employee, params={"status": "CONFIRMED"})
        items, _ = validate_paginated(resp)
        for item in items:
            assert item["status"] == "CONFIRMED"

    def test_list_bookings_filter_by_organizer_id(self):
        """Filter bookings by organizer_id."""
        room = create_standard_room()
        payload = create_booking_payload(room["id"])
        api_client.create_booking(payload, _employee)
        resp = api_client.list_bookings(_employee, params={"organizer_id": "test-employee-1"})
        items, _ = validate_paginated(resp)
        for item in items:
            assert item["organizer_id"] == "test-employee-1"
