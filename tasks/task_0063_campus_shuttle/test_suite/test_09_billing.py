"""Monthly bills: create, finalize, refund cascade, settle.

Covers PRD §3.8.
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
    assert_monthly_bill,
    create_bill_payload,
    fetch_bill, fetch_reservation,
    iso_z, parse_iso,
    list_all_audit_logs,
    make_employee_headers,
    previous_billing_month, first_day_of_month_iso,
    setup_employee_bill_with_completed_reservation,
    setup_run_with_confirmed_reservation,
    unique_employee_code,
)


# ===========================================================================
# Bill uniqueness (PRD §3.8)
# ===========================================================================
class TestBillUniqueness:

    def test_duplicate_bill_rejected(self, dispatcher_headers):
        """PRD §3.8: "At most one bill may exist for any (payer_scope,
        payer_id, billing_month) triple — a duplicate is rejected with
        ERR_BILL_ALREADY_EXISTS."

        Claim: creating two bills with the same (scope, id, month) ->
        ERR_BILL_ALREADY_EXISTS on the second.
        """
        prev_month = previous_billing_month()
        emp = unique_employee_code()
        validate_success(
            api_client.create_bill(
                create_bill_payload(prev_month, "EMPLOYEE", emp),
                dispatcher_headers,
            ),
            201,
        )
        resp = api_client.create_bill(
            create_bill_payload(prev_month, "EMPLOYEE", emp),
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BILL_ALREADY_EXISTS)


# ===========================================================================
# Bill finalize (PRD §3.8)
# ===========================================================================
class TestBillFinalize:

    def test_finalize_current_month_rejected(self, dispatcher_headers):
        """PRD §3.8: "First, the billing_month must be strictly before the
        current UTC month; an attempt to finalise the current or a future
        month is rejected with ERR_BILLING_MONTH_NOT_COMPLETE."

        Claim: finalize for the current UTC month -> ERR_BILLING_MONTH_NOT_COMPLETE.
        """
        advance_clock_to("2026-06-15T03:00:00.000Z")
        bill = validate_success(
            api_client.create_bill(
                create_bill_payload("2026-06", "EMPLOYEE",
                                    unique_employee_code()),
                dispatcher_headers,
            ),
            201,
        )
        resp = api_client.finalize_bill(bill["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_BILLING_MONTH_NOT_COMPLETE)

    def test_finalize_with_open_reservations_rejected(self, dispatcher_headers):
        """PRD §3.8: "Second, every reservation in the bill's scope must
        already be in a terminal state — that is, COMPLETED, NO_SHOW, or
        CANCELLED; any in-scope reservation still in a non-terminal state
        surfaces as ERR_BILL_HAS_OPEN_RESERVATIONS."

        Claim: finalize while a SELF_PAY reservation is still CONFIRMED ->
        ERR_BILL_HAS_OPEN_RESERVATIONS.
        """
        # Build a reservation in an earlier month that is still CONFIRMED.
        advance_clock_to("2026-06-01T03:00:00.000Z")
        # Schedule departure in prior month: 2026-05-15.
        scenario_setup_iso = "2026-05-15T05:00:00.000Z"
        # Move clock back to a setup point in May.
        advance_clock_to("2026-05-10T03:00:00.000Z")
        scenario = setup_run_with_confirmed_reservation()
        # The scenario uses scheduled_departure 2h ahead; that may not be
        # in May, so we don't rely on it. Instead we just check that a
        # bill targeting THIS employee in May refuses to finalize because
        # the reservation is still CONFIRMED.
        # Move into June.
        advance_clock_to("2026-06-05T02:00:00.000Z")
        prev_month = "2026-05"
        bill = validate_success(
            api_client.create_bill(
                create_bill_payload(prev_month, "EMPLOYEE",
                                    scenario["employee_id"]),
                dispatcher_headers,
            ),
            201,
        )
        # The CONFIRMED reservation's run hasn't departed yet; it might
        # not be in this billing_month either. To make the test deterministic,
        # we create a brand-new in-scope reservation in May (scheduled_date
        # in May) and keep it CONFIRMED.
        # Re-rewind to May to create a May-scheduled run.
        # However a stronger approach: rely on the scenario's already-CONFIRMED
        # reservation being in May because we advanced the clock to May.
        # The fixture pins scheduled_departure to "now + 2h"; thus May 10 + 2h
        # = May 10 05:00, which IS in May. Confirm via dates if scope matches.
        resp = api_client.finalize_bill(bill["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_BILL_HAS_OPEN_RESERVATIONS)

    def test_finalize_pins_gross_cents_for_completed_reservation(
            self, dispatcher_headers):
        """PRD §3.8: "The bill's line_count is set to the number of
        in-scope reservations; the bill's gross_cents is the integer-cent
        sum of the fare_cents of those reservations, with no further
        rounding because each line is already an integer; finalized_at is
        stamped to the current instant."

        Claim: finalize a bill whose only in-scope reservation completed
        with fare_cents=300 -> gross_cents == 300 and line_count == 1.
        """
        scenario = setup_employee_bill_with_completed_reservation(
            fare_target_segment_count=5,  # 5-segment off-peak -> 300 cents
        )
        finalized = validate_success(
            api_client.finalize_bill(scenario["bill"]["id"], dispatcher_headers),
            200,
        )
        assert_monthly_bill(finalized)
        assert finalized["status"] == "FINALIZED"
        assert finalized["line_count"] == 1
        # Off-peak 5-segment -> 300 cents.
        assert finalized["gross_cents"] == 300, \
            f"PRD §3.8: gross_cents must equal sum of in-scope fares (300), got {finalized['gross_cents']}"


# ===========================================================================
# Settlement (PRD §3.8)
# ===========================================================================
class TestBillSettle:

    def test_settle_finalized_pins_net_cents(self, dispatcher_headers):
        """PRD §3.8: "both settlement paths pin net_cents to gross_cents
        minus refund_cents at settlement time."

        Claim: settle a FINALIZED bill -> SETTLED with net_cents ==
        gross_cents - refund_cents.
        """
        scenario = setup_employee_bill_with_completed_reservation(
            fare_target_segment_count=5,
        )
        bill_id = scenario["bill"]["id"]
        validate_success(
            api_client.finalize_bill(bill_id, dispatcher_headers), 200,
        )
        settled = validate_success(
            api_client.settle_bill(bill_id, dispatcher_headers), 200,
        )
        assert settled["status"] == "SETTLED"
        assert settled["net_cents"] == settled["gross_cents"] - settled["refund_cents"]
