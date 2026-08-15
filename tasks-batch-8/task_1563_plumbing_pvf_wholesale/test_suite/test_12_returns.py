"""Returns: window, returnability, quantity gates, fees, credit, restock (PRD §3.10)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_approved_return,
    create_credited_return,
    create_order_line_payload,
    create_picked_up_order,
    create_return_payload,
    create_submitted_order,
    create_submitted_return,
    get_order_line,
    get_stock_row,
    make_account,
    make_branch,
    make_counterrep_headers,
    make_manager_headers,
    make_product,
    make_stock,
    receive_stock,
    set_clock,
    setup_branch_product_account,
    validate_error,
    validate_success,
)

REP = TEST_USERS["counterrep_headers"]
SALES = TEST_USERS["sales_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]


class TestRestockingFeeRounding:
    def _setup_three_line_return(self):
        """Picked-up will-call order with three separate PR x1 lines (333 each at
        GOLD), clock advanced 45 days (25% fee tier), return submitted."""
        branch = make_branch()
        product = make_product(sku="PR", description="Returnable fitting", category="FITTING",
                               list_price_cents=370, cost_cents=100, cubes_per_unit=1)
        account = make_account()
        make_stock(branch["id"], product["id"], 3)
        order, line_ids = create_picked_up_order(
            account["id"], branch["id"],
            [(product["id"], 1), (product["id"], 1), (product["id"], 1)],
        )
        set_clock("2026-09-15T00:00:00Z")
        ret = create_submitted_return(
            order["id"], [{"order_line_id": lid, "qty": 1} for lid in line_ids],
            submitted_by="rep-1",
        )
        return account, order, ret

    def test_fee_rounded_per_line_then_summed(self, api):
        """PRD §3.10: "Each returned line's value is its `qty` times the order
        line's `unit_price_cents` — times `cut_length_ft` as well for cut items
        — and the rounding order is pinned: each line's fee is its value
        multiplied by the applicable percent and divided by 100, rounded half up
        to a whole cent, and the per-line fees are then summed into
        `restocking_fee_cents`; summing the values first and rounding once is
        forbidden."
        PRD §3.10: "ten percent when the return was submitted within 30 days of
        fulfillment, and twenty-five percent when submitted more than 30 but no
        more than 90 days after".

        Three lines of 333 at 25%: round_half_up(83.25) = 83 per line, summed to
        249 — a sum-then-round implementation would produce 250 and must fail.

        Design: Difficulty/combinatorial_formula/restocking_fee_per_line_rounding
        """
        _, _, ret = self._setup_three_line_return()
        decided = validate_success(api.decide_return(
            ret["id"], {"decision": "APPROVE"}, make_manager_headers("mgr-9")
        ))
        assert decided["restocking_fee_cents"] == 249, (
            f"per-line rounding must give 3 x 83 = 249, got {decided['restocking_fee_cents']}"
        )

    def test_credit_is_values_minus_fee(self, api):
        """PRD §3.10: "The `credit_cents` is the sum of the line values minus
        `restocking_fee_cents`; freight is never credited."

        Line values 999 minus the 249 fee credits 750.

        Design: Difficulty/combinatorial_formula/restocking_fee_per_line_rounding
        """
        _, _, ret = self._setup_three_line_return()
        decided = validate_success(api.decide_return(
            ret["id"], {"decision": "APPROVE"}, make_manager_headers("mgr-9")
        ))
        assert decided["status"] == "APPROVED"
        assert decided["credit_cents"] == 750, (
            f"999 - 249 must credit 750, got {decided['credit_cents']}"
        )


class TestReturnSubmitGates:
    def test_return_qty_gated_by_line_fulfillment(self, api):
        """PRD §3.10: "And per line, the returned `qty` may not exceed that
        line's fulfilled-minus-returned remainder, else
        `ERR_RETURN_QTY_EXCEEDS_FULFILLED`."

        The line fulfilled 5; asking to return 6 is rejected and the return
        stays DRAFT.

        Design: Difficulty/cross_entity_state_dependency/return_qty_gated_by_line_fulfillment
        """
        branch, product, account = setup_branch_product_account(stock=5)
        order, line_ids = create_picked_up_order(account["id"], branch["id"], [(product["id"], 5)])
        ret = validate_success(api.create_return(
            create_return_payload(order["id"], [{"order_line_id": line_ids[0], "qty": 6}]),
            make_counterrep_headers("rep-1"),
        ), 201)
        res = api.submit_return(ret["id"], make_counterrep_headers("rep-1"))
        validate_error(res, ApiErrorId.ERR_RETURN_QTY_EXCEEDS_FULFILLED)
        after = validate_success(api.get_return(ret["id"], REP))
        assert after["status"] == "DRAFT"

    def test_return_qty_at_exact_remainder_submits(self, api):
        """PRD §3.10: "And per line, the returned `qty` may not exceed that
        line's fulfilled-minus-returned remainder, else
        `ERR_RETURN_QTY_EXCEEDS_FULFILLED`." Equality is not an exceedance: a
        return of exactly the fulfilled quantity (5 of 5) submits and moves to
        `SUBMITTED`.

        Design: Difficulty/cross_entity_state_dependency/return_qty_gated_by_line_fulfillment
        """
        branch, product, account = setup_branch_product_account(stock=5)
        order, line_ids = create_picked_up_order(account["id"], branch["id"], [(product["id"], 5)])
        ret = validate_success(api.create_return(
            create_return_payload(order["id"], [{"order_line_id": line_ids[0], "qty": 5}]),
            make_counterrep_headers("rep-1"),
        ), 201)
        submitted = validate_success(api.submit_return(ret["id"], make_counterrep_headers("rep-1")))
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by"] == "rep-1"

    def test_cut_item_return_rejected_non_returnable(self, api):
        """PRD §3.10: "No return line may reference a cut-to-order or
        special-order product, else `ERR_NON_RETURNABLE_ITEM`."

        Design: Corner/validations/cut_item_return_rejected_non_returnable
        """
        branch = make_branch()
        cut = make_product(sku="PC", is_cut_to_order=True, list_price_cents=200,
                           cost_cents=100, cubes_per_unit=1)
        account = make_account()
        make_stock(branch["id"], cut["id"], 20)
        order, line_ids = create_picked_up_order(
            account["id"], branch["id"], [(cut["id"], 2, {"cut_length_ft": 3})]
        )
        ret = validate_success(api.create_return(
            create_return_payload(order["id"], [{"order_line_id": line_ids[0], "qty": 1}]),
            make_counterrep_headers("rep-1"),
        ), 201)
        res = api.submit_return(ret["id"], make_counterrep_headers("rep-1"))
        validate_error(res, ApiErrorId.ERR_NON_RETURNABLE_ITEM)
        after = validate_success(api.get_return(ret["id"], REP))
        assert after["status"] == "DRAFT"

    def test_return_after_90_days_rejected(self, api):
        """PRD §3.10: "The return window is 90 days: the logical clock at
        submission may be no more than 90 days after the order's fulfillment
        timestamp, else `ERR_RETURN_WINDOW_EXPIRED`."

        The order was picked up 2026-08-01; submitting at 2026-10-31 is 91 days
        later, past the window.

        Design: Corner/validations/return_after_90_days_rejected
        """
        branch, product, account = setup_branch_product_account(stock=2)
        order, line_ids = create_picked_up_order(account["id"], branch["id"], [(product["id"], 1)])
        set_clock("2026-10-31T00:00:00Z")
        ret = validate_success(api.create_return(
            create_return_payload(order["id"], [{"order_line_id": line_ids[0], "qty": 1}]),
            make_counterrep_headers("rep-1"),
        ), 201)
        res = api.submit_return(ret["id"], make_counterrep_headers("rep-1"))
        validate_error(res, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED)

    def test_empty_return_on_unfulfilled_order_rejected(self, api):
        """PRD §3.10: "Across the referenced lines, at least one must have
        remaining returnable quantity — fulfilled minus already returned greater
        than zero — else the return is rejected with `ERR_EMPTY_RETURN`."

        The order was submitted (line ALLOCATED) but never staged, so every
        line's fulfilled count is 0.

        Design: Corner/validations/empty_return_on_unfulfilled_order_rejected
        """
        branch, product, account = setup_branch_product_account(stock=2)
        order, line_ids = create_submitted_order(account["id"], branch["id"], [(product["id"], 1)])
        ret = validate_success(api.create_return(
            create_return_payload(order["id"], [{"order_line_id": line_ids[0], "qty": 1}]),
            make_counterrep_headers("rep-1"),
        ), 201)
        res = api.submit_return(ret["id"], make_counterrep_headers("rep-1"))
        validate_error(res, ApiErrorId.ERR_EMPTY_RETURN)


class TestReturnDecisionAndReceive:
    def test_rejected_return_cannot_receive(self, api, sales_headers):
        """PRD §3.10: "A `REJECT` decision records `decided_by`, moves the return
        to terminal `REJECTED`, and touches nothing — no inventory, no balance,
        no fees." Receive is defined only for `APPROVED` returns: "A
        `WarehouseLead` receives an `APPROVED` return, moving it to terminal
        `CREDITED`".

        Receiving the REJECTED return is rejected; inventory and the account
        balance are untouched.

        Design: Corner/state_machines/rejected_return_cannot_receive
        """
        branch, product, account = setup_branch_product_account(stock=2)
        order, line_ids = create_picked_up_order(account["id"], branch["id"], [(product["id"], 2)])
        ret = create_submitted_return(order["id"], [{"order_line_id": line_ids[0], "qty": 1}],
                                      submitted_by="rep-1")
        rejected = validate_success(api.decide_return(
            ret["id"], {"decision": "REJECT"}, make_manager_headers("mgr-9")
        ))
        assert rejected["status"] == "REJECTED"

        res = api.receive_return(ret["id"], WAREHOUSE)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        row = get_stock_row(branch["id"], product["id"])
        assert row["on_hand"] == 0, "a rejected return must not restock"
        acct = validate_success(api.get_account(account["id"], sales_headers))
        assert acct["outstanding_balance_cents"] == 20500, "a rejected return must not credit"

    def test_receive_restock_fills_waiting_order(self, api, sales_headers):
        """PRD §3.10: "for each line, the stock record's `on_hand` rises by the
        returned quantity and the order line's `qty_returned` rises likewise;
        the restock triggers the backorder waterfall of §2.10 for the restocked
        products, which can flip waiting lines to `ALLOCATED` and bubble their
        orders to `PICKING`".

        Account R's credited return of 4 restocks P1, which fills account W's
        waiting line (3) and waves order W to PICKING; the stock record reads
        (4, 3, 1) and the returned line records qty_returned 4.

        Design: Difficulty/transitive_cascade/return_restock_fills_waiting_order_and_credits_account
        """
        branch, product, acct_r = setup_branch_product_account(
            account_overrides={"company_name": "R Co"}, stock=4,
        )
        acct_w = make_account(company_name="W Co", credit_limit_cents=1000000)
        order_r, line_r = create_picked_up_order(acct_r["id"], branch["id"], [(product["id"], 4)])
        order_w, line_w = create_submitted_order(
            acct_w["id"], branch["id"], [(product["id"], 3)], will_call=True
        )
        approved = create_approved_return(order_r["id"], [{"order_line_id": line_r[0], "qty": 4}],
                                          submitted_by="rep-1", decided_by="mgr-9")

        validate_success(api.receive_return(approved["id"], WAREHOUSE))

        line_w_after = get_order_line(line_w[0], order_w["id"])
        assert line_w_after["status"] == "ALLOCATED" and line_w_after["qty_allocated"] == 3, (
            "the restock — not a direct call — must fill the waiting line"
        )
        order_w_after = validate_success(api.get_order(order_w["id"], sales_headers))
        assert order_w_after["fulfillment_status"] == "PICKING"
        row = get_stock_row(branch["id"], product["id"])
        assert (row["on_hand"], row["reserved"], row["available"]) == (4, 3, 1)
        line_r_after = get_order_line(line_r[0], order_r["id"])
        assert line_r_after["qty_returned"] == 4

    def test_receive_credits_account_balance(self, api, sales_headers):
        """PRD §3.10: "the account's `outstanding_balance_cents` falls by the
        return's `credit_cents`" and "Receiving closes the loop. A
        `WarehouseLead` receives an `APPROVED` return, moving it to terminal
        `CREDITED`".

        Order R invoiced 38500; the approved return of 4 units (36000 value,
        10% fee 3600 within 30 days) credits 32400, leaving a balance of 6100.

        Design: Difficulty/transitive_cascade/return_restock_fills_waiting_order_and_credits_account
        """
        branch, product, acct_r = setup_branch_product_account(
            account_overrides={"company_name": "R Co"}, stock=4,
        )
        order_r, line_r = create_picked_up_order(acct_r["id"], branch["id"], [(product["id"], 4)])
        ret = create_credited_return(order_r["id"], [{"order_line_id": line_r[0], "qty": 4}],
                                     submitted_by="rep-1", decided_by="mgr-9")
        assert ret["status"] == "CREDITED"
        assert ret["credit_cents"] == 32400, (
            f"36000 value - 3600 fee must credit 32400, got {ret['credit_cents']}"
        )
        acct = validate_success(api.get_account(acct_r["id"], sales_headers))
        assert acct["outstanding_balance_cents"] == 6100, (
            f"38500 - 32400 must leave 6100, got {acct['outstanding_balance_cents']}"
        )


class TestJobCostingAfterReturn:
    def test_job_cost_final_nets_credited_returns(self, api, sales_headers):
        """PRD §3.3: "and `final_cost_cents`, the sum over `FILLED` lines only,
        of each line's `line_total_cents` minus its returned value (the
        `qty_returned` times the line's `unit_price_cents`, times
        `cut_length_ft` as well for cut items), netting out credited returns."
        PRD §3.3: "`provisional_cost_cents`, the sum of `line_total_cents` over
        lines in `OPEN`, `ALLOCATED`, `BACKORDERED`, or `FILLED` status, which
        includes unfulfilled commitment value and ignores pending returns".

        After a credited return of 1 unit, final drops by the gross 9000 while
        provisional still counts the full 36000.

        Design: Corner/calculations/job_cost_final_nets_credited_returns
        """
        branch, product, account = setup_branch_product_account(stock=4)
        order, line_ids = create_picked_up_order(
            account["id"], branch["id"], [(product["id"], 4)], job_name="JOB-R"
        )
        create_credited_return(order["id"], [{"order_line_id": line_ids[0], "qty": 1}],
                               submitted_by="rep-1", decided_by="mgr-9")

        report = validate_success(
            api.get_job_costing(account["id"], sales_headers, params={"job_name": "JOB-R"})
        )
        assert report["provisional_cost_cents"] == 36000, (
            f"provisional ignores returns, got {report['provisional_cost_cents']}"
        )
        assert report["final_cost_cents"] == 27000, (
            f"final nets the returned 9000 gross (fee not added back), got {report['final_cost_cents']}"
        )
        acct = validate_success(api.get_account(account["id"], sales_headers))
        assert acct["outstanding_balance_cents"] == 30400, (
            f"38500 - 8100 credit must be 30400, got {acct['outstanding_balance_cents']}"
        )
