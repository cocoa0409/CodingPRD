"""Order fulfillment and payment: the two parallel state dimensions, the
guarded join at completion, load gating on short lines, FEFO allocation, and
the conserved-units invariant across confirm/cancel."""
from test_helpers import (
    ApiErrorId,
    MGR,
    branch_version,
    create_confirmed_order,
    get_order_lines,
    invoice_order,
    make_lot,
    mark_loaded,
    order_line,
    pay_order,
    setup_branch_account_product_lot,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

COUNTER = TEST_USERS["counter_rep_headers"]
ROUTE = TEST_USERS["route_dispatcher_headers"]
WAREHOUSE = TEST_USERS["warehouse_lead_headers"]


class TestParallelDimensions:
    def test_loaded_while_uninvoiced_and_complete_blocked_until_paid(self, api):
        """PRD §3.6: "Completion requires fulfillment `PICKED_LOADED` (`ERR_ORDER_NOT_LOADED`, HTTP 409) and payment already `PAID` (`ERR_ORDER_UNPAID`, HTTP 409), and moves fulfillment to `COMPLETED`."
        PRD §3.6: "The payment dimension runs in parallel to fulfillment, independently: from `UNINVOICED`, invoicing by a `BranchManager` requires fulfillment `CONFIRMED` (`ERR_ORDER_NOT_CONFIRMED`) and payment still `UNINVOICED` (`ERR_ORDER_ALREADY_INVOICED`, HTTP 409); it freezes `invoiced_cents`, adds that amount into the account's `ytd_volume_cents`, recomputes the account's tier — which may ratchet upward but never downward — and moves payment to `INVOICED`."

        Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_x_payment
        """
        branch, account, product, _lot = setup_branch_account_product_lot(
            api,
            branch_over={"branch_code": "PHX-12", "hazmat_storage_certified": False},
            account_over={"account_number": "DLR-400"},
            product_over={"sku": "BASKET-STD", "product_family": "PARTS", "base_price_cents": 2500},
            lot_over={"qty_on_hand": 20},
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(product["id"], 2)],
        )
        # Fulfillment advances while payment stays UNINVOICED.
        loaded = mark_loaded(order["id"], api)
        assert loaded["fulfillment_status"] == "PICKED_LOADED"
        assert loaded["payment_status"] == "UNINVOICED", (
            f"dimensions are independent — loading does not invoice: {loaded}"
        )

        # The guarded join refuses completion until payment lands.
        resp = api.complete_order(order["id"], COUNTER)
        validate_error(resp, ApiErrorId.ERR_ORDER_UNPAID)
        order = validate_success(api.get_order(order["id"], MGR))
        assert order["fulfillment_status"] == "PICKED_LOADED"
        assert order["payment_status"] == "UNINVOICED"

        # Invoicing requires fulfillment CONFIRMED — already past it.
        resp = api.invoice_order(order["id"], MGR)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CONFIRMED)

    def test_payment_axis_runs_ahead_of_fulfillment_join(self, api):
        """PRD §3.6: "The payment dimension runs in parallel to fulfillment, independently: from `UNINVOICED`, invoicing by a `BranchManager` requires fulfillment `CONFIRMED` (`ERR_ORDER_NOT_CONFIRMED`) and payment still `UNINVOICED` (`ERR_ORDER_ALREADY_INVOICED`, HTTP 409); it freezes `invoiced_cents`, adds that amount into the account's `ytd_volume_cents`, recomputes the account's tier — which may ratchet upward but never downward — and moves payment to `INVOICED`."
        PRD §3.6: "Payment recording by the `Account` itself or a `BranchManager` requires payment `INVOICED` (`ERR_ORDER_NOT_INVOICED`, HTTP 409) and lands the order at `PAID`."
        PRD §3.6: "Completion requires fulfillment `PICKED_LOADED` (`ERR_ORDER_NOT_LOADED`, HTTP 409) and payment already `PAID` (`ERR_ORDER_UNPAID`, HTTP 409), and moves fulfillment to `COMPLETED`."

        Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_x_payment
        """
        branch, account, product, _lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            product_over={"sku": "BRUSH-X", "product_family": "PARTS", "base_price_cents": 1500},
            lot_over={"qty_on_hand": 10},
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(product["id"], 1)],
        )
        invoiced = invoice_order(order["id"], api)
        assert invoiced["payment_status"] == "INVOICED"
        assert invoiced["fulfillment_status"] == "CONFIRMED", (
            f"payment advanced while fulfillment held at CONFIRMED: {invoiced}"
        )
        paid = pay_order(order["id"], api)
        assert paid["payment_status"] == "PAID"
        assert paid["fulfillment_status"] == "CONFIRMED"

        loaded = mark_loaded(order["id"], api)
        assert loaded["fulfillment_status"] == "PICKED_LOADED"
        completed = validate_success(api.complete_order(order["id"], COUNTER), 200)
        assert completed["fulfillment_status"] == "COMPLETED"
        assert completed["payment_status"] == "PAID", "guarded join: COMPLETED with PAID"


class TestTransitionGates:
    def test_confirm_from_picked_loaded_returns_invalid_state(self, api):
        """PRD §3.4: "The order must be in fulfillment `DRAFT` (`ERR_ORDER_NOT_DRAFT`, HTTP 409) and its branch still `OPEN` (`ERR_BRANCH_CLOSED`, HTTP 409) before any business check runs."

        Design: Corner/state_machines/confirm_from_picked_loaded_returns_invalid_state
        """
        branch, account, product, _lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            account_over={"account_number": "DLR-3"},
            product_over={"sku": "HOSE-25", "product_family": "PARTS", "base_price_cents": 3000},
            lot_over={"qty_on_hand": 10},
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(product["id"], 1)],
        )
        mark_loaded(order["id"], api)

        resp = api.confirm_order(
            order["id"],
            {"expected_branch_version": branch_version(branch["id"], api)},
            COUNTER,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_DRAFT)
        order = validate_success(api.get_order(order["id"], MGR))
        assert order["fulfillment_status"] == "PICKED_LOADED", (
            f"failed re-confirm fires no side effects: {order}"
        )

    def test_mark_loaded_blocked_by_short_line(self, api):
        """PRD §3.6: "The order must be in fulfillment `CONFIRMED` (`ERR_ORDER_NOT_CONFIRMED`, HTTP 409), and every line must be fully allocated — any line with `backordered_qty` above zero blocks the load with `ERR_ORDER_LINES_SHORT` (HTTP 409)."

        Design: Corner/endpoints/mark_loaded_blocked_by_short_line
        """
        branch, account, product, lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            account_over={"account_number": "DLR-18"},
            product_over={
                "sku": "LIGHT-LED", "product_family": "PARTS",
                "base_price_cents": 7000, "shortage_freeze_threshold": 1000,
            },
            lot_over={"qty_on_hand": 2},
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(product["id"], 5)],
        )
        resp = api.mark_order_loaded(order["id"], WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_ORDER_LINES_SHORT)
        order = validate_success(api.get_order(order["id"], MGR))
        assert order["fulfillment_status"] == "CONFIRMED", (
            f"rejected load leaves fulfillment at CONFIRMED: {order}"
        )
        lot_after = validate_success(api.get_stock_lot(lot["id"], WAREHOUSE))
        assert lot_after["qty_on_hand"] == 2, (
            f"no shipment happened — on-hand unchanged: {lot_after}"
        )


class TestFefoAllocation:
    def test_fefo_allocation_prefers_earliest_expiry(self, api):
        """PRD §3.4: "Each line is FEFO-allocated: among the branch's lots of the line's product holding enough unreserved units to cover the full line quantity, the system picks the earliest `expiry_date` ascending with expiring lots ranked ahead of non-expiring ones and `created_at` ascending as the tie-break, records it as the line's `allocated_lot_id`, reserves the units as `allocated_qty`, and increments the lot's `qty_reserved_willcall` or `qty_reserved_route` bucket according to channel."

        Design: Corner/calculations/fefo_allocation_prefers_earliest_expiry
        """
        branch, account, product, lot_late = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": True},
            account_over={"account_number": "DLR-7"},
            product_over={
                "sku": "ALG-40", "product_family": "CHEMICAL",
                "base_price_cents": 3500, "expiry_tracked": True,
            },
            lot_over={"lot_code": "L-LATE", "qty_on_hand": 10, "expiry_date": "2026-12-01"},
        )
        # Created second but expires first — FEFO must pick it.
        lot_early = make_lot(
            api, branch_id=branch["id"], product_id=product["id"],
            lot_code="L-EARLY", qty_on_hand=10, expiry_date="2026-09-01",
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(product["id"], 4)],
        )
        lines = get_order_lines(order["id"], api)
        assert lines[0]["allocated_lot_id"] == lot_early["id"], (
            f"earliest expiry wins despite later creation: {lines[0]}"
        )
        assert lines[0]["allocated_qty"] == 4
        early = validate_success(api.get_stock_lot(lot_early["id"], WAREHOUSE))
        late = validate_success(api.get_stock_lot(lot_late["id"], WAREHOUSE))
        assert early["qty_reserved_willcall"] == 4
        assert late["qty_reserved_willcall"] == 0, (
            f"no reservation lands on the later-expiry lot: {late}"
        )


class TestLotUnitConservation:
    def test_lot_units_conserved_across_confirm_cancel(self, api):
        """PRD §3.6: "The compensating act releases every line's lot reservation by its `allocated_qty`, cancels the order's `OPEN` backorder requests, and recomputes branch posture, which may drop the branch out of `FROZEN` into `CONSTRAINED` or `NORMAL`."
        PRD §3.1: "Availability is a three-bucket ledger: `qty_reserved_willcall` counts units held for confirmed counter orders not yet picked up or released, `qty_reserved_route` counts units held for confirmed truck orders not yet shipped or released, and `qty_available` is what remains of `qty_on_hand` after both reservation buckets — it may never go negative."

        Design: Difficulty/compensating_invariant/lot_units_conserved_across_confirm_cancel
        """
        branch, account, product, lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            account_over={"account_number": "DLR-1000"},
            product_over={"sku": "VAC-HEAD", "product_family": "PARTS", "base_price_cents": 6000},
            lot_over={"qty_on_hand": 50},
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            lines=[order_line(product["id"], 8)],
        )
        mid = validate_success(api.get_stock_lot(lot["id"], WAREHOUSE))
        assert mid["qty_reserved_willcall"] == 8
        assert mid["qty_available"] == 42, f"50 on hand minus 8 reserved: {mid}"

        validate_success(api.cancel_order(order["id"], MGR), 200)
        end = validate_success(api.get_stock_lot(lot["id"], WAREHOUSE))
        assert end["qty_available"] == 50, (
            f"cancel must restore availability exactly — no reservation drift: {end}"
        )
        assert end["qty_reserved_willcall"] == 0

    def test_lot_units_conserved_across_confirm_cancel_route_channel(self, api):
        """PRD §3.4: "Each line is FEFO-allocated: among the branch's lots of the line's product holding enough unreserved units to cover the full line quantity, the system picks the earliest `expiry_date` ascending with expiring lots ranked ahead of non-expiring ones and `created_at` ascending as the tie-break, records it as the line's `allocated_lot_id`, reserves the units as `allocated_qty`, and increments the lot's `qty_reserved_willcall` or `qty_reserved_route` bucket according to channel."
        PRD §3.6: "The compensating act releases every line's lot reservation by its `allocated_qty`, cancels the order's `OPEN` backorder requests, and recomputes branch posture, which may drop the branch out of `FROZEN` into `CONSTRAINED` or `NORMAL`."

        Design: Difficulty/compensating_invariant/lot_units_conserved_across_confirm_cancel
        """
        branch, account, product, lot = setup_branch_account_product_lot(
            api,
            branch_over={"hazmat_storage_certified": False},
            product_over={"sku": "NET-PRO", "product_family": "PARTS", "base_price_cents": 2200},
            lot_over={"qty_on_hand": 40},
        )
        order = create_confirmed_order(
            api, branch_id=branch["id"], account_id=account["id"],
            channel="ROUTE_DELIVERY", route_date="2026-08-10",
            lines=[order_line(product["id"], 6)],
        )
        mid = validate_success(api.get_stock_lot(lot["id"], WAREHOUSE))
        assert mid["qty_reserved_route"] == 6, (
            f"route orders reserve into the route bucket: {mid}"
        )
        assert mid["qty_reserved_willcall"] == 0
        assert mid["qty_available"] == 34

        validate_success(api.cancel_order(order["id"], MGR), 200)
        end = validate_success(api.get_stock_lot(lot["id"], WAREHOUSE))
        assert end["qty_available"] == 40
        assert end["qty_reserved_route"] == 0, "route bucket fully released on cancel"
