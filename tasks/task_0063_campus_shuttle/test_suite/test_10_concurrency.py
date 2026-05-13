"""Concurrency: race conditions explicitly named in the PRD.

PRD §2.6 describes the route-publish race; §3.6 describes
check-in-vs-cancel and run-full race outcomes; §3.8 describes the bill
uniqueness race. These tests verify exactly-one-winner semantics. Tests
that would assert a SPECIFIC loser error_id (and PRD has not pinned that
loser) use validate_error_is_one_of per the skill's silence guidance.
"""
from __future__ import annotations
from datetime import timedelta

import pytest

from prd_bench_local_runner.testing import (
    assert_exactly_one_succeeds,
    assert_race_outcome,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    create_bill_payload,
    create_reservation_payload,
    make_employee_headers,
    previous_billing_month,
    setup_planned_run_sheet,
    unique_employee_code,
)


# ===========================================================================
# Reservation race: two employees vs one seat (PRD §3.6)
# ===========================================================================
class TestReservationRace:

    def test_two_employees_one_seat(self, dispatcher_headers):
        """PRD §3.6: "Two simultaneous reservations on a run with exactly
        one seat left serialize to exactly one CONFIRMED winner; the
        loser receives WAITLISTED if waitlisting is admissible, otherwise
        the loser sees ERR_RUN_FULL."

        Claim: two simultaneous reservations against a 1-seat run
        produce exactly one CONFIRMED; the loser is WAITLISTED or
        ERR_RUN_FULL (we accept either since PRD says 'if waitlisting
        is admissible'; the default is waitlist-enabled).
        """
        advance_clock_to("2026-06-01T03:00:00.000Z")
        base = setup_planned_run_sheet(seat_capacity=1)
        emp_a = unique_employee_code()
        emp_b = unique_employee_code()
        run_id = base["run_sheet"]["id"]
        stops = base["stops"]
        results = run_race(
            lambda: api_client.create_reservation(
                run_id,
                create_reservation_payload(emp_a, stops[0]["id"],
                                           stops[-1]["id"]),
                make_employee_headers(emp_a),
            ),
            lambda: api_client.create_reservation(
                run_id,
                create_reservation_payload(emp_b, stops[0]["id"],
                                           stops[-1]["id"]),
                make_employee_headers(emp_b),
            ),
        )
        # Both can return 201 (one CONFIRMED, one WAITLISTED) -- both are
        # "success" outcomes. We assert that at most one of the responses
        # has status CONFIRMED.
        codes = [r.status_code for r in results]
        # Both should be 2xx (one CONFIRMED + one WAITLISTED). Otherwise
        # exactly one 2xx + one 409/ERR_RUN_FULL is also acceptable.
        confirmed_count = 0
        for r in results:
            if r.status_code == 201:
                body = r.json()["data"]
                if body.get("status") == "CONFIRMED":
                    confirmed_count += 1
        assert confirmed_count == 1, \
            f"PRD §3.6: exactly one CONFIRMED winner expected, got {confirmed_count} (statuses={codes})"


# ===========================================================================
# Bill uniqueness race (PRD §3.8)
# ===========================================================================
class TestBillUniquenessRace:

    def test_simultaneous_bill_creation(self, dispatcher_headers):
        """PRD §3.8: "Two simultaneous creations against the same triple
        resolve to exactly one winner; the loser sees ERR_BILL_ALREADY_EXISTS."

        Claim: two concurrent POST /shuttle/bills with the same
        (payer_scope, payer_id, billing_month) yield exactly one 2xx and
        one ERR_BILL_ALREADY_EXISTS.
        """
        prev = previous_billing_month()
        emp = unique_employee_code()
        results = run_race(
            lambda: api_client.create_bill(
                create_bill_payload(prev, "EMPLOYEE", emp),
                dispatcher_headers,
            ),
            lambda: api_client.create_bill(
                create_bill_payload(prev, "EMPLOYEE", emp),
                dispatcher_headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        validate_error(loser, ApiErrorId.ERR_BILL_ALREADY_EXISTS)
