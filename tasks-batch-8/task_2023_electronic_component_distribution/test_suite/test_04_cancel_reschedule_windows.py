"""Cancellation terms, reschedule windows, and the order OCC guard (PRD §3.3, §2.10)."""
from test_helpers import (
    ADMIN,
    SALES,
    WAREHOUSE,
    ApiErrorId,
    advance_clock,
    create_allocation_run_for_part,
    create_customer,
    create_order,
    get_order_line,
    get_order_lines,
    get_success_data,
    order_line_spec,
    publish_run,
    receive_lot,
    reschedule_payload,
    setup_acknowledged_order,
    setup_allocated_order,
    setup_catalog,
    ship_line,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestCancelWindowBoundary:
    def test_cancel_window_just_before_boundary_allowed(self, api):
        """PRD §3.3: "rejecting with `ERR_CANCEL_WINDOW_CLOSED` once the logical
        clock has reached or passed the line's `cancel_by_date` — the window is
        open only strictly before that date."

        Design: Difficulty/boundary_precision_check/cancel_window_exact_boundary
        """
        sc = setup_acknowledged_order(quantity=5, ship_date="2026-10-01",
                                      line_code="LIN-C")
        order_line = sc["order_line"]
        assert order_line["cancel_by_date"] == "2026-09-01"
        advance_clock("2026-08-31T23:59:00Z")

        cancelled = validate_success(
            api.cancel_order_line(sc["order"]["id"], order_line["id"], SALES), 200)
        assert cancelled["status"] == "CANCELLED", (
            "One minute before cancel_by_date the window is still open"
        )

    def test_cancel_window_exact_boundary_rejected(self, api):
        """PRD §3.3: "rejecting with `ERR_CANCEL_WINDOW_CLOSED` once the logical
        clock has reached or passed the line's `cancel_by_date` — the window is
        open only strictly before that date."
        PRD §3.3: "From those snapshots each line's `cancel_by_date` is computed
        as its `ship_date` minus `cancel_window_days_snapshot`."

        Design: Difficulty/boundary_precision_check/cancel_window_exact_boundary
        """
        sc = setup_acknowledged_order(quantity=5, ship_date="2026-10-01",
                                      line_code="LIN-C")
        order_line = sc["order_line"]
        assert order_line["cancel_by_date"] == "2026-09-01", (
            "ship_date 2026-10-01 minus the default 30-day cancel window"
        )
        advance_clock("2026-09-01T00:00:00Z")

        resp = api.cancel_order_line(sc["order"]["id"], order_line["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_CANCEL_WINDOW_CLOSED)
        after = get_order_line(order_line["id"])
        assert after["status"] == "OPEN", "At exactly cancel_by_date the window is closed"


class TestNcnrCancel:
    def test_ncnr_line_cancel_rejected(self, api):
        """PRD §3.3: "the NCNR check first, rejecting with `ERR_LINE_NCNR` when
        `ncnr_snapshot` is true, then the window check".

        Design: Corner/errors/ncnr_line_cancel_rejected
        """
        sc = setup_acknowledged_order(quantity=5, ship_date="2026-10-01",
                                      line_code="LIN-NC", line_kw={"ncnr": True})
        order_line = sc["order_line"]
        assert order_line["ncnr_snapshot"] is True

        resp = api.cancel_order_line(sc["order"]["id"], order_line["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_LINE_NCNR)
        after = get_order_line(order_line["id"])
        assert after["status"] == "OPEN"


class TestRescheduleWindows:
    def test_reschedule_window_closed_rejected(self, api):
        """PRD §3.3: "Rescheduling moves a line's `ship_date` to a
        `new_ship_date`, permitted to a `SalesRep` or the owning `CustomerBuyer`
        while the order is `ACKNOWLEDGED` and while the logical clock is still
        strictly earlier than the current `ship_date` minus
        `reschedule_window_days_snapshot` — at or past that cutoff the attempt
        is `ERR_RESCHEDULE_WINDOW_CLOSED`."

        Design: Corner/errors/reschedule_window_closed_rejected
        """
        sc = setup_acknowledged_order(quantity=5, ship_date="2026-08-25",
                                      line_code="LIN-RW",
                                      line_kw={"reschedule_window_days": 20})
        order_line = sc["order_line"]
        advance_clock("2026-08-06T00:00:00Z")  # past the 2026-08-05 deadline
        order = get_success_data(api.get_order(sc["order"]["id"], ADMIN))

        resp = api.reschedule_order_line(
            sc["order"]["id"], order_line["id"],
            reschedule_payload("2026-09-10", order["version"]), SALES)
        validate_error(resp, ApiErrorId.ERR_RESCHEDULE_WINDOW_CLOSED)
        after = get_order_line(order_line["id"])
        assert after["ship_date"] == "2026-08-25", "Rejected reschedule mutates nothing"

    def test_reschedule_to_past_date_rejected(self, api):
        """PRD §3.3: "The new date must lie in the future, and for an NCNR line
        the reschedule may only push the date outward, never pull it in; either
        violation surfaces `ERR_SHIP_DATE_IN_PAST`."

        Design: Corner/errors/reschedule_to_past_date_rejected
        """
        sc = setup_acknowledged_order(quantity=5, ship_date="2026-12-01",
                                      line_code="LIN-PD")
        order_line = sc["order_line"]
        order = get_success_data(api.get_order(sc["order"]["id"], ADMIN))

        resp = api.reschedule_order_line(
            sc["order"]["id"], order_line["id"],
            reschedule_payload("2026-07-01", order["version"]), SALES)
        validate_error(resp, ApiErrorId.ERR_SHIP_DATE_IN_PAST)
        after = get_order_line(order_line["id"])
        assert after["ship_date"] == "2026-12-01"

    def test_reschedule_stale_order_version_rejected(self, api):
        """PRD §2.10: "a request to reschedule an order line must carry
        `expected_order_version` equal to the order's current `version`; a
        mismatch is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)".
        PRD §3.3: "A successful reschedule rewrites the line's `ship_date`,
        recomputes its `cancel_by_date` from the snapshot window, and increments
        the order's `version`."

        Design: Corner/complexity_layers/reschedule_stale_order_version_rejected
        """
        sc = setup_acknowledged_order(quantity=5, ship_date="2026-12-01",
                                      line_code="LIN-OC2")
        order_line = sc["order_line"]
        order = get_success_data(api.get_order(sc["order"]["id"], ADMIN))
        stale_version = order["version"]

        moved = validate_success(
            api.reschedule_order_line(
                sc["order"]["id"], order_line["id"],
                reschedule_payload("2026-12-15", stale_version), SALES),
            200)
        assert moved["ship_date"] == "2026-12-15"
        assert moved["cancel_by_date"] == "2026-11-15", (
            "cancel_by_date recomputed as 2026-12-15 minus the 30-day snapshot"
        )

        resp = api.reschedule_order_line(
            sc["order"]["id"], order_line["id"],
            reschedule_payload("2026-12-20", stale_version), SALES)
        validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)
        after = get_order_line(order_line["id"])
        assert after["ship_date"] == "2026-12-15", "The stale write did not apply"


class TestHoldBeatsTemporal:
    def _setup_hold_with_expired_reschedule_window(self, api):
        """Credit-limited order driven ON_HOLD by a failed ship; the line's
        reschedule deadline (2026-08-05) has also passed by trigger time."""
        sc = setup_allocated_order(
            quantity=10, lot_qty=100, ship_date="2026-08-25", line_code="LIN-H",
            line_kw={"cancel_window_days": 30, "reschedule_window_days": 20},
            customer_kw={"credit_limit_cents": 1000})
        return sc

    def test_credit_failure_puts_order_on_hold(self, api):
        """PRD §3.6: "The fiscal gate runs at ship time: the customer's
        `open_balance_cents` plus the shipment's value — `qty` times the line's
        `unit_price_cents` — must not exceed `credit_limit_cents`. Equality is
        allowed; exceeding it rejects the ship with `ERR_CREDIT_LIMIT_EXCEEDED`
        and simultaneously moves the order from `ACKNOWLEDGED` or
        `PARTIALLY_SHIPPED` to `ON_HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/hold_state_beats_temporal_window
        """
        sc = self._setup_hold_with_expired_reschedule_window(api)
        ship_resp = api.ship_order_line(sc["order"]["id"], sc["order_line"]["id"],
                                        {"qty": 10}, WAREHOUSE)
        validate_error(ship_resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        held = get_success_data(api.get_order(sc["order"]["id"], ADMIN))
        assert held["status"] == "ON_HOLD", (
            "The failed ship simultaneously moves the order to ON_HOLD"
        )

    def test_hold_state_beats_temporal_window(self, api):
        """PRD §2.11: "State preconditions on the target resource follow, then
        business-safety checks (segregation of duties at inspection, date-code
        freshness at ship), then business constraints (uniqueness, channel
        match, exposure interval discipline, registration window overlap,
        quantity sufficiency), then temporal-window checks (cancel, reschedule,
        ship-date, NCNR, and buy-back windows)".
        PRD §3.6: "exceeding it rejects the ship with `ERR_CREDIT_LIMIT_EXCEEDED`
        and simultaneously moves the order from `ACKNOWLEDGED` or
        `PARTIALLY_SHIPPED` to `ON_HOLD`."

        Design: Difficulty/priority_pair_validation_conflict/hold_state_beats_temporal_window
        """
        sc = self._setup_hold_with_expired_reschedule_window(api)
        ship_resp = api.ship_order_line(sc["order"]["id"], sc["order_line"]["id"],
                                        {"qty": 10}, WAREHOUSE)
        validate_error(ship_resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED)
        advance_clock("2026-08-10T00:00:00Z")  # reschedule deadline 2026-08-05 passed
        order = get_success_data(api.get_order(sc["order"]["id"], ADMIN))
        assert order["status"] == "ON_HOLD"

        resp = api.reschedule_order_line(
            sc["order"]["id"], sc["order_line"]["id"],
            reschedule_payload("2026-09-01", order["version"]), SALES)
        # PRD names ERR_ORDER_ON_HOLD only for the ship endpoint; for a
        # reschedule on a held order the state-category 409 is pinned by §2.11,
        # but the exact state error id is left open (ERR_ORDER_ON_HOLD or
        # ERR_ORDER_NOT_ACKNOWLEDGED). Either way the temporal error must NOT win.
        assert resp.status_code == 409
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_ORDER_ON_HOLD, ApiErrorId.ERR_ORDER_NOT_ACKNOWLEDGED])
        after = get_order_line(sc["order_line"]["id"])
        assert after["ship_date"] == "2026-08-25", "No partial mutation"


class TestCancelShippedLineStateError:
    def test_state_beats_business_on_cancel_of_shipped_line(self, api):
        """PRD §3.3: "Cancelling one line follows the same terms group against
        the line itself, and additionally requires the order to be
        `ACKNOWLEDGED` or `PARTIALLY_SHIPPED` and the line to be `OPEN` or
        `ALLOCATED`; a line already `SHIPPED` or `CANCELLED` draws
        `ERR_LINE_NOT_OPEN_OR_ALLOCATED`."

        Design: Corner/validations/state_beats_business_on_cancel_of_shipped_line
        """
        sc = self._two_line_partially_shipped(api)
        resp = api.cancel_order_line(sc["order"]["id"], sc["line1"]["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_LINE_NOT_OPEN_OR_ALLOCATED)

        order = get_success_data(api.get_order(sc["order"]["id"], ADMIN))
        assert order["status"] == "PARTIALLY_SHIPPED", (
            "The order-level state check passes; only the line state blocks"
        )
        assert get_order_line(sc["line1"]["id"])["status"] == "SHIPPED"

    def _two_line_partially_shipped(self, api):
        line, part = setup_catalog(line_code="LIN-SS")
        customer = create_customer(name="Cust SS")
        order = create_order(
            customer["id"],
            [order_line_spec(part["id"], 10, "2026-10-01"),
             order_line_spec(part["id"], 5, "2026-11-01")])
        order = get_success_data(api.acknowledge_order(order["id"], SALES))
        lot = receive_lot(part["id"], qty_received=100)
        publish_run(create_allocation_run_for_part(part["id"])["id"])
        line1, line2 = get_order_lines(order["id"])
        ship_line(order["id"], line1["id"], 10)
        return {"line": line, "part": part, "customer": customer, "order": order,
                "lot": lot, "line1": line1, "line2": line2}
