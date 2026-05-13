"""Reservations: stop-pair validity, payer-mode coherence, daily limits, fares.

Covers PRD §3.6 reservation creation and PRD-specified fare calculation.
"""
from __future__ import annotations
from datetime import timedelta

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    assert_reservation,
    create_active_driver, create_active_stop_at, create_active_vehicle,
    create_and_publish_route,
    create_reservation, create_reservation_payload,
    create_run_sheet,
    expected_fare_cents, fare_tier_cents,
    fetch_reservation,
    iso_z, parse_iso,
    make_employee_headers,
    setup_active_route_basic,
    setup_planned_run_sheet,
    unique_department_code, unique_employee_code,
)


def _setup_six_stop_route(peak_windows=None):
    """Build a route with 6 stops (5 segments) on the equator."""
    if peak_windows is None:
        peak_windows = [["09:00", "11:00"]]
    stops = [create_active_stop_at(0.0, i * 0.05) for i in range(6)]
    route = create_and_publish_route(
        start_stop_id=stops[0]["id"],
        end_stop_id=stops[-1]["id"],
        intermediate_stop_ids=[s["id"] for s in stops[1:-1]],
        peak_windows=peak_windows,
    )
    return route, stops


def _create_run_off_peak(route, vehicle_seat: int = 20):
    advance_clock_to("2026-06-01T03:00:00.000Z")
    sched = "2026-06-02T05:00:00.000Z"   # off-peak
    vehicle = create_active_vehicle(seat_capacity=vehicle_seat)
    driver = create_active_driver(
        license_expiry_date=iso_z(parse_iso(sched) + timedelta(days=365)),
    )
    return create_run_sheet(route["id"], sched, driver["id"],
                            vehicle_id=vehicle["id"])


def _create_run_peak(route, vehicle_seat: int = 20):
    advance_clock_to("2026-06-01T03:00:00.000Z")
    sched = "2026-06-02T09:30:00.000Z"   # peak window
    vehicle = create_active_vehicle(seat_capacity=vehicle_seat)
    driver = create_active_driver(
        license_expiry_date=iso_z(parse_iso(sched) + timedelta(days=365)),
    )
    return create_run_sheet(route["id"], sched, driver["id"],
                            vehicle_id=vehicle["id"])


# ===========================================================================
# Stop-pair validity (PRD §3.6)
# ===========================================================================
class TestStopPairValidity:

    def test_boarding_not_in_snapshot_rejected(self, dispatcher_headers):
        """PRD §3.6: "On creation the system first validates stop-pair
        correctness: both boarding_stop_id and alighting_stop_id must
        appear in the run's pinned RouteVersion.stop_sequence_snapshot,
        and the boarding stop must precede the alighting stop in that
        snapshot; otherwise the request is rejected with
        ERR_INVALID_STOP_PAIR."

        Claim: boarding_stop_id NOT in the route's stop sequence ->
        ERR_INVALID_STOP_PAIR.
        """
        route, stops = setup_active_route_basic(intermediate_count=2,
                                                 stop_spacing_lng=0.05)
        run = _create_run_off_peak(route)
        # Create another active stop unrelated to the route.
        unrelated = create_active_stop_at(10.0, 10.0)
        emp = unique_employee_code()
        resp = api_client.create_reservation(
            run["id"],
            create_reservation_payload(emp, unrelated["id"], stops[-1]["id"]),
            make_employee_headers(emp),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STOP_PAIR)

    def test_boarding_after_alighting_rejected(self, dispatcher_headers):
        """PRD §3.6: "...the boarding stop must precede the alighting stop
        in that snapshot; otherwise the request is rejected with
        ERR_INVALID_STOP_PAIR."

        Claim: boarding_stop appears AFTER alighting_stop in the snapshot
        -> ERR_INVALID_STOP_PAIR.
        """
        route, stops = setup_active_route_basic(intermediate_count=2,
                                                 stop_spacing_lng=0.05)
        run = _create_run_off_peak(route)
        emp = unique_employee_code()
        resp = api_client.create_reservation(
            run["id"],
            create_reservation_payload(emp, stops[-1]["id"], stops[0]["id"]),
            make_employee_headers(emp),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STOP_PAIR)


# ===========================================================================
# Payer-mode coherence (PRD §3.6)
# ===========================================================================
class TestPayerMode:

    def test_department_paid_without_department_code_rejected(
            self, dispatcher_headers):
        """PRD §3.6: "The system enforces the payer-mode coherence rule:
        when payer_mode is DEPARTMENT_PAID a department_code is required,
        and when payer_mode is SELF_PAY a department_code must not be
        supplied — either form of mismatch is rejected with
        ERR_PAYER_MODE_MISMATCH."

        Claim: payer_mode=DEPARTMENT_PAID without department_code ->
        ERR_PAYER_MODE_MISMATCH.
        """
        route, stops = setup_active_route_basic(intermediate_count=1,
                                                 stop_spacing_lng=0.05)
        run = _create_run_off_peak(route)
        emp = unique_employee_code()
        resp = api_client.create_reservation(
            run["id"],
            create_reservation_payload(emp, stops[0]["id"], stops[-1]["id"],
                                       payer_mode="DEPARTMENT_PAID"),
            make_employee_headers(emp),
        )
        validate_error(resp, ApiErrorId.ERR_PAYER_MODE_MISMATCH)

    def test_self_pay_with_department_code_rejected(self, dispatcher_headers):
        """PRD §3.6: "...when payer_mode is SELF_PAY a department_code must
        not be supplied — either form of mismatch is rejected with
        ERR_PAYER_MODE_MISMATCH."

        Claim: payer_mode=SELF_PAY with department_code supplied ->
        ERR_PAYER_MODE_MISMATCH.
        """
        route, stops = setup_active_route_basic(intermediate_count=1,
                                                 stop_spacing_lng=0.05)
        run = _create_run_off_peak(route)
        emp = unique_employee_code()
        resp = api_client.create_reservation(
            run["id"],
            create_reservation_payload(
                emp, stops[0]["id"], stops[-1]["id"],
                payer_mode="SELF_PAY",
                department_code=unique_department_code(),
            ),
            make_employee_headers(emp),
        )
        validate_error(resp, ApiErrorId.ERR_PAYER_MODE_MISMATCH)


# ===========================================================================
# Daily reservation limit (PRD §3.6)
# ===========================================================================
class TestDailyLimit:

    def test_employee_daily_limit_exceeded(self, dispatcher_headers):
        """PRD §3.6: "The system also enforces a per-employee daily
        reservation limit of at most 3 non-cancelled reservations whose
        run-sheet scheduled_date is the same calendar day; an attempt to
        create a fourth such reservation is rejected with
        ERR_DAILY_LIMIT_EXCEEDED."

        Claim: creating a 4th non-cancelled reservation for one employee
        on the same scheduled_date -> ERR_DAILY_LIMIT_EXCEEDED.
        """
        route, stops = setup_active_route_basic(intermediate_count=1,
                                                 stop_spacing_lng=0.05)
        # Three runs on the same scheduled_date, all off-peak.
        advance_clock_to("2026-06-01T03:00:00.000Z")
        emp = unique_employee_code()
        # Build 4 runs on the same calendar day; each with its own driver
        # so driver-double-booking does not trigger.
        sched_times = [
            "2026-06-02T03:00:00.000Z",
            "2026-06-02T05:00:00.000Z",
            "2026-06-02T07:00:00.000Z",
            "2026-06-02T13:00:00.000Z",
        ]
        runs = []
        for sched in sched_times:
            vehicle = create_active_vehicle(seat_capacity=20)
            driver = create_active_driver(
                license_expiry_date=iso_z(parse_iso(sched) + timedelta(days=365)),
            )
            runs.append(create_run_sheet(route["id"], sched, driver["id"],
                                          vehicle_id=vehicle["id"]))
        # First three reservations succeed.
        for run in runs[:3]:
            create_reservation(run["id"], emp, stops[0]["id"], stops[-1]["id"])
        # Fourth must be rejected.
        resp = api_client.create_reservation(
            runs[3]["id"],
            create_reservation_payload(emp, stops[0]["id"], stops[-1]["id"]),
            make_employee_headers(emp),
        )
        validate_error(resp, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED)


# ===========================================================================
# Fare calculation (PRD §3.6)
# ===========================================================================
class TestFareCalculation:

    @pytest.mark.parametrize("segments,expected_offpeak", [
        (1, 200),    # 1..2 segments -> 200
        (2, 200),
        (3, 300),    # 3..5 segments -> 300
        (5, 300),
        (6, 400),    # 6+ segments  -> 400
    ])
    def test_tier_fare_offpeak(self, segments, expected_offpeak):
        """PRD §3.6: "The segment count between boarding_stop_id and
        alighting_stop_id on the snapshot determines a tier: 1 to 2
        segments yields the base tier at 200 cents, 3 to 5 segments yields
        the base tier plus 100 cents, and 6 or more segments yields the
        base tier plus 200 cents."

        Claim: off-peak reservation with N segments yields fare per tier
        table (no peak multiplier).
        """
        # Build a route with at least (segments + 1) stops.
        stops = [create_active_stop_at(0.0, i * 0.05) for i in range(segments + 1)]
        route = create_and_publish_route(
            start_stop_id=stops[0]["id"],
            end_stop_id=stops[-1]["id"],
            intermediate_stop_ids=[s["id"] for s in stops[1:-1]],
            peak_windows=[["09:00", "11:00"]],
        )
        run = _create_run_off_peak(route)
        emp = unique_employee_code()
        res = create_reservation(run["id"], emp,
                                 stops[0]["id"], stops[segments]["id"])
        assert res["fare_cents"] == expected_offpeak, \
            f"PRD §3.6 tier: {segments} segments off-peak expected {expected_offpeak} cents, got {res['fare_cents']}"

    def test_peak_multiplier_applied(self):
        """PRD §3.6: "If the run's scheduled_departure projects into a peak
        window of the route version's peak_windows, the tier amount is
        multiplied by 1.5; otherwise it stands. The final integer-cents
        fare is then computed by rounding the multiplication result
        half-up to the nearest cent — the tier-then-peak order is fixed
        and pinned for forward compatibility with future per-tier
        multipliers."

        Claim: peak-window departure with 5 segments yields
        (200+100)*1.5 = 450 cents.
        """
        route, stops = _setup_six_stop_route()
        run = _create_run_peak(route)
        emp = unique_employee_code()
        res = create_reservation(run["id"], emp,
                                 stops[0]["id"], stops[5]["id"])
        assert res["fare_cents"] == 450, \
            f"PRD §3.6 peak: expected 450 cents (300 * 1.5), got {res['fare_cents']}"

    def test_offpeak_no_multiplier(self):
        """PRD §3.6: "...otherwise it stands."

        Claim: same 5-segment reservation off-peak yields 300 cents (no
        peak multiplier).
        """
        route, stops = _setup_six_stop_route()
        run = _create_run_off_peak(route)
        emp = unique_employee_code()
        res = create_reservation(run["id"], emp,
                                 stops[0]["id"], stops[5]["id"])
        assert res["fare_cents"] == 300, \
            f"PRD §3.6: off-peak 5-segment expected 300 cents, got {res['fare_cents']}"


# ===========================================================================
# Capacity / waitlist behaviour
# ===========================================================================
class TestCapacityAndWaitlist:

    def test_reservation_capacity_decrements(self, dispatcher_headers):
        """PRD §3.4 + §3.6: capacity_remaining starts at vehicle.seat_capacity
        and decrements by 1 per CONFIRMED reservation. PRD §3.6: "The
        reservation is placed in CONFIRMED status if the run has at least
        one seat of capacity_remaining, otherwise it is placed in
        WAITLISTED with a waitlist_position strictly greater than every
        existing waitlist position on the run."

        Claim: after creating one CONFIRMED reservation, the run's
        capacity_remaining decreases by exactly one.
        """
        base = setup_planned_run_sheet(seat_capacity=20)
        emp = unique_employee_code()
        create_reservation(
            base["run_sheet"]["id"], emp,
            base["stops"][0]["id"], base["stops"][-1]["id"],
        )
        from test_helpers import fetch_run_sheet
        rs_after = fetch_run_sheet(base["run_sheet"]["id"])
        assert rs_after["capacity_remaining"] == 19, \
            f"PRD §3.6: capacity_remaining must drop by 1, got {rs_after['capacity_remaining']}"

    def test_waitlist_when_full(self, dispatcher_headers):
        """PRD §3.6: "The reservation is placed in CONFIRMED status if the
        run has at least one seat of capacity_remaining, otherwise it is
        placed in WAITLISTED with a waitlist_position strictly greater
        than every existing waitlist position on the run (and null otherwise)."

        Claim: capacity_remaining=0 results in WAITLISTED status with
        waitlist_position == 1 for the first waitlisted reservation.
        """
        base = setup_planned_run_sheet(seat_capacity=1)
        emp_a = unique_employee_code()
        emp_b = unique_employee_code()
        first = create_reservation(base["run_sheet"]["id"], emp_a,
                                    base["stops"][0]["id"],
                                    base["stops"][-1]["id"])
        assert first["status"] == "CONFIRMED"
        second = create_reservation(base["run_sheet"]["id"], emp_b,
                                     base["stops"][0]["id"],
                                     base["stops"][-1]["id"])
        assert second["status"] == "WAITLISTED"
        assert second["waitlist_position"] == 1, \
            f"PRD §3.6: first waitlisted should have waitlist_position=1, got {second['waitlist_position']}"
