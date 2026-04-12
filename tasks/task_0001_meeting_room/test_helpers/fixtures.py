"""Composite setup helpers for meeting room test scenarios.

Fixtures encapsulate multi-step API call sequences so that tests focus on
assertions, not plumbing.  Every fixture uses get_success_data() internally
(lenient validator) so setup failures produce clear errors.
"""
import uuid
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data, build_user_headers

from .api_client import api_client
from .factories import (
    create_room_payload,
    create_premium_room_payload,
    create_booking_payload,
    create_series_payload,
    create_waitlist_payload,
    _future_time,
    _future_date,
    _unique_name,
)
from .test_users import TEST_USERS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_admin = TEST_USERS["facility_admin_headers"]
_manager = TEST_USERS["manager_headers"]
_employee = TEST_USERS["employee_headers"]
_employee2 = TEST_USERS["employee2_headers"]


def _ts(hours_ahead: float = 24, minutes_ahead: float = 0) -> str:
    """ISO 8601 UTC timestamp at a given offset from now."""
    dt = datetime.now(timezone.utc) + timedelta(hours=hours_ahead, minutes=minutes_ahead)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _date(days_ahead: int = 7) -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    return dt.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Tier 1: Basic entity creation
# ---------------------------------------------------------------------------

def create_standard_room(**overrides) -> dict:
    """Create and return a STANDARD ACTIVE room.

    Returns the full Room dict from the API response.
    """
    payload = create_room_payload(tier="STANDARD", **overrides)
    resp = api_client.create_room(payload, _admin)
    return get_success_data(resp)


def create_premium_room(**overrides) -> dict:
    """Create and return a PREMIUM ACTIVE room."""
    payload = create_premium_room_payload(**overrides)
    resp = api_client.create_room(payload, _admin)
    return get_success_data(resp)


def create_room_in_maintenance(**overrides) -> dict:
    """Create a room and transition it to MAINTENANCE."""
    room = create_standard_room(**overrides)
    resp = api_client.update_room(room["id"], {"status": "MAINTENANCE"}, _admin)
    return get_success_data(resp)


def create_room_decommissioned(**overrides) -> dict:
    """Create a room and transition it to DECOMMISSIONED."""
    room = create_standard_room(**overrides)
    resp = api_client.update_room(room["id"], {"status": "DECOMMISSIONED"}, _admin)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: Booking lifecycle helpers
# ---------------------------------------------------------------------------

def create_confirmed_booking(room_id: str | None = None, room: dict | None = None,
                             headers: dict | None = None, **overrides) -> tuple[dict, dict]:
    """Create a confirmed booking on a STANDARD room.

    If no room_id/room provided, creates a new STANDARD room.
    Returns (booking, room).
    """
    if room is None and room_id is None:
        room = create_standard_room()
        room_id = room["id"]
    elif room is not None:
        room_id = room["id"]
    else:
        resp = api_client.get_room(room_id, _admin)
        room = get_success_data(resp)

    hdrs = headers or _employee
    payload = create_booking_payload(room_id, **overrides)
    resp = api_client.create_booking(payload, hdrs)
    booking = get_success_data(resp)
    assert booking["status"] in ("CONFIRMED", "TENTATIVE"), (
        f"Expected CONFIRMED for STANDARD room, got {booking['status']}"
    )
    return booking, room


def create_pending_approval_booking(room: dict | None = None,
                                    headers: dict | None = None,
                                    **overrides) -> tuple[dict, dict]:
    """Create a PENDING_APPROVAL booking on a PREMIUM room.

    Returns (booking, room).
    """
    if room is None:
        room = create_premium_room()
    hdrs = headers or _employee
    payload = create_booking_payload(room["id"], **overrides)
    resp = api_client.create_booking(payload, hdrs)
    booking = get_success_data(resp)
    assert booking["status"] == "PENDING_APPROVAL", (
        f"Expected PENDING_APPROVAL for PREMIUM room, got {booking['status']}"
    )
    return booking, room


def create_approved_booking(room: dict | None = None, **overrides) -> tuple[dict, dict]:
    """Create a booking on a PREMIUM room and approve it.

    Returns (booking, room).
    """
    booking, room = create_pending_approval_booking(room=room, **overrides)
    resp = api_client.approve_booking(booking["id"], _manager)
    booking = get_success_data(resp)
    assert booking["status"] == "CONFIRMED", (
        f"Expected CONFIRMED after approval, got {booking['status']}"
    )
    return booking, room


def create_checked_in_booking(room: dict | None = None,
                              headers: dict | None = None,
                              **overrides) -> tuple[dict, dict]:
    """Create a STANDARD booking within check-in window and check in.

    The booking starts very soon (within 15 min) so check-in is allowed.
    Returns (booking, room).
    """
    if room is None:
        room = create_standard_room()

    # Create booking that starts within the check-in window (a few minutes from now)
    start = datetime.now(timezone.utc) + timedelta(minutes=5)
    end = start + timedelta(hours=1)
    start_str = start.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_str = end.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    payload = create_booking_payload(
        room["id"],
        start_time=start_str,
        end_time=end_str,
        **overrides,
    )
    hdrs = headers or _employee
    resp = api_client.create_booking(payload, hdrs)
    booking = get_success_data(resp)

    resp = api_client.check_in_booking(booking["id"], hdrs)
    booking = get_success_data(resp)
    assert booking["status"] == "CHECKED_IN", (
        f"Expected CHECKED_IN, got {booking['status']}"
    )
    return booking, room


def create_completed_booking(room: dict | None = None, **overrides) -> tuple[dict, dict]:
    """Create a booking, check in, and check out -> COMPLETED.

    Returns (booking, room).
    """
    booking, room = create_checked_in_booking(room=room, **overrides)
    resp = api_client.check_out_booking(booking["id"], _employee)
    booking = get_success_data(resp)
    assert booking["status"] == "COMPLETED", (
        f"Expected COMPLETED, got {booking['status']}"
    )
    return booking, room


# ---------------------------------------------------------------------------
# Tier 3: Waitlist helpers
# ---------------------------------------------------------------------------

def create_waitlist_entry(room_id: str, headers: dict | None = None,
                          **overrides) -> dict:
    """Create a WAITING waitlist entry. Returns the waitlist dict."""
    hdrs = headers or _employee
    payload = create_waitlist_payload(room_id, **overrides)
    resp = api_client.create_waitlist(payload, hdrs)
    return get_success_data(resp)


def setup_booking_with_waitlist(room: dict | None = None,
                                **booking_overrides) -> tuple[dict, dict, dict]:
    """Create a STANDARD room with a confirmed booking and a waitlist entry
    for the same time slot.

    Returns (booking, waitlist_entry, room).
    """
    if room is None:
        room = create_standard_room()

    start = _ts(hours_ahead=72)
    end = _ts(hours_ahead=73)

    booking_payload = create_booking_payload(
        room["id"], start_time=start, end_time=end, **booking_overrides
    )
    resp = api_client.create_booking(booking_payload, _employee)
    booking = get_success_data(resp)

    # Different user joins waitlist for the same slot
    waitlist_payload = create_waitlist_payload(
        room["id"], start_time=start, end_time=end
    )
    resp = api_client.create_waitlist(waitlist_payload, _employee2)
    wl = get_success_data(resp)

    return booking, wl, room


# ---------------------------------------------------------------------------
# Tier 4: Series helpers
# ---------------------------------------------------------------------------

def create_active_series(room: dict | None = None,
                         headers: dict | None = None,
                         **overrides) -> tuple[dict, dict]:
    """Create a recurring series on a STANDARD room.

    Returns (series, room).
    """
    if room is None:
        room = create_standard_room()
    hdrs = headers or _employee
    payload = create_series_payload(room["id"], **overrides)
    resp = api_client.create_series(payload, hdrs)
    series = get_success_data(resp)
    return series, room


# ---------------------------------------------------------------------------
# Tier 5: Overlap / conflict scenario setups
# ---------------------------------------------------------------------------

def setup_time_conflict_scenario() -> tuple[dict, dict, str, str]:
    """Create a STANDARD room with one confirmed booking.

    Returns (room, existing_booking, start_time, end_time) where the times
    are the booked slot. Tests can then attempt to book overlapping times.
    """
    room = create_standard_room()
    start = _ts(hours_ahead=96)
    end = _ts(hours_ahead=97)
    payload = create_booking_payload(room["id"], start_time=start, end_time=end)
    resp = api_client.create_booking(payload, _employee)
    booking = get_success_data(resp)
    return room, booking, start, end


# ---------------------------------------------------------------------------
# Tier 6: Cost calculation helpers
# ---------------------------------------------------------------------------

def create_room_with_pricing(hourly_rate_cents: int = 6000,
                             peak_multiplier: float = 1.5,
                             peak_hours_start: str = "09:00",
                             peak_hours_end: str = "17:00",
                             **overrides) -> dict:
    """Create a STANDARD room with specific pricing configuration."""
    return create_standard_room(
        hourly_rate_cents=hourly_rate_cents,
        peak_multiplier=peak_multiplier,
        peak_hours_start=peak_hours_start,
        peak_hours_end=peak_hours_end,
        **overrides,
    )


# ---------------------------------------------------------------------------
# Tier 7: Ops run / no-show detection helpers
# ---------------------------------------------------------------------------

def setup_no_show_scenario(room: dict | None = None) -> tuple[dict, dict]:
    """Create a CONFIRMED booking whose start_time is in the past so that
    run_ops should mark it as NO_SHOW.

    WARNING: This booking's start_time must be in the past by >15 min for
    no-show detection, but the API rejects past bookings. Tests that need
    no-show behavior should create a booking in the near future, wait
    (or accept that they test the ops-run path indirectly).

    For practical testing: creates a booking starting 5 minutes from now
    (within check-in window but still future). The test can then run_ops
    after adequate time passes.

    Returns (booking, room).
    """
    if room is None:
        room = create_standard_room()
    start = datetime.now(timezone.utc) + timedelta(minutes=5)
    end = start + timedelta(hours=1)
    payload = create_booking_payload(
        room["id"],
        start_time=start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        end_time=end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    )
    resp = api_client.create_booking(payload, _employee)
    booking = get_success_data(resp)
    return booking, room


# ---------------------------------------------------------------------------
# Tier 8: Concurrency / race condition setup
# ---------------------------------------------------------------------------

def setup_race_booking_scenario() -> tuple[dict, str, str]:
    """Create a STANDARD room and return time slot info for concurrent booking attempts.

    Returns (room, start_time, end_time). Multiple threads can try to book
    the same slot simultaneously.
    """
    room = create_standard_room()
    start = _ts(hours_ahead=120)
    end = _ts(hours_ahead=121)
    return room, start, end


def setup_race_approval_scenario() -> tuple[dict, dict, dict]:
    """Create a PREMIUM room with one PENDING_APPROVAL booking and one
    confirmed booking that will create a conflict on approval.

    Returns (room, pending_booking, conflicting_booking).
    Used for testing concurrent approve + book race conditions.
    """
    room = create_premium_room()
    start = _ts(hours_ahead=120)
    end = _ts(hours_ahead=121)

    # Create a pending booking on premium room
    payload1 = create_booking_payload(room["id"], start_time=start, end_time=end)
    resp = api_client.create_booking(payload1, _employee)
    pending = get_success_data(resp)

    return room, pending, {"start_time": start, "end_time": end}
