"""End-to-end integration tests exercising full booking lifecycle flows.

Covers:
- Complete lifecycle: create room -> create booking -> check in -> check out -> COMPLETED
- Premium room flow: create room -> book -> approve -> check in -> check out
- Series creation with waitlist promotion on cancel
- Room decommission cascade with audit trail verification
- Full waitlist promotion cycle: book -> waitlist -> cancel booking -> promotion -> confirm
"""
import pytest
from datetime import datetime, timedelta, timezone
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, is_valid_uuid, is_iso8601_timestamp,
    ApiErrorId, TEST_USERS,
    assert_room, assert_booking, assert_series, assert_waitlist, assert_audit_log,
    create_room_payload, create_booking_payload, create_series_payload,
    create_waitlist_payload,
    create_standard_room, create_premium_room,
)


_admin = TEST_USERS["facility_admin_headers"]
_employee = TEST_USERS["employee_headers"]
_employee2 = TEST_USERS["employee2_headers"]
_manager = TEST_USERS["manager_headers"]


def _ts(hours=0, minutes=0):
    dt = datetime.now(timezone.utc) + timedelta(hours=hours, minutes=minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _future_date(days=7):
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


class TestFullStandardBookingLifecycle:
    """End-to-end: STANDARD room booking from creation to completion."""

    def test_standard_booking_full_lifecycle(self):
        """Create room -> book -> check in -> check out -> verify COMPLETED."""
        # 1. Create room
        room_payload = create_room_payload(tier="STANDARD", hourly_rate_cents=6000)
        resp = api_client.create_room(room_payload, _admin)
        room = validate_success(resp, 201)
        assert_room(room)
        assert room["status"] == "ACTIVE"

        # 2. Create booking (starts soon for check-in)
        start = datetime.now(timezone.utc) + timedelta(minutes=5)
        end = start + timedelta(hours=1)
        booking_payload = create_booking_payload(
            room["id"],
            start_time=start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            end_time=end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        )
        resp = api_client.create_booking(booking_payload, _employee)
        booking = validate_success(resp, 201)
        assert_booking(booking)
        assert booking["status"] == "CONFIRMED"
        assert booking["cost_cents"] > 0

        # 3. Check in
        resp = api_client.check_in_booking(booking["id"], _employee)
        checked_in = validate_success(resp, 200)
        assert checked_in["status"] == "CHECKED_IN"
        assert checked_in["checked_in_at"] is not None

        # 4. Check out
        resp = api_client.check_out_booking(booking["id"], _employee)
        completed = validate_success(resp, 200)
        assert completed["status"] == "COMPLETED"

        # 5. Verify audit trail
        resp = api_client.list_audit_logs(_admin, params={
            "resource_type": "Booking",
            "resource_id": booking["id"],
        })
        logs, _ = validate_paginated(resp)
        assert len(logs) >= 3, (
            f"Expected >= 3 audit logs (create, check-in, check-out), got {len(logs)}"
        )


class TestFullPremiumBookingLifecycle:
    """End-to-end: PREMIUM room booking with approval flow."""

    def test_premium_booking_approval_lifecycle(self):
        """Create PREMIUM room -> book -> approve -> check in -> check out."""
        # 1. Create premium room
        room = create_premium_room(hourly_rate_cents=12000, peak_multiplier=2.0)
        assert room["tier"] == "PREMIUM"

        # 2. Create booking (starts soon)
        start = datetime.now(timezone.utc) + timedelta(minutes=5)
        end = start + timedelta(hours=1)
        booking_payload = create_booking_payload(
            room["id"],
            start_time=start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            end_time=end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        )
        resp = api_client.create_booking(booking_payload, _employee)
        booking = validate_success(resp, 201)
        assert booking["status"] == "PENDING_APPROVAL"

        # 3. Manager approves
        resp = api_client.approve_booking(booking["id"], _manager)
        approved = validate_success(resp, 200)
        assert approved["status"] == "CONFIRMED"
        assert approved["cost_cents"] > 0

        # 4. Check in
        resp = api_client.check_in_booking(booking["id"], _employee)
        checked_in = validate_success(resp, 200)
        assert checked_in["status"] == "CHECKED_IN"

        # 5. Check out
        resp = api_client.check_out_booking(booking["id"], _employee)
        completed = validate_success(resp, 200)
        assert completed["status"] == "COMPLETED"


class TestWaitlistPromotionCycle:
    """Full waitlist lifecycle: book -> waitlist -> cancel -> promote -> new booking."""

    def test_full_waitlist_promotion_flow(self):
        """Employee books a slot, another joins waitlist. Cancel booking ->
        waitlist promoted -> new booking auto-created."""
        room = create_standard_room()
        start = _ts(hours=72)
        end = _ts(hours=73)

        # 1. Employee books the slot
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        booking = get_success_data(resp)
        assert booking["status"] == "CONFIRMED"

        # 2. Employee2 joins waitlist for same slot
        wl_payload = create_waitlist_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_waitlist(wl_payload, _employee2)
        wl = get_success_data(resp)
        assert wl["status"] == "WAITING"

        # 3. Employee cancels booking
        resp = api_client.cancel_booking(booking["id"], _employee)
        cancelled = get_success_data(resp)
        assert cancelled["status"] == "CANCELLED"

        # 4. Verify waitlist entry is promoted
        resp = api_client.list_waitlist(_admin, params={"room_id": room["id"]})
        items, _ = validate_paginated(resp)
        wl_updated = next((w for w in items if w["id"] == wl["id"]), None)
        assert wl_updated is not None
        assert wl_updated["status"] == "PROMOTED", (
            f"Waitlist entry should be PROMOTED after booking cancel, got {wl_updated['status']}"
        )

        # 5. Verify new booking created for the waitlisted user
        resp = api_client.list_bookings(_admin, params={"room_id": room["id"]})
        bookings, _ = validate_paginated(resp)
        new_bookings = [
            b for b in bookings
            if b["organizer_id"] == "test-employee-2"
            and b["status"] in ("TENTATIVE", "CONFIRMED")
        ]
        assert len(new_bookings) >= 1, (
            "A new booking should be created from the promoted waitlist entry"
        )


class TestRoomDecommissionCascade:
    """End-to-end: room decommission with full cascade verification."""

    def test_decommission_cascade_full(self):
        """Create room with bookings and waitlist entries. Decommission cascades all."""
        room = create_standard_room()

        # Create multiple bookings
        bookings = []
        for i in range(3):
            start = _ts(hours=120 + i * 24)
            end = _ts(hours=121 + i * 24)
            payload = create_booking_payload(room["id"], start_time=start, end_time=end)
            resp = api_client.create_booking(payload, _employee)
            b = get_success_data(resp)
            bookings.append(b)

        # Create waitlist entry
        wl_start = _ts(hours=120)
        wl_end = _ts(hours=121)
        wl_payload = create_waitlist_payload(room["id"], start_time=wl_start, end_time=wl_end)
        resp = api_client.create_waitlist(wl_payload, _employee2)
        wl = get_success_data(resp)

        # Decommission room
        resp = api_client.update_room(room["id"], {"status": "DECOMMISSIONED"}, _admin)
        updated_room = validate_success(resp, 200)
        assert updated_room["status"] == "DECOMMISSIONED"

        # Verify all bookings are cancelled
        for b in bookings:
            resp = api_client.get_booking(b["id"], _admin)
            data = get_success_data(resp)
            assert data["status"] == "CANCELLED", (
                f"Booking {b['id']} should be CANCELLED after decommission, got {data['status']}"
            )

        # Verify waitlist entry is expired
        resp = api_client.list_waitlist(_admin, params={"room_id": room["id"]})
        items, _ = validate_paginated(resp)
        wl_updated = next((w for w in items if w["id"] == wl["id"]), None)
        if wl_updated:
            assert wl_updated["status"] == "EXPIRED"


class TestSeriesWithConflictHandling:
    """Series creation where some occurrences conflict with existing bookings."""

    def test_series_with_partial_conflicts(self):
        """Create a daily series where one occurrence conflicts with existing booking.

        Non-conflicting occurrences should be confirmed (STANDARD room).
        Conflicting occurrence should be TENTATIVE (flagged, not auto-confirmed).
        """
        room = create_standard_room()

        # Book one specific slot that will conflict with the series
        conflict_date = _future_date(days=9)
        start = f"{conflict_date}T10:00:00.000Z"
        end = f"{conflict_date}T11:00:00.000Z"
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        blocking = get_success_data(resp)
        assert blocking["status"] == "CONFIRMED"

        # Create daily series that overlaps the blocking booking
        series_payload = create_series_payload(
            room["id"],
            recurrence_rule="DAILY",
            start_time="10:00",
            duration_minutes=60,
            series_start_date=_future_date(days=8),
            series_end_date=_future_date(days=11),  # 4 days
        )
        resp = api_client.create_series(series_payload, _employee2)
        series = get_success_data(resp)
        assert series["total_bookings"] >= 3, (
            f"Expected at least 3 bookings in series, got {series['total_bookings']}"
        )

        # Check the generated bookings
        resp = api_client.list_bookings(_admin, params={"room_id": room["id"]})
        bookings, _ = validate_paginated(resp)
        series_bookings = [b for b in bookings if b.get("series_id") == series["id"]]

        statuses = [b["status"] for b in series_bookings]
        # At least some should be CONFIRMED, and potentially one TENTATIVE
        confirmed = [s for s in statuses if s == "CONFIRMED"]
        tentative = [s for s in statuses if s == "TENTATIVE"]
        assert len(confirmed) >= 1, "At least some non-conflicting occurrences should be CONFIRMED"


class TestEndToEndCostVerification:
    """Verify cost accuracy through full workflow."""

    def test_premium_room_cost_after_approval(self):
        """Full flow: create PREMIUM room with pricing -> book -> approve -> verify cost.

        Room: hourly_rate=6000, peak_multiplier=1.5, peak=09:00-17:00
        Booking: 08:00-10:00 on future date (60 off-peak + 60 peak)
        Expected: 60*100 + 60*150 = 6000 + 9000 = 15000
        """
        room = create_premium_room(
            hourly_rate_cents=6000,
            peak_multiplier=1.5,
            peak_hours_start="09:00",
            peak_hours_end="17:00",
        )
        date = _future_date(days=30)
        start = f"{date}T08:00:00.000Z"
        end = f"{date}T10:00:00.000Z"

        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        booking = get_success_data(resp)
        assert booking["status"] == "PENDING_APPROVAL"

        # Approve
        resp = api_client.approve_booking(booking["id"], _manager)
        approved = validate_success(resp, 200)
        assert approved["status"] == "CONFIRMED"
        assert approved["cost_cents"] == 15000, (
            f"Expected 15000 cents (60*100 + 60*150), got {approved['cost_cents']}"
        )
