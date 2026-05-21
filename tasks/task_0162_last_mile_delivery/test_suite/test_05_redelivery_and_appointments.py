"""Redelivery limits, customer rolling 30-day cap, and appointment
supersede cascades.

Covers PRD §3.5 redelivery preconditions and PRD §3.7 customer
rolling-30-day count, plus appointment auto-supersede on reattempt.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    CUSTOMER_REDELIVERY_CAP_30D,
    MAX_REDELIVERY_ATTEMPTS,
    TEST_USERS,
    add_stop,
    advance_clock_by_days,
    advance_clock_to,
    api_client,
    check_in_driver,
    create_appointment_payload,
    create_parcel,
    create_route,
    current_clock,
    dispatch_route,
    induct_to_hub,
    iso_utc,
    make_customer_headers,
    make_driver_headers,
    move_clock_into_window,
    parse_iso,
    reattempt_parcel,
    record_attempt,
    reset_driver_to_on_duty,
    setup_appointment_on_exception_parcel,
    setup_baseline,
    setup_parcel_in_exception,
    sort_parcel,
    validate_error,
    validate_success,
    walk_parcel_to_out_for_delivery,
    walk_parcel_to_sorted,
)


def _cycle_no_one_home(ctx, api):
    """Run one full NO_ONE_HOME cycle on ctx['parcel'] and reset ctx
    for the next attempt. Returns updated ctx."""
    move_clock_into_window(ctx["parcel"])
    api.create_attempt(
        ctx["parcel"]["id"],
        {"route_stop_id": ctx["stop"]["id"],
         "outcome": "NO_ONE_HOME"},
        make_driver_headers(ctx["driver"]["id"]),
    )
    return ctx


def _re_route_after_exception(ctx, api):
    """After EXCEPTION, close+reset the driver, run reattempt + new
    route + dispatch so a further attempt can be recorded. PRD §3.2:
    driver cycles OFF_DUTY -> ON_DUTY -> ON_ROUTE -> RETURNED ->
    OFF_DUTY, so a new dispatch requires the driver to be ON_DUTY,
    reached only via close-route + check-out + check-in.

    PRD §3.7: stop assignment fails ERR_TIME_WINDOW_INFEASIBLE when
    the cursor exceeds the parcel's time_window_end. PRD §3.5 says
    reattempt does NOT re-set the parcel window, so the new route
    must be planned on the same calendar date as the parcel window;
    otherwise the cursor (08:00 of planned_date) is after the
    parcel's window_end.
    """
    reset_driver_to_on_duty(ctx["driver"]["id"], ctx["route"]["id"])
    reattempt_parcel(ctx["parcel"]["id"])
    # Pin the new route to the parcel's window date so stop assignment
    # does not fall outside the original window (PRD §3.7).
    parcel_window_date = ctx["parcel"]["time_window_start"][:10]
    new_route = create_route(
        ctx["center"]["id"], ctx["driver"]["id"],
        planned_date=parcel_window_date,
    )
    new_stop = add_stop(new_route["id"], ctx["parcel"]["id"])
    dispatch_route(new_route["id"])
    ctx["stop"] = new_stop
    ctx["route"] = new_route
    ctx["parcel"] = validate_success(api.get_parcel(
        ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
    ), 200)
    return ctx


# ---------------------------------------------------------------------------
# Per-parcel redelivery counter
# ---------------------------------------------------------------------------
class TestRedeliveryAttemptsCounter:

    def test_first_failure_sets_counter_to_one(self, api):
        """PRD §3.5: 'redelivery_attempts is incremented by one.'"""
        ctx = walk_parcel_to_out_for_delivery()
        move_clock_into_window(ctx["parcel"])
        api.create_attempt(
            ctx["parcel"]["id"],
            {"route_stop_id": ctx["stop"]["id"],
             "outcome": "REFUSED"},
            make_driver_headers(ctx["driver"]["id"]),
        )
        re_p = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert re_p["redelivery_attempts"] == 1
        assert re_p["last_attempt_outcome"] == "REFUSED"

    def test_return_to_sender_admissible_at_max_attempts(self, api):
        """PRD §3.5: 'admissible when the parcel has exhausted its
        reattempts (redelivery_attempts is at or above three)'."""
        ctx = walk_parcel_to_out_for_delivery()
        # Run 3 NO_ONE_HOME cycles.
        for i in range(MAX_REDELIVERY_ATTEMPTS):
            _cycle_no_one_home(ctx, api)
            if i < MAX_REDELIVERY_ATTEMPTS - 1:
                _re_route_after_exception(ctx, api)
        # Parcel now in EXCEPTION with redelivery_attempts == 3.
        re_p = validate_success(api.get_parcel(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert re_p["redelivery_attempts"] == MAX_REDELIVERY_ATTEMPTS
        terminal = validate_success(api.return_to_sender(
            ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
        ), 200)
        assert terminal["status"] == "RETURNED_TO_SENDER"


# ---------------------------------------------------------------------------
# Reattempt auto-supersedes pending appointment
# ---------------------------------------------------------------------------
class TestReattemptCascadesToAppointmentSupersede:

    def test_reattempt_supersedes_pending_appointment(self, api):
        """PRD §3.5: 'As a side effect of the reattempt, any
        Appointment for the same parcel that is still in PENDING is
        auto-superseded to SUPERSEDED.'"""
        ctx = setup_appointment_on_exception_parcel()
        # Reattempt -> SORTED -> appointment must be SUPERSEDED.
        reattempt_parcel(ctx["parcel"]["id"])
        # No GET /appointments/{id}, but accept_appointment on a
        # non-PENDING appointment fails with ERR_INVALID_STATE.
        res = api.accept_appointment(
            ctx["appointment"]["id"], TEST_USERS["dispatcher_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# Customer rolling 30-day cap
# ---------------------------------------------------------------------------
class TestCustomerRollingRedeliveryCounter:

    def test_customer_rolling_counter_starts_at_zero(self, api):
        """PRD §3.1: 'The aggregated counter redelivery_attempts_used_30d
        on the customer record is recomputed on demand when the
        customer record is read'."""
        base = setup_baseline()
        res = api.get_customer(
            base["customer"]["id"],
            make_customer_headers(base["customer"]["id"]),
        )
        cust = validate_success(res, 200)
        assert cust["redelivery_attempts_used_30d"] == 0

    def test_customer_counter_increases_after_no_one_home(self, api):
        """PRD §3.7: 'the system counts the number of DeliveryAttempt
        rows whose outcome is either NO_ONE_HOME or REFUSED and whose
        attempted_at is greater than or equal to the instant exactly
        30 days before Clock.now'."""
        ctx = walk_parcel_to_out_for_delivery()
        move_clock_into_window(ctx["parcel"])
        api.create_attempt(
            ctx["parcel"]["id"],
            {"route_stop_id": ctx["stop"]["id"],
             "outcome": "NO_ONE_HOME"},
            make_driver_headers(ctx["driver"]["id"]),
        )
        cust = validate_success(api.get_customer(
            ctx["customer"]["id"],
            make_customer_headers(ctx["customer"]["id"]),
        ), 200)
        assert cust["redelivery_attempts_used_30d"] == 1
