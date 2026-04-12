"""Test recurring booking series.

Covers:
- Series creation: generates individual bookings
- Recurrence rules: DAILY, WEEKLY, BIWEEKLY
- Series generates bookings linked by series_id
- total_bookings count is correct
- Each booking follows normal TENTATIVE -> CONFIRMED/PENDING_APPROVAL flow
- Series cancellation: ACTIVE -> CANCELLED, future non-terminal bookings cancelled
- Cancelling single booking in series doesn't cancel the series
- Validation: ERR_INVALID_SERIES_RANGE, ERR_EMPTY_SERIES
- ERR_ROOM_NOT_ACTIVE, ERR_CAPACITY_EXCEEDED, ERR_BOOKING_TOO_SHORT, etc.
- ERR_SERIES_NOT_FOUND, ERR_INVALID_SERIES_STATE
"""
import pytest
from datetime import datetime, timedelta, timezone
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    assert_series,
    create_series_payload, create_booking_payload,
    create_standard_room, create_premium_room,
    create_room_in_maintenance,
    create_active_series,
)


_admin = TEST_USERS["facility_admin_headers"]
_employee = TEST_USERS["employee_headers"]
_manager = TEST_USERS["manager_headers"]


def _future_date(days=7):
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


class TestCreateSeries:
    """POST /series"""

    def test_create_weekly_series(self):
        """Create a WEEKLY series. Verify series fields and total_bookings > 0."""
        room = create_standard_room()
        payload = create_series_payload(
            room["id"],
            recurrence_rule="WEEKLY",
            series_start_date=_future_date(7),
            series_end_date=_future_date(35),  # ~4 weeks
        )
        resp = api_client.create_series(payload, _employee)
        data = validate_success(resp, 201)
        assert_series(data)
        assert data["status"] == "ACTIVE"
        assert data["recurrence_rule"] == "WEEKLY"
        assert data["total_bookings"] >= 4, (
            f"4+ week WEEKLY series should produce >= 4 bookings, got {data['total_bookings']}"
        )
        assert data["room_id"] == room["id"]
        assert data["organizer_id"] == "test-employee-1"

    def test_create_daily_series(self):
        """Create a DAILY series over 7 days -> 7 bookings."""
        room = create_standard_room()
        payload = create_series_payload(
            room["id"],
            recurrence_rule="DAILY",
            series_start_date=_future_date(7),
            series_end_date=_future_date(13),  # 7 days
        )
        resp = api_client.create_series(payload, _employee)
        data = validate_success(resp, 201)
        assert data["recurrence_rule"] == "DAILY"
        assert data["total_bookings"] == 7

    def test_create_biweekly_series(self):
        """Create a BIWEEKLY series."""
        room = create_standard_room()
        payload = create_series_payload(
            room["id"],
            recurrence_rule="BIWEEKLY",
            series_start_date=_future_date(7),
            series_end_date=_future_date(49),  # ~6 weeks
        )
        resp = api_client.create_series(payload, _employee)
        data = validate_success(resp, 201)
        assert data["recurrence_rule"] == "BIWEEKLY"
        assert data["total_bookings"] >= 3

    def test_series_bookings_linked_by_series_id(self):
        """All generated bookings carry the series_id."""
        room = create_standard_room()
        payload = create_series_payload(
            room["id"],
            recurrence_rule="DAILY",
            series_start_date=_future_date(7),
            series_end_date=_future_date(9),  # 3 days
        )
        resp = api_client.create_series(payload, _employee)
        series = get_success_data(resp)

        # List bookings for this room
        resp = api_client.list_bookings(_employee, params={"room_id": room["id"]})
        bookings, _ = validate_paginated(resp)
        series_bookings = [b for b in bookings if b.get("series_id") == series["id"]]
        assert len(series_bookings) == series["total_bookings"], (
            f"Expected {series['total_bookings']} bookings with series_id, found {len(series_bookings)}"
        )

    def test_series_standard_room_auto_confirms(self):
        """Bookings generated for STANDARD room are auto-confirmed (when no conflict)."""
        room = create_standard_room()
        payload = create_series_payload(
            room["id"],
            recurrence_rule="WEEKLY",
            series_start_date=_future_date(7),
            series_end_date=_future_date(21),
            duration_minutes=60,
        )
        resp = api_client.create_series(payload, _employee)
        series = get_success_data(resp)

        resp = api_client.list_bookings(_employee, params={"room_id": room["id"]})
        bookings, _ = validate_paginated(resp)
        series_bookings = [b for b in bookings if b.get("series_id") == series["id"]]
        for b in series_bookings:
            assert b["status"] in ("CONFIRMED", "TENTATIVE"), (
                f"STANDARD room series booking should be CONFIRMED or TENTATIVE, got {b['status']}"
            )

    def test_series_premium_room_pending_approval(self):
        """Bookings generated for PREMIUM room go to PENDING_APPROVAL."""
        room = create_premium_room()
        payload = create_series_payload(
            room["id"],
            recurrence_rule="WEEKLY",
            series_start_date=_future_date(7),
            series_end_date=_future_date(21),
        )
        resp = api_client.create_series(payload, _employee)
        series = get_success_data(resp)

        resp = api_client.list_bookings(_employee, params={"room_id": room["id"]})
        bookings, _ = validate_paginated(resp)
        series_bookings = [b for b in bookings if b.get("series_id") == series["id"]]
        for b in series_bookings:
            assert b["status"] == "PENDING_APPROVAL", (
                f"PREMIUM room series booking should be PENDING_APPROVAL, got {b['status']}"
            )


class TestSeriesValidation:
    """Validation rules for series creation."""

    def test_series_end_before_start(self):
        """series_end_date before series_start_date -> ERR_INVALID_SERIES_RANGE."""
        room = create_standard_room()
        payload = create_series_payload(
            room["id"],
            series_start_date=_future_date(14),
            series_end_date=_future_date(7),
        )
        resp = api_client.create_series(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_INVALID_SERIES_RANGE)

    def test_series_produces_zero_occurrences(self):
        """Range too short for even one occurrence -> ERR_EMPTY_SERIES."""
        room = create_standard_room()
        # BIWEEKLY with only 1 day range
        start_date = _future_date(7)
        # Same day for start and end with BIWEEKLY -> should be invalid or produce 1
        payload = create_series_payload(
            room["id"],
            recurrence_rule="BIWEEKLY",
            series_start_date=start_date,
            series_end_date=start_date,  # same day
        )
        resp = api_client.create_series(payload, _employee)
        # Either ERR_INVALID_SERIES_RANGE (end not after start) or ERR_EMPTY_SERIES
        assert resp.status_code == 400

    def test_series_room_not_active(self):
        """Series on non-ACTIVE room -> ERR_ROOM_NOT_ACTIVE."""
        room = create_room_in_maintenance()
        payload = create_series_payload(room["id"])
        resp = api_client.create_series(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_ACTIVE)

    def test_series_capacity_exceeded(self):
        """Series attendee_count > room capacity -> ERR_CAPACITY_EXCEEDED."""
        room = create_standard_room(capacity=3)
        payload = create_series_payload(room["id"], attendee_count=5)
        resp = api_client.create_series(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    def test_series_room_not_found(self):
        """Series with non-existent room_id -> ERR_ROOM_NOT_FOUND."""
        payload = create_series_payload(NON_EXISTENT_UUID)
        resp = api_client.create_series(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_FOUND)

    @pytest.mark.parametrize("missing_field", [
        "room_id", "title", "recurrence_rule", "start_time", "duration_minutes",
        "attendee_count", "series_start_date", "series_end_date",
    ])
    def test_series_missing_required_field(self, missing_field):
        """Omitting required field -> ERR_BAD_REQUEST."""
        room = create_standard_room()
        payload = create_series_payload(room["id"])
        del payload[missing_field]
        resp = api_client.create_series(payload, _employee)
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST)


class TestGetSeries:
    """GET /series/{series_id}"""

    def test_get_series_success(self):
        """Retrieve a series by ID."""
        series, room = create_active_series()
        resp = api_client.get_series(series["id"], _employee)
        data = validate_success(resp, 200)
        assert_series(data)
        assert data["id"] == series["id"]

    def test_get_series_not_found(self):
        """Non-existent series_id -> ERR_SERIES_NOT_FOUND."""
        resp = api_client.get_series(NON_EXISTENT_UUID, _employee)
        validate_error(resp, ApiErrorId.ERR_SERIES_NOT_FOUND)


class TestCancelSeries:
    """POST /series/{series_id}/cancel"""

    def test_cancel_active_series(self):
        """Cancel ACTIVE series -> CANCELLED. Future bookings cancelled."""
        series, room = create_active_series()
        resp = api_client.cancel_series(series["id"], _employee)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

        # Verify all future bookings in the series are cancelled
        resp = api_client.list_bookings(_employee, params={"room_id": room["id"]})
        bookings, _ = validate_paginated(resp)
        series_bookings = [b for b in bookings if b.get("series_id") == series["id"]]
        for b in series_bookings:
            assert b["status"] == "CANCELLED", (
                f"After series cancel, booking should be CANCELLED, got {b['status']}"
            )

    def test_cancel_already_cancelled_series(self):
        """Cancel already-CANCELLED series -> ERR_INVALID_SERIES_STATE."""
        series, room = create_active_series()
        api_client.cancel_series(series["id"], _employee)
        resp = api_client.cancel_series(series["id"], _employee)
        validate_error(resp, ApiErrorId.ERR_INVALID_SERIES_STATE)

    def test_cancel_series_not_found(self):
        """Cancel non-existent series -> ERR_SERIES_NOT_FOUND."""
        resp = api_client.cancel_series(NON_EXISTENT_UUID, _employee)
        validate_error(resp, ApiErrorId.ERR_SERIES_NOT_FOUND)

    def test_cancel_single_booking_keeps_series_active(self):
        """Cancelling one booking in a series does not cancel the series."""
        room = create_standard_room()
        payload = create_series_payload(
            room["id"],
            recurrence_rule="DAILY",
            series_start_date=_future_date(7),
            series_end_date=_future_date(10),  # 4 bookings
        )
        resp = api_client.create_series(payload, _employee)
        series = get_success_data(resp)

        # Find one booking from the series
        resp = api_client.list_bookings(_employee, params={"room_id": room["id"]})
        bookings, _ = validate_paginated(resp)
        series_bookings = [b for b in bookings if b.get("series_id") == series["id"]]
        assert len(series_bookings) > 0

        # Cancel just one booking
        api_client.cancel_booking(series_bookings[0]["id"], _employee)

        # Series should still be ACTIVE
        resp = api_client.get_series(series["id"], _employee)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVE", "Series should remain ACTIVE when single booking is cancelled"
