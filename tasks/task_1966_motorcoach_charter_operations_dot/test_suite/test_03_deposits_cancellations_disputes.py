"""Deposit tiers and sufficiency, cancellation fee/refund conservation, and the
dispute fork of the order lifecycle."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, make_customer_headers,
    assert_order, assert_completed_order,
    set_clock, make_customer, make_vehicle, make_driver, make_quote,
    price_quote, accept_quote,
    pay_full_deposit, get_order, get_vehicle, get_driver, get_customer,
    assign_order, setup_pending_deposit_order, setup_confirmed_order,
    setup_in_progress_order, setup_completed_order,
)

DISPATCH = TEST_USERS["dispatch_manager_headers"]


class TestDepositSufficiency:
    def _quote_300mi_5h(self, customer_id):
        quote = make_quote(customer_id, trip_date="2026-09-01T08:00:00Z",
                           return_date="2026-09-01T16:00:00Z",
                           estimated_miles=300, estimated_hours=5)
        return price_quote(quote["id"])

    def test_insufficient_deposit_rejected(self, api):
        """PRD §3.4: "The customer then pays the deposit by tendering
        `amount_cents`; a tender below the required `deposit_cents` is rejected
        with `ERR_INSUFFICIENT_DEPOSIT`."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_deposit
        """
        set_clock()
        customer = make_customer(company_name="Prio Test 2")
        quote = self._quote_300mi_5h(customer["id"])
        order = accept_quote(quote["id"], customer["id"])
        assert order["deposit_cents"] > 100
        res = api.pay_deposit(order["id"], {"amount_cents": 100},
                              make_customer_headers(customer["id"]))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_DEPOSIT)

    def test_deposit_one_cent_short_rejected(self, api):
        """PRD §3.4: "a tender below the required `deposit_cents` is rejected with
        `ERR_INSUFFICIENT_DEPOSIT`." Boundary: exactly one cent short still
        fails.

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_deposit
        """
        set_clock()
        customer = make_customer(company_name="Boundary Payer")
        quote = self._quote_300mi_5h(customer["id"])
        order = accept_quote(quote["id"], customer["id"])
        res = api.pay_deposit(order["id"],
                              {"amount_cents": order["deposit_cents"] - 1},
                              make_customer_headers(customer["id"]))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_DEPOSIT)

    def test_exact_deposit_confirms_order(self, api):
        """PRD §3.4: "A sufficient payment records `deposit_paid_cents` equal to
        the amount tendered, stamps `deposit_paid_at`, adds the amount received
        to the customer's `lifetime_revenue_cents`, and moves the order
        `PENDING_DEPOSIT` → `CONFIRMED`."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_fiscal_on_deposit
        """
        set_clock()
        customer = make_customer(company_name="Exact Payer")
        quote = self._quote_300mi_5h(customer["id"])
        order = accept_quote(quote["id"], customer["id"])
        paid = validate_success(api.pay_deposit(
            order["id"], {"amount_cents": order["deposit_cents"]},
            make_customer_headers(customer["id"])))
        assert paid["status"] == "CONFIRMED"
        assert paid["deposit_paid_cents"] == order["deposit_cents"]
        assert paid["deposit_paid_at"] is not None
        customer_after = get_customer(customer["id"])
        assert customer_after["lifetime_revenue_cents"] == order["deposit_cents"]


class TestDepositTierBoundary:
    def _total_186731_quote(self, customer_id, trip_date):
        """600 mi / 8 h STANDARD prices to subtotal 172500, tax 14231,
        total 186731 (PRD §3.3 rate table + 8.25% tax)."""
        quote = make_quote(customer_id, trip_date=trip_date,
                           return_date="2026-08-08T08:00:00Z",
                           estimated_miles=600, estimated_hours=8)
        return price_quote(quote["id"])

    def test_exactly_168_hours_lead_requires_fifty_percent(self, api):
        """PRD §3.4: "at least 168 hours (seven days) but fewer than 336 requires
        fifty percent" of the quote's `total_cents`, "each figure rounded half-up
        to integer cents."

        Clock 2026-08-01T00:00Z, trip 2026-08-08T00:00Z -> exactly 168 h lead;
        deposit = round(186731 * 0.50) = 93366.

        Design: Difficulty/boundary_precision_check/deposit_tier_boundary_168_hours
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(company_name="Boundary Test")
        quote = self._total_186731_quote(customer["id"], "2026-08-08T00:00:00Z")
        order = accept_quote(quote["id"], customer["id"])
        assert order["deposit_cents"] == 93366

    def test_167_hours_lead_requires_seventy_five_percent(self, api):
        """PRD §3.4: "at least 48 hours but fewer than 168 requires seventy-five
        percent" of the quote's `total_cents`.

        Clock 2026-08-01T01:00Z, trip 2026-08-08T00:00Z -> 167 h lead (one hour
        below the 168 h tier); same-day return keeps the itinerary from
        crossing midnight (PRD §3.3 `requires_overnight`), so the 600 mi / 8 h
        quote prices to total 186731; deposit = round(186731 * 0.75) = 140048.

        Design: Difficulty/boundary_precision_check/deposit_tier_boundary_168_hours
        """
        set_clock("2026-08-01T01:00:00Z")
        customer = make_customer(company_name="Boundary Test 2")
        quote = make_quote(customer["id"], trip_date="2026-08-08T00:00:00Z",
                           return_date="2026-08-08T08:00:00Z",
                           estimated_miles=600, estimated_hours=8)
        quote = price_quote(quote["id"])
        order = accept_quote(quote["id"], customer["id"])
        assert order["deposit_cents"] == 140048


class TestCancellationRefundConservation:
    def _confirmed_600mi_order(self, company, trip_date="2026-08-09T08:00:00Z"):
        """Order for a 600 mi / 8 h trip (total 186731); accepted at
        2026-08-01T00:00Z -> 200 h lead -> 50% deposit = 93366, paid in full."""
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(company_name=company)
        quote = make_quote(customer["id"], trip_date=trip_date,
                           return_date=trip_date.replace("T08:00", "T16:00"),
                           estimated_miles=600, estimated_hours=8)
        quote = price_quote(quote["id"])
        order = accept_quote(quote["id"], customer["id"])
        order = pay_full_deposit(order["id"], customer["id"])
        return customer, order

    def test_customer_cancel_confirmed_conserves_deposit(self, api):
        """PRD §3.6: "at least 168 hours, twenty-five percent" fee and "The fee
        is rounded half-up to integer cents into `cancellation_fee_cents`, and
        the remainder of the deposit comes back as `refund_cents` — the deposit
        paid less the fee." PRD §3.6: "All customer-initiated cancellations
        record `cancelled_by` as `CUSTOMER`."

        200 h lead -> fee = round(93366 * 0.25) = 23342; refund = 70024.

        Design: Difficulty/compensating_invariant/cancel_refund_conserves_deposit_total
        """
        customer, order = self._confirmed_600mi_order("Invariant Test")
        cancelled = validate_success(api.cancel_order(
            order["id"], {"reason": "Plans changed"},
            make_customer_headers(customer["id"])))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancelled_by"] == "CUSTOMER"
        assert cancelled["deposit_paid_cents"] == 93366
        assert cancelled["cancellation_fee_cents"] == 23342
        assert cancelled["refund_cents"] == 70024
        assert (cancelled["cancellation_fee_cents"] + cancelled["refund_cents"]
                == cancelled["deposit_paid_cents"])

    def test_customer_cancel_assigned_releases_vehicle_and_driver(self, api):
        """PRD §3.6: "Cancelling from `ASSIGNED` additionally releases the
        assigned vehicle and every assigned driver back to `AVAILABLE`." The
        same conservation identity holds: "the remainder of the deposit comes
        back as `refund_cents` — the deposit paid less the fee."

        Design: Difficulty/compensating_invariant/cancel_refund_conserves_deposit_total
        """
        customer, order = self._confirmed_600mi_order("Invariant Assigned")
        vehicle = make_vehicle()
        driver = make_driver()
        order = assign_order(order["id"], vehicle["id"], driver["id"])
        cancelled = validate_success(api.cancel_order(
            order["id"], {"reason": "Plans changed"},
            make_customer_headers(customer["id"])))
        assert cancelled["status"] == "CANCELLED"
        assert (cancelled["cancellation_fee_cents"] + cancelled["refund_cents"]
                == cancelled["deposit_paid_cents"] == 93366)
        assert get_vehicle(vehicle["id"])["status"] == "AVAILABLE"
        assert get_driver(driver["id"])["status"] == "AVAILABLE"

    def test_cancel_pending_deposit_has_no_fee_no_refund(self, api):
        """PRD §3.6: "A customer may cancel an order while it stands in
        `PENDING_DEPOSIT` — no fee and no refund, since nothing was ever paid".

        Design: Difficulty/compensating_invariant/cancel_refund_conserves_deposit_total
        """
        ctx = setup_pending_deposit_order()
        cancelled = validate_success(api.cancel_order(
            ctx["order"]["id"], {"reason": "Changed my mind"},
            make_customer_headers(ctx["customer"]["id"])))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancelled_by"] == "CUSTOMER"
        assert cancelled["cancellation_fee_cents"] == 0
        assert cancelled["refund_cents"] == 0
        assert cancelled["deposit_paid_cents"] == 0

    def test_cancellation_fee_at_exactly_72_hours(self, api):
        """PRD §3.6: "at least 72 hours, fifty percent" of `deposit_paid_cents`.

        Trip 2026-08-04T00:00Z; accepted at 2026-08-01T00:00Z (72 h lead -> 75%
        deposit = 140048, paid in full); cancelled at the same clock -> exactly
        72 h lead -> fee = round(140048 * 0.50) = 70024, refund = 70024.

        Design: Corner/calculations/cancellation_fee_at_exactly_72_hours
        """
        set_clock("2026-08-01T00:00:00Z")
        customer = make_customer(company_name="Fee Bound")
        quote = make_quote(customer["id"], trip_date="2026-08-04T00:00:00Z",
                           return_date="2026-08-04T08:00:00Z",
                           estimated_miles=600, estimated_hours=8)
        quote = price_quote(quote["id"])
        order = accept_quote(quote["id"], customer["id"])
        assert order["deposit_cents"] == 140048
        order = pay_full_deposit(order["id"], customer["id"])
        cancelled = validate_success(api.cancel_order(
            order["id"], {"reason": "Changed plans"},
            make_customer_headers(customer["id"])))
        assert cancelled["cancellation_fee_cents"] == 70024
        assert cancelled["refund_cents"] == 70024
        assert (cancelled["cancellation_fee_cents"] + cancelled["refund_cents"]
                == 140048)

    def test_cancel_completed_order_returns_invalid_state(self, api):
        """PRD §3.6: "A customer may cancel an order while it stands in
        `PENDING_DEPOSIT` — no fee and no refund, since nothing was ever paid —
        or from `CONFIRMED` or `ASSIGNED`, where a cancellation fee applies."
        No cancellation transition exists from `COMPLETED`. PRD §2.8: "4. State
        validity: the target entity is in a state from which the requested
        transition exists per Section 3, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/order_cancel_from_completed_returns_invalid_state
        """
        ctx = setup_completed_order(actual_miles=100, actual_hours=4)
        res = api.cancel_order(ctx["order"]["id"], {"reason": "Too late"},
                               make_customer_headers(ctx["customer"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)


class TestDisputeFork:
    def _disputed_order(self, api, company="Dispute Test"):
        ctx = setup_in_progress_order(
            quote_overrides={"trip_date": "2026-07-15T08:00:00Z",
                             "return_date": "2026-07-15T18:00:00Z",
                             "estimated_miles": 500, "estimated_hours": 8},
            clock_iso="2026-07-01T00:00:00Z")
        disputed = validate_success(api.dispute_order(
            ctx["order"]["id"],
            {"reason": "Driver was late and missed a scheduled stop"},
            make_customer_headers(ctx["customer"]["id"])))
        ctx["order"] = disputed
        return ctx

    def test_dispute_moves_in_progress_to_disputed(self, api):
        """PRD §3.6: "A customer who contests an in-progress trip files a dispute
        carrying a non-empty `reason`, moving the order `IN_PROGRESS` →
        `DISPUTED` and recording that reason in `cancellation_reason`."

        Design: Difficulty/non_linear_state_machine/charter_order_branching_with_dispute_cycle
        """
        ctx = self._disputed_order(api)
        assert ctx["order"]["status"] == "DISPUTED"
        assert (ctx["order"]["cancellation_reason"]
                == "Driver was late and missed a scheduled stop")

    def test_disputed_order_completes_via_dispatch(self, api):
        """PRD §3.6: "A disputed order resolves in exactly two ways: dispatch
        completes the trip, settling it precisely as §3.5 describes — actuals,
        extra hours, fuel surcharge, final invoice, and every cascade — moving
        `DISPUTED` → `COMPLETED`".

        Design: Difficulty/non_linear_state_machine/charter_order_branching_with_dispute_cycle
        """
        ctx = self._disputed_order(api, "Dispute Complete")
        completed = validate_success(api.complete_trip(
            ctx["order"]["id"], {"actual_miles": 500, "actual_hours": 8},
            DISPATCH))
        assert_completed_order(completed)
        assert completed["status"] == "COMPLETED"
        assert completed["extra_hours"] == 0.0
        # 500 actual miles -> 5% fuel tier on quoted subtotal 147500.
        assert completed["fuel_surcharge_cents"] == 7375

    def test_disputed_order_cancelled_by_dispatch_on_operator_terms(self, api):
        """PRD §3.6: "or dispatch cancels it on the operator terms above, moving
        `DISPUTED` → `CANCELLED`." PRD §3.6: "Operator-initiated cancellations
        waive the fee entirely, refund the deposit in full, release the vehicle
        and drivers back to `AVAILABLE`, and record `cancelled_by` as
        `OPERATOR`."

        Design: Difficulty/non_linear_state_machine/charter_order_branching_with_dispute_cycle
        """
        ctx = self._disputed_order(api, "Dispute Cancel")
        cancelled = validate_success(api.cancel_order(
            ctx["order"]["id"], {"reason": "Service failure"}, DISPATCH))
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancelled_by"] == "OPERATOR"
        assert cancelled["cancellation_fee_cents"] == 0
        assert cancelled["refund_cents"] == cancelled["deposit_paid_cents"]
        assert cancelled["deposit_paid_cents"] > 0
        assert get_vehicle(ctx["vehicle"]["id"])["status"] == "AVAILABLE"
        assert get_driver(ctx["driver"]["id"])["status"] == "AVAILABLE"
