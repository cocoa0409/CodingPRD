"""Returns: quantity boundary, credit math, lot matching, receive cascade,
and the order-close gate."""
from test_helpers import (
    TEST_USERS,
    api_client,
    first_order_line,
    get_success_data,
    make_contractor_headers,
    request_return_payload,
    setup_approved_return,
    setup_delivered_order,
    setup_invoiced_order,
    setup_paid_order,
    validate_error,
    validate_success,
    ApiErrorId,
)

MANAGER = TEST_USERS["branch_manager_headers"]
WAREHOUSE = TEST_USERS["warehouse_clerk_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
CREDIT = TEST_USERS["credit_analyst_headers"]
SALES = TEST_USERS["sales_rep_headers"]


class TestReturnQuantityBoundary:
    def test_return_of_exactly_delivered_quantity_approved(self, api):
        """PRD §3.8: "Approval first checks arithmetic honesty: the return
        quantity plus the line's already-`returned_bundles` must not exceed
        the line's `delivered_bundles`, or the return is refused with
        `ERR_RETURN_QUANTITY_EXCEEDED`."

        The line delivered 10 bundles; returning all 10 (the inclusive upper
        bound) is approved.

        Design: Difficulty/boundary_precision_check/return_at_exactly_delivered_quantity_accepted
        """
        ctx = setup_delivered_order(branch_code="BR-B2", sku="SH-B2", bps=1.0,
                                    price=2000, roof_squares=10.0,
                                    on_hand=100, lot_code="LOT-B2",
                                    company_name="Boundary Two")
        line = first_order_line(ctx["order"]["id"])
        ret = validate_success(api_client.request_return(
            ctx["order"]["id"],
            request_return_payload(line["id"], quantity_bundles=10,
                                   opened_bundles=0),
            make_contractor_headers(ctx["account"]["id"])), expected_status=201)
        approved = validate_success(api_client.approve_return(ret["id"],
                                                              MANAGER))
        assert approved["status"] == "APPROVED"

    def test_one_beyond_delivered_quantity_rejected(self, api):
        """PRD §3.8: "Approval first checks arithmetic honesty: the return
        quantity plus the line's already-`returned_bundles` must not exceed
        the line's `delivered_bundles`, or the return is refused with
        `ERR_RETURN_QUANTITY_EXCEEDED`."

        The line delivered 10; the request is for 11 — one past the boundary.

        Design: Difficulty/boundary_precision_check/return_at_exactly_delivered_quantity_accepted
        """
        ctx = setup_delivered_order(branch_code="BR-B3", sku="SH-B3", bps=1.0,
                                    price=2000, roof_squares=10.0,
                                    on_hand=100, lot_code="LOT-B3",
                                    company_name="Boundary Three")
        line = first_order_line(ctx["order"]["id"])
        ret = validate_success(api_client.request_return(
            ctx["order"]["id"],
            request_return_payload(line["id"], quantity_bundles=11,
                                   opened_bundles=0),
            make_contractor_headers(ctx["account"]["id"])), expected_status=201)
        resp = api_client.approve_return(ret["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_RETURN_QUANTITY_EXCEEDED)


class TestReturnCreditMath:
    def test_opened_bundle_credit_floors_at_zero(self, api):
        """PRD §3.8: "Opened bundles earn back fifty percent of their unit
        price, rounded half up to whole cents. The `restocking_fee_cents` is
        then 900 cents (nine dollars) per opened bundle, and the
        `credit_amount_cents` is the unopened credit plus the opened credit
        minus the restocking fee, floored at zero so a return never produces a
        negative credit."

        3 opened bundles at 1000 cents: gross 1500 minus restocking 2700
        floors to 0.

        Design: Corner/calculations/return_credit_opened_bundles_floor_at_zero
        """
        ctx = setup_approved_return(3, opened_bundles=3, roof_squares=3.0,
                                    bps=1.0, price=1000, branch_code="BR-CA4",
                                    sku="SH-CA4")
        assert ctx["return"]["restocking_fee_cents"] == 2700
        assert ctx["return"]["credit_amount_cents"] == 0

    def test_approve_over_quantity_return_rejected(self, api):
        """PRD §3.8: "Approval first checks arithmetic honesty: the return
        quantity plus the line's already-`returned_bundles` must not exceed
        the line's `delivered_bundles`, or the return is refused with
        `ERR_RETURN_QUANTITY_EXCEEDED`."

        Design: Corner/errors/error_return_quantity_exceeded
        """
        ctx = setup_delivered_order(branch_code="BR-ER3", sku="SH-ER3",
                                    bps=1.0, price=2000, roof_squares=10.0,
                                    on_hand=100, lot_code="LOT-ER3",
                                    company_name="ER3 Co")
        line = first_order_line(ctx["order"]["id"])
        ret = validate_success(api_client.request_return(
            ctx["order"]["id"],
            request_return_payload(line["id"], quantity_bundles=11,
                                   opened_bundles=0),
            make_contractor_headers(ctx["account"]["id"])), expected_status=201)
        resp = api_client.approve_return(ret["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_RETURN_QUANTITY_EXCEEDED)


class TestReturnReceive:
    def test_lot_mismatch_on_receive_rejected(self, api):
        """PRD §3.8: "The return must be `APPROVED` (otherwise
        `ERR_RETURN_NOT_APPROVED`), and the scanned `returned_lot_code` must
        equal the lot the order line's reservation was drawn from — a mismatch
        is rejected with `ERR_LOT_MISMATCH` even after approval, because
        blended lots are exactly what this rule exists to catch."

        Design: Corner/validations/lot_mismatch_on_receive_rejected
        """
        ctx = setup_approved_return(2, opened_bundles=0, roof_squares=5.0,
                                    bps=3.0, price=2000, branch_code="BR-VL5",
                                    sku="SH-VL5")
        resp = api_client.receive_return(ctx["return"]["id"], "LOT-DIFFERENT",
                                         WAREHOUSE)
        validate_error(resp, ApiErrorId.ERR_LOT_MISMATCH)

    def test_receive_re_stocks_adjusts_fulfillment_and_posts_credit(self, api):
        """PRD §3.8: "A clean receipt moves the return from `APPROVED` to the
        terminal `RECEIVED` state, sets `lot_match_verified` true, restocks
        the unopened bundles by adding the quantity minus the opened count
        back to the lot's `on_hand_bundles`, adds the full quantity to the
        line's `returned_bundles`, and marks the order's
        `fulfillment_status` `RETURN_ADJUSTED`."
        PRD §3.8: "when the order's `payment_status` is `INVOICED` or `PAID`,
        the `credit_amount_cents` is subtracted from the account's
        `open_balance_cents` (floored at zero); otherwise the credit instead
        reduces the pending delivery hold."

        15 delivered from a 100-bundle lot (on_hand 85 after dispatch), 5
        unopened returned: on_hand 90; credit 5*2000 = 10000 off the
        38500 open balance -> 28500.

        Design: Corner/cross_cutting_layers/cascade_receive_restock_and_credit_chain
        """
        ctx = setup_invoiced_order(branch_code="BR-CC3", sku="SH-CC3",
                                   roof_squares=5.0, lot_code="LOT-CC3",
                                   on_hand=100, company_name="CC3 Co")
        line = first_order_line(ctx["order"]["id"])
        ret = validate_success(api_client.request_return(
            ctx["order"]["id"],
            request_return_payload(line["id"], quantity_bundles=5,
                                   opened_bundles=0),
            make_contractor_headers(ctx["account"]["id"])), expected_status=201)
        get_success_data(api_client.approve_return(ret["id"], MANAGER))
        received = validate_success(api_client.receive_return(
            ret["id"], "LOT-CC3", WAREHOUSE))
        assert received["status"] == "RECEIVED"
        assert received["lot_match_verified"] is True

        lot = get_success_data(
            api_client.get_inventory_lot(ctx["lot"]["id"], WAREHOUSE))
        assert lot["on_hand_bundles"] == 90
        order = get_success_data(
            api_client.get_order(ctx["order"]["id"], CREDIT))
        assert order["fulfillment_status"] == "RETURN_ADJUSTED"
        account = get_success_data(
            api_client.get_contractor_account(ctx["account"]["id"], CREDIT))
        assert account["open_balance_cents"] == 28500


class TestReturnGates:
    def test_order_close_blocked_by_open_return(self, api):
        """PRD §3.4: "no return on the order may sit in `REQUESTED` or
        `APPROVED` (otherwise `ERR_OPEN_RETURNS_EXIST`)."

        The order is delivered, invoiced, and fully paid, but one return is
        still REQUESTED.

        Design: Corner/state_machines/order_close_blocked_by_open_return
        """
        ctx = setup_paid_order(branch_code="BR-SM6", sku="SH-SM6",
                               roof_squares=5.0, lot_code="LOT-SM6",
                               company_name="SM6 Co")
        line = first_order_line(ctx["order"]["id"])
        get_success_data(api_client.request_return(
            ctx["order"]["id"],
            request_return_payload(line["id"], quantity_bundles=2,
                                   opened_bundles=0),
            make_contractor_headers(ctx["account"]["id"])))
        resp = api_client.close_order(ctx["order"]["id"], SALES)
        validate_error(resp, ApiErrorId.ERR_OPEN_RETURNS_EXIST)

    def test_dispatcher_cannot_approve_return(self, api):
        """PRD §2.1: "Each endpoint admits a fixed set of roles (§4); a caller
        whose role is not admitted, or a `Contractor` attempting to act on
        another contractor's resources, is rejected with `ERR_FORBIDDEN` (HTTP
        403)."
        PRD §4: POST /roofing/returns/{id}/approve — "Approve a return,
        computing credit | BranchManager".

        Design: Corner/rbac/dispatcher_cannot_approve_returns
        """
        ctx = setup_delivered_order(branch_code="BR-RB4", sku="SH-RB4",
                                    bps=1.0, price=2000, roof_squares=5.0,
                                    lot_code="LOT-RB4", company_name="RB4 Co")
        line = first_order_line(ctx["order"]["id"])
        ret = get_success_data(api_client.request_return(
            ctx["order"]["id"],
            request_return_payload(line["id"], quantity_bundles=2,
                                   opened_bundles=0),
            make_contractor_headers(ctx["account"]["id"])))
        resp = api_client.approve_return(ret["id"], DISPATCH)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
