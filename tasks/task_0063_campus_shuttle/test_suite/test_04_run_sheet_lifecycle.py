"""RunSheet lifecycle: planning, boarding, departure, completion.

Covers PRD §3.4 (run-sheet lifecycle) including the BASE / PEAK_ADJUSTED
duration variants and double-booking invariants.
"""
from __future__ import annotations
from datetime import timedelta
import math

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    assert_run_sheet,
    create_active_driver,
    create_active_stop, create_active_stop_at,
    create_active_vehicle,
    create_and_publish_route,
    create_run_sheet, create_run_sheet_payload,
    expected_peak_adjusted_duration_minutes,
    expected_base_duration_minutes,
    expected_route_distance_km,
    iso_z, parse_iso,
    setup_active_route_basic,
    setup_planned_run_sheet,
    setup_four_active_stops_in_line,
    start_boarding, depart_run_sheet, complete_run_sheet, cancel_run_sheet,
    make_driver_headers,
    fetch_run_sheet,
)


# ===========================================================================
# RunSheet creation (PRD §3.4)
# ===========================================================================
class TestRunSheetCreation:

    def test_create_run_sheet_sets_planned_with_capacity_remaining(
            self, dispatcher_headers):
        """PRD §3.4: "At creation, the run-sheet pins route_version_number
        to the route's current version_number, computes scheduled_arrival
        from the route's estimated_duration_minutes using the PEAK_ADJUSTED
        variant (see below), and enters PLANNED status with a computed
        capacity_remaining equal to the assigned vehicle's seat_capacity."

        Claim: a fresh run-sheet is PLANNED with capacity_remaining ==
        Vehicle.seat_capacity and route_version_number pinned.
        """
        base = setup_planned_run_sheet(seat_capacity=24)
        rs = base["run_sheet"]
        assert_run_sheet(rs)
        assert rs["status"] == "PLANNED"
        assert rs["capacity_remaining"] == 24, \
            f"PRD §3.4: capacity_remaining must equal seat_capacity (24), got {rs['capacity_remaining']}"
        assert rs["route_version_number"] == base["route"]["version_number"]
        assert rs["delay_minutes_accumulated"] == 0
        assert rs["substitute_vehicle_id"] in (None, "")

    def test_scheduled_arrival_peak_adjusted_variant(self, dispatcher_headers):
        """PRD §3.4: "The PEAK_ADJUSTED duration variant projects
        scheduled_departure onto the local time of day, and if that
        projection falls inside any peak window of the route version
        snapshot, the travel-time portion of the duration is multiplied by
        a peak factor of 1.25 (dwell time is not affected); otherwise the
        BASE variant is used. The resulting minute count is ceilinged to a
        whole minute and added to scheduled_departure to yield
        scheduled_arrival."

        Claim: schedule a run whose scheduled_departure lies inside the
        route's peak window; verify scheduled_arrival - scheduled_departure
        equals the helper-computed PEAK_ADJUSTED duration.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        stops = setup_four_active_stops_in_line(spacing_lng=0.05)
        route = create_and_publish_route(
            start_stop_id=stops[0]["id"],
            end_stop_id=stops[-1]["id"],
            intermediate_stop_ids=[stops[1]["id"], stops[2]["id"]],
            peak_windows=[["09:00", "11:00"]],
        )
        vehicle = create_active_vehicle()
        driver = create_active_driver(
            license_expiry_date=iso_z(parse_iso("2026-06-02T08:00:00.000Z")
                                       + timedelta(days=365)),
        )
        # Departure at 09:30 falls inside the 09:00-11:00 peak window.
        sched = "2026-06-02T09:30:00.000Z"
        rs = create_run_sheet(route["id"], sched, driver["id"],
                              vehicle_id=vehicle["id"])
        dep = parse_iso(rs["scheduled_departure"])
        arr = parse_iso(rs["scheduled_arrival"])
        actual_minutes = int(round((arr - dep).total_seconds() / 60))
        expected_minutes = expected_peak_adjusted_duration_minutes(
            route["estimated_distance_km"], intermediate_count=2,
        )
        assert actual_minutes == expected_minutes, \
            f"PRD §3.4 PEAK_ADJUSTED: expected {expected_minutes} min, got {actual_minutes}"

    def test_scheduled_arrival_base_variant_offpeak(self, dispatcher_headers):
        """PRD §3.4: "...otherwise the BASE variant is used."

        Claim: schedule a run whose scheduled_departure lies OUTSIDE the
        peak window; scheduled_arrival - scheduled_departure equals the
        BASE-variant duration (no 1.25 multiplier).
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        stops = setup_four_active_stops_in_line(spacing_lng=0.05)
        route = create_and_publish_route(
            start_stop_id=stops[0]["id"],
            end_stop_id=stops[-1]["id"],
            intermediate_stop_ids=[stops[1]["id"], stops[2]["id"]],
            peak_windows=[["09:00", "11:00"]],
        )
        vehicle = create_active_vehicle()
        driver = create_active_driver(
            license_expiry_date=iso_z(parse_iso("2026-06-02T05:00:00.000Z")
                                       + timedelta(days=365)),
        )
        sched = "2026-06-02T05:00:00.000Z"  # well off-peak
        rs = create_run_sheet(route["id"], sched, driver["id"],
                              vehicle_id=vehicle["id"])
        dep = parse_iso(rs["scheduled_departure"])
        arr = parse_iso(rs["scheduled_arrival"])
        actual_minutes = int(round((arr - dep).total_seconds() / 60))
        expected_minutes = expected_base_duration_minutes(
            route["estimated_distance_km"], intermediate_count=2,
        )
        assert actual_minutes == expected_minutes, \
            f"PRD §3.4 BASE: expected {expected_minutes} min, got {actual_minutes}"

    def test_vehicle_double_booking_buffer_overlap_rejected(
            self, dispatcher_headers):
        """PRD §3.4: "A vehicle must not be the assigned_vehicle_id of two
        run-sheets whose planned occupation windows (the closed-closed
        interval from scheduled_departure minus 15 minutes through
        scheduled_arrival plus 15 minutes) overlap; a violation surfaces
        as ERR_VEHICLE_DOUBLE_BOOKED."

        Claim: a second run assigned to the same vehicle whose buffered
        window overlaps the first -> ERR_VEHICLE_DOUBLE_BOOKED.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        base = setup_planned_run_sheet()
        rs1 = base["run_sheet"]
        # Place rs2 so its buffered window overlaps rs1's.
        dep1 = parse_iso(rs1["scheduled_departure"])
        # rs2 departs 5 minutes after rs1 (well within the 15-min buffer).
        sched2 = iso_z(dep1 + timedelta(minutes=5))
        driver2 = create_active_driver(
            license_expiry_date=iso_z(dep1 + timedelta(days=365)),
        )
        resp = api_client.create_run_sheet(
            create_run_sheet_payload(
                route_id=base["route"]["id"],
                scheduled_departure=sched2,
                assigned_driver_id=driver2["id"],
                assigned_vehicle_id=base["vehicle"]["id"],
            ),
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_DOUBLE_BOOKED)

    def test_driver_double_booking_touching_interval_rejected(
            self, dispatcher_headers):
        """PRD §3.4: "A driver must not be the assigned_driver_id of two
        run-sheets whose [scheduled_departure, scheduled_arrival] intervals
        are adjacent or overlapping under closed-open semantics: even a
        touching boundary (one run's end equal to another's start) counts
        as conflict and surfaces as ERR_DRIVER_DOUBLE_BOOKED."

        Claim: rs2.scheduled_departure == rs1.scheduled_arrival (touching)
        with same driver -> ERR_DRIVER_DOUBLE_BOOKED.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        base = setup_planned_run_sheet()
        rs1 = base["run_sheet"]
        arr1 = parse_iso(rs1["scheduled_arrival"])
        # rs2 departs at exactly rs1's arrival (touching) but uses a
        # different vehicle so we isolate the driver invariant.
        vehicle2 = create_active_vehicle()
        resp = api_client.create_run_sheet(
            create_run_sheet_payload(
                route_id=base["route"]["id"],
                scheduled_departure=iso_z(arr1),
                assigned_driver_id=base["driver"]["id"],
                assigned_vehicle_id=vehicle2["id"],
            ),
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_DOUBLE_BOOKED)


# ===========================================================================
# Lifecycle transitions
# ===========================================================================
class TestRunSheetTransitions:

    def test_start_boarding_outside_window_rejected(self, dispatcher_headers):
        """PRD §3.4: "Boarding is initiated by a Driver or Dispatcher; it
        requires that the assigned vehicle is currently ACTIVE (not
        MAINTENANCE, not RETIRED), and that the current instant lies
        within plus or minus 30 minutes of scheduled_departure."

        Claim: starting boarding more than 30 minutes before
        scheduled_departure -> ERR_INVALID_STATE.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        base = setup_planned_run_sheet()
        # The fixture put scheduled_departure 2 hours from now; current
        # instant is well outside +/- 30 min.
        resp = api_client.start_boarding(base["run_sheet"]["id"],
                                         dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_planned_to_boarding_inside_window(self, dispatcher_headers):
        """PRD §3.4: "Boarding is initiated by a Driver or Dispatcher; it
        requires that the assigned vehicle is currently ACTIVE (not
        MAINTENANCE, not RETIRED), and that the current instant lies
        within plus or minus 30 minutes of scheduled_departure."

        Claim: advancing the clock to 10 min before departure permits
        start-boarding, which transitions PLANNED -> BOARDING.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        base = setup_planned_run_sheet()
        sched_dep = parse_iso(base["run_sheet"]["scheduled_departure"])
        advance_clock_to(iso_z(sched_dep - timedelta(minutes=10)))
        data = validate_success(
            api_client.start_boarding(base["run_sheet"]["id"],
                                      dispatcher_headers),
            200,
        )
        assert data["status"] == "BOARDING"

    def test_boarding_to_in_transit_and_completed_flow(self, dispatcher_headers):
        """PRD §3.4: "Departure (BOARDING -> IN_TRANSIT) is initiated by a
        Driver or Dispatcher with no minimum-checked-in precondition... Completion
        (IN_TRANSIT -> COMPLETED or DELAYED -> COMPLETED) is initiated by a
        Driver or Dispatcher; it stamps completed_at to the current
        instant, sets last_run_completed_at on the assigned vehicle (which
        in turn becomes the sort key for the next vehicle-rotation
        selection on that route), and auto-transitions every CHECKED_IN
        reservation on this run to COMPLETED."

        Claim: BOARDING -> IN_TRANSIT -> COMPLETED stamps completed_at and
        leaves the run in COMPLETED status.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        base = setup_planned_run_sheet()
        sched_dep = parse_iso(base["run_sheet"]["scheduled_departure"])
        advance_clock_to(iso_z(sched_dep - timedelta(minutes=10)))
        start_boarding(base["run_sheet"]["id"])
        advance_clock_to(iso_z(sched_dep + timedelta(seconds=10)))
        departed = depart_run_sheet(base["run_sheet"]["id"])
        assert departed["status"] == "IN_TRANSIT"
        advance_clock_to(iso_z(sched_dep + timedelta(minutes=30)))
        completed = complete_run_sheet(base["run_sheet"]["id"])
        assert completed["status"] == "COMPLETED"
        assert completed.get("completed_at"), \
            "PRD §3.4: completion must stamp completed_at"

    def test_cancel_planned_run_cascades_to_reservations(self, dispatcher_headers):
        """PRD §3.4: "Cancellation (PLANNED -> CANCELLED) is initiated by a
        Dispatcher or arises as a cascade from retiring a route. Every
        CONFIRMED or WAITLISTED reservation on the run is cancelled in
        turn, and any cancelled CONFIRMED reservation already rolled into
        a FINALIZED monthly bill triggers a refund line on that bill."

        Claim: cancelling a PLANNED run whose reservation is CONFIRMED
        cascades the reservation to CANCELLED.
        """
        from test_helpers import setup_run_with_confirmed_reservation, fetch_reservation
        advance_clock_to("2026-06-01T03:00:00.000Z")
        base = setup_run_with_confirmed_reservation()
        run_id = base["run_sheet"]["id"]
        res_id = base["reservation"]["id"]
        cancelled = cancel_run_sheet(run_id)
        assert cancelled["status"] == "CANCELLED"
        # Reservation cascade.
        res_after = fetch_reservation(res_id)
        assert res_after["status"] == "CANCELLED", \
            f"PRD §3.4 cancel-run cascade: reservation must be CANCELLED, got {res_after['status']}"

    def test_depart_marks_unchecked_in_confirmed_as_no_show(
            self, dispatcher_headers):
        """PRD §3.4: "The act of departing automatically transitions every
        CONFIRMED reservation that has not checked in to NO_SHOW."

        Claim: BOARDING -> IN_TRANSIT cascade flips an un-checked-in
        CONFIRMED reservation to NO_SHOW.
        """
        from test_helpers import setup_run_with_confirmed_reservation, fetch_reservation
        advance_clock_to("2026-06-01T03:00:00.000Z")
        # Use an off-peak window so we test the simple no-show case.
        base = setup_run_with_confirmed_reservation(
            peak_windows=[["00:00", "00:30"]],  # nothing intersects normal hours
        )
        run_id = base["run_sheet"]["id"]
        sched_dep = parse_iso(base["run_sheet"]["scheduled_departure"])
        advance_clock_to(iso_z(sched_dep - timedelta(minutes=10)))
        start_boarding(run_id)
        advance_clock_to(iso_z(sched_dep + timedelta(seconds=10)))
        depart_run_sheet(run_id)
        res_after = fetch_reservation(base["reservation"]["id"])
        assert res_after["status"] == "NO_SHOW", \
            f"PRD §3.4 depart cascade: un-checked-in CONFIRMED must become NO_SHOW, got {res_after['status']}"
