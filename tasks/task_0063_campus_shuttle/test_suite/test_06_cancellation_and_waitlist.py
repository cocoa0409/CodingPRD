"""Reservation cancellation, waitlist promotion, no-show penalty.

Covers PRD §3.6 (cancel window, waitlist promotion, no-show penalty).
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
    api_client,
    check_in_rider, complete_run_sheet,
    create_reservation,
    depart_run_sheet,
    expected_no_show_points,
    fetch_reservation, fetch_run_sheet,
    iso_z, parse_iso,
    make_driver_headers, make_employee_headers,
    setup_run_with_confirmed_reservation,
    setup_run_with_capacity_full_and_waitlist,
    start_boarding,
    unique_employee_code,
)


# ===========================================================================
# Cancel window (PRD §3.6)
# ===========================================================================
class TestCancelWindow:

    def test_employee_cancel_exactly_15_min_before_succeeds(
            self, dispatcher_headers):
        """PRD §3.6: "Employee-triggered cancellation requires that the
        current instant is at or before the run's scheduled_departure
        minus 15 minutes; an attempt later than that surfaces as
        ERR_CANCEL_WINDOW_CLOSED."

        Claim: cancel exactly 15 minutes before scheduled_departure is
        permitted (boundary is inclusive on the early side).
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        base = setup_run_with_confirmed_reservation()
        sched = parse_iso(base["run_sheet"]["scheduled_departure"])
        advance_clock_to(iso_z(sched - timedelta(minutes=15)))
        cancelled = validate_success(
            api_client.cancel_reservation(
                base["reservation"]["id"],
                make_employee_headers(base["employee_id"]),
            ),
            200,
        )
        assert cancelled["status"] == "CANCELLED"

    def test_employee_cancel_inside_lockout_rejected(self, dispatcher_headers):
        """PRD §3.6: "Employee-triggered cancellation requires that the
        current instant is at or before the run's scheduled_departure
        minus 15 minutes; an attempt later than that surfaces as
        ERR_CANCEL_WINDOW_CLOSED."

        Claim: cancel less than 15 minutes before scheduled_departure ->
        ERR_CANCEL_WINDOW_CLOSED.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        base = setup_run_with_confirmed_reservation()
        sched = parse_iso(base["run_sheet"]["scheduled_departure"])
        advance_clock_to(iso_z(sched - timedelta(minutes=10)))
        resp = api_client.cancel_reservation(
            base["reservation"]["id"],
            make_employee_headers(base["employee_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CANCEL_WINDOW_CLOSED)

    def test_cancel_idempotency_second_cancel_rejected(self, dispatcher_headers):
        """PRD §3.6: "A second cancel arriving for an already-cancelled
        reservation is rejected idempotently with ERR_INVALID_STATE."

        Claim: cancel an already-CANCELLED reservation -> ERR_INVALID_STATE.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        base = setup_run_with_confirmed_reservation()
        validate_success(
            api_client.cancel_reservation(
                base["reservation"]["id"],
                make_employee_headers(base["employee_id"]),
            ),
            200,
        )
        resp = api_client.cancel_reservation(
            base["reservation"]["id"],
            make_employee_headers(base["employee_id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ===========================================================================
# Waitlist promotion (PRD §3.6)
# ===========================================================================
class TestWaitlistPromotion:

    def test_cancel_confirmed_promotes_waitlisted(self, dispatcher_headers):
        """PRD §3.6: "A cancel on a CONFIRMED reservation stamps
        cancelled_at, frees a seat on the run's capacity_remaining, and —
        if any WAITLISTED reservation exists on the same run and the run
        is still in PLANNED — promotes the lowest waitlist_position to
        CONFIRMED."

        Claim: cancelling the only CONFIRMED reservation promotes the
        first WAITLISTED to CONFIRMED, clearing its waitlist_position.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        scenario = setup_run_with_capacity_full_and_waitlist(seat_capacity=1)
        confirmed = scenario["confirmed"][0]
        validate_success(
            api_client.cancel_reservation(
                confirmed["reservation"]["id"],
                make_employee_headers(confirmed["employee_id"]),
            ),
            200,
        )
        promoted = fetch_reservation(scenario["waitlisted"]["id"])
        assert promoted["status"] == "CONFIRMED", \
            f"PRD §3.6: waitlist promotion should make WAITLISTED -> CONFIRMED, got {promoted['status']}"
        assert promoted.get("waitlist_position") in (None, 0) or promoted.get("waitlist_position") is None

    def test_cancel_confirmed_no_waitlist_no_promotion(self, dispatcher_headers):
        """PRD §3.6: "A cancel on a CONFIRMED reservation stamps
        cancelled_at, frees a seat on the run's capacity_remaining, and —
        if any WAITLISTED reservation exists on the same run and the run
        is still in PLANNED — promotes the lowest waitlist_position to
        CONFIRMED."

        Claim: with NO waitlisted reservations the system performs no
        promotion and frees the seat (capacity_remaining increments).
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        scenario = setup_run_with_confirmed_reservation()
        run_id = scenario["run_sheet"]["id"]
        before = fetch_run_sheet(run_id)
        validate_success(
            api_client.cancel_reservation(
                scenario["reservation"]["id"],
                make_employee_headers(scenario["employee_id"]),
            ),
            200,
        )
        after = fetch_run_sheet(run_id)
        assert after["capacity_remaining"] == before["capacity_remaining"] + 1


# ===========================================================================
# No-show penalty (PRD §3.6)
# ===========================================================================
class TestNoShowPenalty:

    def test_no_show_penalty_first_offpeak(self, dispatcher_headers):
        """PRD §3.6: "The departure cascade — every CONFIRMED reservation
        that did not check in transitions to NO_SHOW — assigns each
        affected reservation a no_show_penalty_points value computed as
        follows: start at a base of 10; add 5 if the run's
        scheduled_departure projects into a peak window; subtract 3 if
        the run's delay_minutes_accumulated at departure is at least 30
        (a partial mitigation for delays that contributed to the missed
        run); add 2 for each prior NO_SHOW reservation by the same
        employee whose run's scheduled_departure falls in the trailing
        30-day window exclusive of this run; floor the result at zero so
        the value can never go negative."

        Claim: first NO_SHOW for an employee on an off-peak run with no
        delay mitigation -> 10 points.
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        # Off-peak window: ensure scheduled_departure does NOT intersect.
        scenario = setup_run_with_confirmed_reservation(
            peak_windows=[["00:00", "00:30"]],
        )
        sched = parse_iso(scenario["run_sheet"]["scheduled_departure"])
        advance_clock_to(iso_z(sched - timedelta(minutes=10)))
        start_boarding(scenario["run_sheet"]["id"])
        advance_clock_to(iso_z(sched + timedelta(seconds=10)))
        depart_run_sheet(scenario["run_sheet"]["id"])
        res_after = fetch_reservation(scenario["reservation"]["id"])
        assert res_after["status"] == "NO_SHOW"
        expected = expected_no_show_points(
            is_peak=False, has_delay_mitigation=False, prior_no_show_count=0,
        )
        assert res_after["no_show_penalty_points"] == expected, \
            f"PRD §3.6: first off-peak NO_SHOW expects {expected} points, got {res_after['no_show_penalty_points']}"
        assert expected == 10
