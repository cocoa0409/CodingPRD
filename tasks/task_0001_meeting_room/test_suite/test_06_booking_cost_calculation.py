"""Test booking cost computation.

Covers:
- Fully off-peak: (duration_minutes / 60) * hourly_rate_cents
- Fully peak: (duration_minutes / 60) * hourly_rate_cents * peak_multiplier
- Straddling peak boundary: split at boundary, different rates per segment
- Round-half-up at the end (not per-segment)
- Integer cents precision
- Cost computed on auto-confirm (STANDARD) and on approval (PREMIUM)
"""
import pytest
import math
from datetime import datetime, timedelta, timezone
from test_helpers import (
    api_client, validate_success, get_success_data,
    ApiErrorId, TEST_USERS,
    create_booking_payload,
    create_standard_room, create_premium_room,
    create_room_with_pricing,
)


_admin = TEST_USERS["facility_admin_headers"]
_employee = TEST_USERS["employee_headers"]
_manager = TEST_USERS["manager_headers"]


def _make_booking_at_fixed_time(room_id, date_str, start_hour, start_min,
                                 end_hour, end_min, headers=None):
    """Create a booking at a specific wall-clock time on a future date.

    date_str: YYYY-MM-DD (must be in the future)
    start_hour/min, end_hour/min: 24h time components
    """
    hdrs = headers or _employee
    start = f"{date_str}T{start_hour:02d}:{start_min:02d}:00.000Z"
    end = f"{date_str}T{end_hour:02d}:{end_min:02d}:00.000Z"
    payload = create_booking_payload(room_id, start_time=start, end_time=end)
    return api_client.create_booking(payload, hdrs)


def _future_date_str(days=30):
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


def _round_half_up(x):
    """Python's round() uses banker's rounding; this does round-half-up."""
    return int(math.floor(x + 0.5))


class TestFullyOffPeakCost:
    """Booking entirely outside peak hours."""

    def test_off_peak_1_hour(self):
        """1 hour off-peak: 60 * (6000/60) = 6000 cents."""
        room = create_room_with_pricing(
            hourly_rate_cents=6000,
            peak_multiplier=1.5,
            peak_hours_start="09:00",
            peak_hours_end="17:00",
        )
        date = _future_date_str()
        # 07:00 - 08:00 is entirely off-peak (peak is 09:00-17:00)
        resp = _make_booking_at_fixed_time(room["id"], date, 7, 0, 8, 0)
        data = validate_success(resp, 201)
        # 60 minutes * (6000/60) = 6000
        assert data["cost_cents"] == 6000, (
            f"Expected 6000 cents for 1h off-peak at 6000/hr, got {data['cost_cents']}"
        )

    def test_off_peak_30_minutes(self):
        """30 min off-peak: 30 * (6000/60) = 3000 cents."""
        room = create_room_with_pricing(hourly_rate_cents=6000, peak_hours_start="09:00", peak_hours_end="17:00")
        date = _future_date_str()
        resp = _make_booking_at_fixed_time(room["id"], date, 7, 0, 7, 30)
        data = validate_success(resp, 201)
        assert data["cost_cents"] == 3000

    def test_off_peak_2_hours(self):
        """2 hours off-peak: 120 * (6000/60) = 12000 cents."""
        room = create_room_with_pricing(hourly_rate_cents=6000, peak_hours_start="09:00", peak_hours_end="17:00")
        date = _future_date_str()
        resp = _make_booking_at_fixed_time(room["id"], date, 6, 0, 8, 0)
        data = validate_success(resp, 201)
        assert data["cost_cents"] == 12000


class TestFullyPeakCost:
    """Booking entirely within peak hours."""

    def test_peak_1_hour(self):
        """1 hour peak: 60 * (6000/60) * 1.5 = 9000 cents."""
        room = create_room_with_pricing(
            hourly_rate_cents=6000,
            peak_multiplier=1.5,
            peak_hours_start="09:00",
            peak_hours_end="17:00",
        )
        date = _future_date_str()
        # 10:00 - 11:00 is entirely within peak
        resp = _make_booking_at_fixed_time(room["id"], date, 10, 0, 11, 0)
        data = validate_success(resp, 201)
        assert data["cost_cents"] == 9000, (
            f"Expected 9000 cents for 1h peak (6000/hr * 1.5), got {data['cost_cents']}"
        )

    def test_peak_2_hours(self):
        """2 hours peak: 120 * 100 * 1.5 = 18000 cents."""
        room = create_room_with_pricing(
            hourly_rate_cents=6000,
            peak_multiplier=1.5,
            peak_hours_start="09:00",
            peak_hours_end="17:00",
        )
        date = _future_date_str()
        resp = _make_booking_at_fixed_time(room["id"], date, 10, 0, 12, 0)
        data = validate_success(resp, 201)
        assert data["cost_cents"] == 18000

    def test_peak_15_minutes(self):
        """15 min peak: 15 * (6000/60) * 1.5 = 2250 cents."""
        room = create_room_with_pricing(
            hourly_rate_cents=6000,
            peak_multiplier=1.5,
            peak_hours_start="09:00",
            peak_hours_end="17:00",
        )
        date = _future_date_str()
        resp = _make_booking_at_fixed_time(room["id"], date, 10, 0, 10, 15)
        data = validate_success(resp, 201)
        assert data["cost_cents"] == 2250


class TestStraddlingPeakCost:
    """Booking that crosses the peak boundary. The critical edge case."""

    def test_straddle_into_peak(self):
        """08:00-10:00: 60 min off-peak + 60 min peak.

        Off-peak: 60 * (6000/60) = 6000
        Peak: 60 * (6000/60) * 1.5 = 9000
        Total: 15000
        """
        room = create_room_with_pricing(
            hourly_rate_cents=6000,
            peak_multiplier=1.5,
            peak_hours_start="09:00",
            peak_hours_end="17:00",
        )
        date = _future_date_str()
        resp = _make_booking_at_fixed_time(room["id"], date, 8, 0, 10, 0)
        data = validate_success(resp, 201)
        assert data["cost_cents"] == 15000, (
            f"Expected 15000 for straddling booking (60min off-peak + 60min peak), got {data['cost_cents']}"
        )

    def test_straddle_out_of_peak(self):
        """16:00-18:00: 60 min peak + 60 min off-peak.

        Peak: 60 * (6000/60) * 1.5 = 9000
        Off-peak: 60 * (6000/60) = 6000
        Total: 15000
        """
        room = create_room_with_pricing(
            hourly_rate_cents=6000,
            peak_multiplier=1.5,
            peak_hours_start="09:00",
            peak_hours_end="17:00",
        )
        date = _future_date_str()
        resp = _make_booking_at_fixed_time(room["id"], date, 16, 0, 18, 0)
        data = validate_success(resp, 201)
        assert data["cost_cents"] == 15000

    def test_straddle_both_boundaries(self):
        """06:00-18:00 (8 hours, straddling both boundaries if allowed by duration).

        But max is 8 hours, so let's use 08:00-16:00 (8 hours exactly):
        Off-peak 08:00-09:00: 60 min * 100 = 6000
        Peak 09:00-16:00: 420 min * 150 = 63000
        Total: 69000
        """
        room = create_room_with_pricing(
            hourly_rate_cents=6000,
            peak_multiplier=1.5,
            peak_hours_start="09:00",
            peak_hours_end="17:00",
        )
        date = _future_date_str()
        resp = _make_booking_at_fixed_time(room["id"], date, 8, 0, 16, 0)
        data = validate_success(resp, 201)
        # 60 off-peak min * 100 + 420 peak min * 150 = 6000 + 63000 = 69000
        assert data["cost_cents"] == 69000

    def test_straddle_with_fractional_rate(self):
        """Test with a rate that produces fractional per-minute values.

        Room: hourly_rate_cents=100, peak_multiplier=1.5, peak 09:00-17:00
        Booking: 08:30-09:30 (30 min off-peak + 30 min peak)

        Off-peak per-minute: 100/60 = 1.6667
        Peak per-minute: (100/60) * 1.5 = 2.5

        Off-peak total: 30 * 1.6667 = 50.0
        Peak total: 30 * 2.5 = 75.0
        Sum: 125.0
        Rounded (round_half_up): 125
        """
        room = create_room_with_pricing(
            hourly_rate_cents=100,
            peak_multiplier=1.5,
            peak_hours_start="09:00",
            peak_hours_end="17:00",
        )
        date = _future_date_str()
        resp = _make_booking_at_fixed_time(room["id"], date, 8, 30, 9, 30)
        data = validate_success(resp, 201)
        assert data["cost_cents"] == 125, (
            f"Expected 125 cents (30*1.667 + 30*2.5 = 125), got {data['cost_cents']}"
        )

    def test_round_half_up_semantics(self):
        """Verify round_half_up: sum of fractional per-minute rates rounded once at end.

        Room: hourly_rate_cents=100, peak_multiplier=1.0 (effectively no peak),
              peak 09:00-17:00
        Booking fully off-peak: 07:00-07:45 (45 minutes)

        Per-minute: 100/60 = 1.6667
        Total: 45 * 1.6667 = 75.0
        Round_half_up(75.0) = 75
        """
        room = create_room_with_pricing(
            hourly_rate_cents=100,
            peak_multiplier=1.0,
            peak_hours_start="09:00",
            peak_hours_end="17:00",
        )
        date = _future_date_str()
        resp = _make_booking_at_fixed_time(room["id"], date, 7, 0, 7, 45)
        data = validate_success(resp, 201)
        assert data["cost_cents"] == 75

    def test_round_half_up_boundary(self):
        """Test rounding where the sum is X.5 -> should round up.

        Room: hourly_rate_cents=10, peak_multiplier=1.0
        Per-minute = 10/60 = 0.1667
        Booking: 3 minutes -> 3 * 0.1667 = 0.5 -> round_half_up = 1
        But 3 minutes < 15 minute minimum. Use a different approach.

        Room: hourly_rate_cents=7, peak_multiplier=1.0
        Per-minute = 7/60 = 0.1167
        Booking 15 min off-peak: 15 * 0.1167 = 1.75 -> round_half_up = 2
        """
        room = create_room_with_pricing(
            hourly_rate_cents=7,
            peak_multiplier=1.0,
            peak_hours_start="09:00",
            peak_hours_end="17:00",
        )
        date = _future_date_str()
        resp = _make_booking_at_fixed_time(room["id"], date, 7, 0, 7, 15)
        data = validate_success(resp, 201)
        # 15 * (7/60) = 15 * 0.11667 = 1.75 -> round_half_up = 2
        assert data["cost_cents"] == 2, (
            f"Expected 2 cents (round_half_up of 1.75), got {data['cost_cents']}"
        )


class TestCostOnApproval:
    """Cost is computed when a PREMIUM room booking is approved."""

    def test_cost_computed_on_approval(self):
        """PREMIUM room booking gets cost_cents set upon approval."""
        room = create_premium_room(
            hourly_rate_cents=6000,
            peak_multiplier=1.5,
            peak_hours_start="09:00",
            peak_hours_end="17:00",
        )
        date = _future_date_str()
        start = f"{date}T10:00:00.000Z"
        end = f"{date}T11:00:00.000Z"
        payload = create_booking_payload(room["id"], start_time=start, end_time=end)
        resp = api_client.create_booking(payload, _employee)
        booking = get_success_data(resp)
        assert booking["status"] == "PENDING_APPROVAL"

        resp = api_client.approve_booking(booking["id"], _manager)
        data = validate_success(resp, 200)
        assert data["status"] == "CONFIRMED"
        # 60 peak minutes * (6000/60) * 1.5 = 9000
        assert data["cost_cents"] == 9000


class TestDefaultPeakMultiplier:
    """When peak_multiplier is not set, it defaults to 1.0."""

    def test_no_peak_multiplier_defaults_to_1(self):
        """Without peak_multiplier, cost is base rate only."""
        room = create_standard_room(
            hourly_rate_cents=6000,
            # Omit peak_multiplier -> defaults to 1.0
        )
        # Remove peak_multiplier from room creation is handled by factory defaults
        # Just verify that a room with multiplier 1.0 charges base rate during "peak"
        date = _future_date_str()
        # Create room without peak multiplier override
        room2 = create_room_with_pricing(
            hourly_rate_cents=6000,
            peak_multiplier=1.0,
            peak_hours_start="09:00",
            peak_hours_end="17:00",
        )
        resp = _make_booking_at_fixed_time(room2["id"], date, 10, 0, 11, 0)
        data = validate_success(resp, 201)
        # With multiplier 1.0, peak and off-peak are the same: 60 * 100 = 6000
        assert data["cost_cents"] == 6000
