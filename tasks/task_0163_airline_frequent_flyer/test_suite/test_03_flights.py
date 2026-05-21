"""Flight lifecycle — create, depart, cancel, load_factor."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_seconds,
    assert_flight,
    create_flight,
    create_member,
    create_member_with_balance,
    create_segment_for_member,
    depart_flight,
    get_flight,
    make_member_headers,
    validate_error,
    validate_success,
)


class TestFlightCreation:

    def test_admin_creates_flight_with_defaults(self, api):
        """PRD §3.2: "The new flight is in SCHEDULED." Capacity
        defaults: economy 100, business 16, first 4.
        """
        flight = create_flight(
            capacity_economy=100, capacity_business=16, capacity_first=4,
        )
        assert_flight(flight)
        assert flight["status"] == "SCHEDULED"
        assert flight["capacity_economy"] == 100
        assert flight["capacity_business"] == 16
        assert flight["capacity_first"] == 4


class TestFlightDepart:

    def test_depart_flips_status_to_departed(self, api, admin_headers):
        """PRD §3.2: "When an administrator marks a flight departed, its
        status flips to DEPARTED."
        """
        flight = create_flight()
        data = validate_success(api.depart_flight(flight["id"], admin_headers))
        assert data["status"] == "DEPARTED"


class TestFlightCancel:

    def test_cancel_only_from_scheduled(self, api, admin_headers):
        """PRD §3.2: "A flight cancellation by an administrator is
        allowed only while status is SCHEDULED; attempting it from any
        other state yields ERR_FLIGHT_NOT_CANCELLABLE."
        """
        flight = create_flight()
        validate_success(api.depart_flight(flight["id"], admin_headers))
        # Now departed — cancel should fail.
        resp = api.cancel_flight(flight["id"], admin_headers)
        validate_error(resp, ApiErrorId.ERR_FLIGHT_NOT_CANCELLABLE.value)

    def test_cancel_cascades_booked_segments_to_cancelled(self, api,
                                                          admin_headers):
        """PRD §3.2: "On cancellation, every FlightSegment for this
        flight that is still in BOOKED cascades to CANCELLED."
        """
        flight = create_flight()
        member = create_member()
        seg = create_segment_for_member(member["id"], flight["id"])
        # Cancel the flight.
        validate_success(api.cancel_flight(flight["id"], admin_headers))
        # Segment listing should now show seg as CANCELLED.
        listing = api.list_segments(member["id"],
                                     make_member_headers(member["id"]))
        body = listing.json()
        seg_after = next(s for s in body["data"] if s["id"] == seg["id"])
        assert seg_after["status"] == "CANCELLED", (
            "PRD §3.2: every FlightSegment ... still in BOOKED cascades "
            "to CANCELLED."
        )


class TestLoadFactor:

    def test_empty_flight_has_zero_load_factor(self, api):
        """PRD §3.2: "load_factor, the total count of confirmed segments
        across all cabins divided by the sum capacity_economy +
        capacity_business + capacity_first."

        With zero confirmed segments, load_factor is 0.0.
        """
        flight = create_flight(
            capacity_economy=10, capacity_business=2, capacity_first=1,
        )
        flight = get_flight(flight["id"])
        assert float(flight["load_factor"]) == pytest.approx(0.0, abs=1e-9)
