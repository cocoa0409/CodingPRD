"""Vehicles and Drivers: maintenance, retirement, license expiry.

Covers PRD §3.3.
"""
from __future__ import annotations
from datetime import timedelta

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_driver, assert_vehicle,
    api_client,
    create_active_driver,
    create_active_stop, create_active_stop_at,
    create_active_vehicle,
    create_and_publish_route,
    create_driver_payload, create_vehicle_payload,
    create_run_sheet, create_run_sheet_payload,
    get_server_now_dt,
    iso_z, parse_iso,
    setup_active_route_basic,
    setup_planned_run_sheet,
    start_maintenance_payload,
)


# ===========================================================================
# Vehicle CRUD (PRD §3.3)
# ===========================================================================
class TestVehicleCRUD:

    def test_create_vehicle_initial_status_active(self, dispatcher_headers):
        """PRD §3.3: "Vehicles begin in ACTIVE status."

        Claim: a fresh vehicle has status ACTIVE.
        """
        data = validate_success(
            api_client.create_vehicle(create_vehicle_payload(),
                                      dispatcher_headers),
            201,
        )
        assert_vehicle(data)
        assert data["status"] == "ACTIVE"

    def test_start_maintenance_with_invalid_window_rejected(
            self, dispatcher_headers):
        """PRD §3.3: "Two preconditions apply: the supplied start must
        strictly precede the supplied end, and the vehicle must not be the
        assigned_vehicle_id of any run-sheet whose planned occupation
        window (defined as the half-open interval from scheduled_departure
        minus 15 minutes up to scheduled_arrival plus 15 minutes) overlaps
        the requested maintenance window..."

        Claim: maintenance_window_start >= maintenance_window_end is
        rejected (the only failure mode for THIS instance, isolating the
        validation per the priority rule).
        """
        v = create_active_vehicle()
        # Same start and end (no strict precedence): expect some 4xx error.
        same_instant = "2026-06-01T08:00:00.000Z"
        resp = api_client.start_vehicle_maintenance(
            v["id"], start_maintenance_payload(same_instant, same_instant),
            dispatcher_headers,
        )
        assert 400 <= resp.status_code < 500, \
            f"Expected 4xx when start_time >= end_time; got {resp.status_code} {resp.text}"

    def test_maintenance_with_overlapping_planned_run_rejected(
            self, dispatcher_headers):
        """PRD §3.3: "...the vehicle must not be the assigned_vehicle_id of
        any run-sheet whose planned occupation window (defined as the
        half-open interval from scheduled_departure minus 15 minutes up to
        scheduled_arrival plus 15 minutes) overlaps the requested
        maintenance window, where the run-sheet is in PLANNED, BOARDING,
        IN_TRANSIT, or DELAYED. A failed second precondition surfaces as
        ERR_VEHICLE_HAS_BOOKED_RUNS."

        Claim: vehicle assigned to a PLANNED run that overlaps the
        proposed maintenance window -> ERR_VEHICLE_HAS_BOOKED_RUNS.
        """
        base = setup_planned_run_sheet(seat_capacity=20)
        run_sheet = base["run_sheet"]
        v = base["vehicle"]
        # Build a maintenance window that overlaps the run sheet's planned
        # occupation. Use scheduled_departure and arrival.
        dep = parse_iso(run_sheet["scheduled_departure"])
        arr = parse_iso(run_sheet["scheduled_arrival"])
        window_start = iso_z(dep - timedelta(hours=1))
        window_end = iso_z(arr + timedelta(hours=1))
        resp = api_client.start_vehicle_maintenance(
            v["id"], start_maintenance_payload(window_start, window_end),
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_VEHICLE_HAS_BOOKED_RUNS)

    def test_clock_advance_past_maintenance_end_returns_vehicle_to_active(
            self, dispatcher_headers):
        """PRD §2.12: "Advancing the clock fires deferred transitions in
        this order: vehicles whose maintenance_window_end is now less than
        or equal to the new clock instant transition from MAINTENANCE back
        to ACTIVE, with maintenance_window_start and maintenance_window_end
        cleared."

        Claim: advancing the clock past maintenance_window_end clears the
        maintenance window and returns the vehicle to ACTIVE.
        """
        # Pin clock at a known instant so all timestamps are deterministic.
        anchor = "2027-01-01T00:00:00.000Z"
        advance_clock_to(anchor)
        v = create_active_vehicle()
        win_start = "2027-01-02T08:00:00.000Z"
        win_end = "2027-01-02T10:00:00.000Z"
        validate_success(
            api_client.start_vehicle_maintenance(
                v["id"], start_maintenance_payload(win_start, win_end),
                dispatcher_headers,
            ),
            200,
        )
        # Confirm maintenance state.
        # Advance clock past win_end -> vehicle should be ACTIVE again.
        advance_clock_to("2027-01-02T10:30:00.000Z")
        from prd_bench_local_runner.testing import validate_paginated
        data, _meta = validate_paginated(
            api_client.list_vehicles(
                dispatcher_headers, params={"limit": 100},
            ),
        )
        match = next(x for x in data if x["id"] == v["id"])
        assert match["status"] == "ACTIVE", \
            f"PRD §2.12: vehicle must return to ACTIVE after clock advances past maintenance_window_end, got {match['status']}"


# ===========================================================================
# Driver CRUD and license-expiry validation (PRD §3.3)
# ===========================================================================
class TestDrivers:

    def test_create_driver_initial_status_active(self, dispatcher_headers):
        """PRD §3.3: "A driver's status begins at ACTIVE and can be SUSPENDED
        or OFFBOARDED; the employee_code is unique among ACTIVE drivers."

        Claim: a fresh driver has status ACTIVE.
        """
        data = validate_success(
            api_client.create_driver(create_driver_payload(), dispatcher_headers),
            201,
        )
        assert_driver(data)
        assert data["status"] == "ACTIVE"

    def test_run_sheet_with_expired_license_rejected(self, dispatcher_headers):
        """PRD §3.3: "When a driver is assigned to a run-sheet, the
        license_expiry_date must be strictly after that run's
        scheduled_departure, otherwise the assignment is rejected with
        ERR_DRIVER_LICENSE_EXPIRED."

        Claim: assigning a driver whose license_expiry_date is BEFORE
        scheduled_departure -> ERR_DRIVER_LICENSE_EXPIRED.
        """
        # Pin clock so we have absolute timestamps to compare.
        anchor = "2026-06-01T05:00:00.000Z"
        advance_clock_to(anchor)
        route, stops = setup_active_route_basic()
        v = create_active_vehicle()
        # Driver whose license expired one day ago.
        expired = iso_z(parse_iso(anchor) - timedelta(days=1))
        driver = create_active_driver(license_expiry_date=expired)
        # Schedule departure tomorrow.
        sched = "2026-06-02T08:00:00.000Z"
        resp = api_client.create_run_sheet(
            create_run_sheet_payload(
                route_id=route["id"],
                scheduled_departure=sched,
                assigned_driver_id=driver["id"],
                assigned_vehicle_id=v["id"],
            ),
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_LICENSE_EXPIRED)

    def test_run_sheet_with_license_exactly_at_departure_rejected(
            self, dispatcher_headers):
        """PRD §3.3: "When a driver is assigned to a run-sheet, the
        license_expiry_date must be strictly after that run's
        scheduled_departure, otherwise the assignment is rejected with
        ERR_DRIVER_LICENSE_EXPIRED."

        Claim: license_expiry_date == scheduled_departure (NOT strictly
        after) -> ERR_DRIVER_LICENSE_EXPIRED. Boundary test.
        """
        anchor = "2026-06-01T05:00:00.000Z"
        advance_clock_to(anchor)
        route, _ = setup_active_route_basic()
        v = create_active_vehicle()
        sched = "2026-06-02T08:00:00.000Z"
        driver = create_active_driver(license_expiry_date=sched)
        resp = api_client.create_run_sheet(
            create_run_sheet_payload(
                route_id=route["id"], scheduled_departure=sched,
                assigned_driver_id=driver["id"], assigned_vehicle_id=v["id"],
            ),
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DRIVER_LICENSE_EXPIRED)
