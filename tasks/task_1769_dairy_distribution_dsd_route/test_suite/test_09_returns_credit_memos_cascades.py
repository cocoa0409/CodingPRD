"""Returns lifecycle (eligibility windows, dispute cycle, credit bases),
credit-memo gates and compensation, and the QA breach cascade
(PRD §3.4, §3.5, §3.6)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_reading,
    approve_return,
    complete_trip_at,
    confirm_order,
    create_driver,
    create_order,
    create_pricing_period,
    create_product,
    create_return,
    create_route,
    create_store,
    create_trip,
    deliver_order,
    delivered_line,
    get_invoice_for_order,
    get_store,
    make_distributor_owner_headers,
    make_driver_headers,
    make_store_receiver_headers,
    order_line,
    pay_invoice,
    precool_and_depart,
    publish_announcement,
    run_trip_readings,
    set_clock,
    setup_delivered_order,
    setup_planned_order,
    setup_route_with_store,
    setup_two_delivery_scenario,
    validate_error,
    validate_paginated,
    validate_success,
    create_distributor,
    activate_route,
)

TM = TEST_USERS["territory_manager_headers"]
QI = TEST_USERS["quality_inspector_headers"]

REGULATED = {
    "regulated": True,
    "weight_lbs_per_unit": 8.6,
    "margin_cents_per_unit": 30,
    "units_per_case": 1,
    "shelf_life_days": 14,
}


class TestReturnDisputeCycle:
    def _setup_under_review_return(self, api, prefix):
        refs = setup_delivered_order(prefix=prefix, quantity_units=10)
        ret = create_return(
            refs["order"]["id"], refs["store"]["id"], refs["trip"]["id"],
            refs["product"]["id"], 2, "DAMAGED", "2026-09-01",
            refs["driver"]["id"],
        )
        assert ret["status"] == "UNDER_REVIEW"
        assert ret["credit_amount_cents"] == 250, "round(2 x 250 x 0.5)"
        return refs, ret

    def test_reject_dispute_cycle_twice_then_approve_credits(self, api):
        """PRD §3.6: "Rejection, likewise from `UNDER_REVIEW` or `DISPUTED`
        (else `ERR_RETURN_NOT_REVIEWABLE`), moves the return to `REJECTED` and
        creates no credit memo."
        PRD §3.6: "The store's receiver — whose `X-User-ID` must equal the
        return's `store_id`, else `ERR_OWNERSHIP_MISMATCH` — may dispute a
        `REJECTED` return (from any other state, `ERR_RETURN_NOT_DISPUTABLE`),
        cycling it back to `DISPUTED` and into review again."
        PRD §3.6: "Approval is defined from `UNDER_REVIEW` or `DISPUTED` (any
        other state, `ERR_RETURN_NOT_REVIEWABLE`) and runs two steps
        atomically: the return moves to `APPROVED` and then, immediately and
        by system action, to `CREDITED`."

        Design: Difficulty/non_linear_state_machine/return_dispute_cycle_rejected_disputed_rereview
        """
        refs, ret = self._setup_under_review_return(api, "G")
        d_id = refs["distributor"]["id"]
        owner = make_distributor_owner_headers(d_id)
        receiver = make_store_receiver_headers(refs["store"]["id"])

        for _ in range(2):
            validate_success(api.reject_return(ret["id"], owner), 200)
            disputed = validate_success(api.dispute_return(ret["id"], receiver), 200)
            assert disputed["status"] == "DISPUTED"

        final = validate_success(api.approve_return(ret["id"], owner), 200)
        assert final["status"] == "CREDITED", "APPROVED transitions to CREDITED immediately"

        memos, _ = validate_paginated(
            api.list_credit_memos(TM, params={"store_id": refs["store"]["id"]})
        )
        assert len(memos) == 1, "only the terminal approval mints the memo"
        assert memos[0]["amount_cents"] == 250
        assert memos[0]["status"] == "APPLIED"

        invoice = validate_success(api.get_invoice(refs["invoice"]["id"], TM), 200)
        assert invoice["amount_due_cents"] == 2250, "2500 - 250 auto-applied"

    def test_rejection_creates_no_memo_and_credited_is_terminal(self, api):
        """PRD §3.6: "Rejection, likewise from `UNDER_REVIEW` or `DISPUTED`
        (else `ERR_RETURN_NOT_REVIEWABLE`), moves the return to `REJECTED` and
        creates no credit memo."
        PRD §3.6: "The store's receiver — whose `X-User-ID` must equal the
        return's `store_id`, else `ERR_OWNERSHIP_MISMATCH` — may dispute a
        `REJECTED` return (from any other state, `ERR_RETURN_NOT_DISPUTABLE`),
        cycling it back to `DISPUTED` and into review again."

        Design: Difficulty/non_linear_state_machine/return_dispute_cycle_rejected_disputed_rereview
        """
        refs, ret = self._setup_under_review_return(api, "G2")
        d_id = refs["distributor"]["id"]
        owner = make_distributor_owner_headers(d_id)
        receiver = make_store_receiver_headers(refs["store"]["id"])

        validate_success(api.reject_return(ret["id"], owner), 200)
        memos, _ = validate_paginated(
            api.list_credit_memos(TM, params={"store_id": refs["store"]["id"]})
        )
        assert memos == [], "rejection creates no credit memo"

        validate_success(api.dispute_return(ret["id"], receiver), 200)
        validate_success(api.approve_return(ret["id"], owner), 200)
        err = api.dispute_return(ret["id"], receiver)
        validate_error(err, ApiErrorId.ERR_RETURN_NOT_DISPUTABLE)


class TestPullWindowInclusiveBoundary:
    def _setup_delivered_two_products(self, api, prefix):
        refs = setup_route_with_store(prefix=prefix, store_overrides={"pull_window_days": 4})
        d_id = refs["distributor"]["id"]
        pa = create_product(f"YOG-{prefix}-A", list_price_cents=250, shelf_life_days=21)
        pb = create_product(f"YOG-{prefix}-B", list_price_cents=250, shelf_life_days=21)
        driver = create_driver(d_id, name=f"Driver {prefix}")
        trip = create_trip(refs["route"]["id"], driver["id"], d_id, service_date="2026-08-10")
        order = create_order(
            refs["store"]["id"], trip["id"],
            [order_line(pa["id"], 10), order_line(pb["id"], 10)],
            d_id,
            delivery_window_start="2026-08-10T08:00:00Z",
            delivery_window_end="2026-08-10T08:30:00Z",
        )
        confirm_order(order["id"], d_id)
        precool_and_depart(trip["id"], driver["id"], "2026-08-10")
        set_clock("2026-08-10T09:00:00Z")
        deliver_order(
            order["id"], driver["id"],
            [delivered_line(pa["id"], 10, "2026-08-25"),
             delivered_line(pb["id"], 10, "2026-08-25")],
        )
        refs.update({"pa": pa, "pb": pb, "driver": driver, "trip": trip,
                     "order": order})
        return refs

    def test_scan_at_exactly_pull_window_is_eligible(self, api):
        """PRD §3.6: "a `PULL_POLICY` return requires it to lie within the
        store's pull window — at least zero and at most `pull_window_days`,
        both bounds inclusive"
        PRD §3.6: "The `credit_pct` follows the reason: `OUT_OF_CODE` credits
        in full at 1.0, `PULL_POLICY` in full at 1.0, `DAMAGED` at half, 0.5,
        and `COLD_CHAIN` in full at 1.0."

        Design: Difficulty/boundary_precision_check/pull_window_inclusive_boundary
        """
        refs = self._setup_delivered_two_products(api, "M")
        ret = create_return(
            refs["order"]["id"], refs["store"]["id"], refs["trip"]["id"],
            refs["pa"]["id"], 1, "PULL_POLICY", "2026-08-14",
            refs["driver"]["id"],
        )
        assert ret["days_to_expiry_at_scan"] == 4, (
            "scan 2026-08-10 vs code 2026-08-14 equals pull_window_days"
        )
        assert ret["status"] == "UNDER_REVIEW"
        assert ret["credit_pct"] == pytest.approx(1.0)
        assert ret["credit_amount_cents"] == 250

    def test_scan_one_day_beyond_pull_window_rejected_and_zero_allowed(self, api):
        """PRD §3.6: "a `PULL_POLICY` return requires it to lie within the
        store's pull window — at least zero and at most `pull_window_days`,
        both bounds inclusive; a `DAMAGED` return accepts any value; and
        `COLD_CHAIN` is system-created only — a manual attempt names it and is
        rejected with `ERR_RETURN_NOT_ELIGIBLE` (HTTP 422), as is any
        eligibility window miss."

        Design: Difficulty/boundary_precision_check/pull_window_inclusive_boundary
        """
        refs = self._setup_delivered_two_products(api, "M2")
        err = api.create_return(
            {
                "order_id": refs["order"]["id"], "store_id": refs["store"]["id"],
                "pickup_trip_id": refs["trip"]["id"], "product_id": refs["pb"]["id"],
                "quantity_units": 1, "reason_code": "PULL_POLICY",
                "scanned_code_date": "2026-08-15",
            },
            make_driver_headers(refs["driver"]["id"]),
        )
        validate_error(err, ApiErrorId.ERR_RETURN_NOT_ELIGIBLE)

        ok = create_return(
            refs["order"]["id"], refs["store"]["id"], refs["trip"]["id"],
            refs["pb"]["id"], 1, "PULL_POLICY", "2026-08-10",
            refs["driver"]["id"],
        )
        assert ok["days_to_expiry_at_scan"] == 0, "lower bound is inclusive"
        assert ok["status"] == "UNDER_REVIEW"


class TestReturnCreditOriginalVsCurrentBasis:
    def _setup_two_basis_routes(self, api):
        """One distributor with route A (ORIGINAL) and route B (CURRENT); both
        stores take a 10-unit regulated delivery on 2026-07-15 priced off the
        July provisional (unit 210.170c); the clock then moves to 2026-08-05
        and the August provisional (unit 218.770c) is published."""
        set_clock("2026-07-01T00:00:00Z")
        distributor = create_distributor(name="Dairy Dist B", license_number="LIC-B-1")
        d_id = distributor["id"]
        ra = create_route(d_id, route_code="R-A", credit_price_basis="ORIGINAL",
                          service_weekdays=["WED"])
        rb = create_route(d_id, route_code="R-B", credit_price_basis="CURRENT",
                          service_weekdays=["WED"])
        sa = create_store(ra["id"], d_id, store_code="S-A")
        sb = create_store(rb["id"], d_id, store_code="S-B")
        activate_route(ra["id"])
        activate_route(rb["id"])
        product = create_product("MILK-GAL-2", **dict(REGULATED))
        driver = create_driver(d_id, name="Dee Driver")
        per7 = create_pricing_period("2026-07")
        publish_announcement(per7["id"], kind="PROVISIONAL", base=2000,
                             assessment=35, hauling=60, diesel=299)
        ta = create_trip(ra["id"], driver["id"], d_id, service_date="2026-07-15",
                         planned_depart_at="2026-07-15T05:00:00Z",
                         planned_return_at="2026-07-15T08:00:00Z")
        tb = create_trip(rb["id"], driver["id"], d_id, service_date="2026-07-15",
                         planned_depart_at="2026-07-15T09:00:00Z",
                         planned_return_at="2026-07-15T12:00:00Z")
        oa = create_order(sa["id"], ta["id"], [order_line(product["id"], 10)], d_id,
                          delivery_window_start="2026-07-15T06:00:00Z",
                          delivery_window_end="2026-07-15T06:30:00Z")
        ob = create_order(sb["id"], tb["id"], [order_line(product["id"], 10)], d_id,
                          delivery_window_start="2026-07-15T10:00:00Z",
                          delivery_window_end="2026-07-15T10:30:00Z")
        confirm_order(oa["id"], d_id)
        confirm_order(ob["id"], d_id)
        precool_and_depart(ta["id"], driver["id"], "2026-07-15")
        precool_and_depart(tb["id"], driver["id"], "2026-07-15")
        set_clock("2026-07-15T06:15:00Z")
        deliver_order(oa["id"], driver["id"],
                      [delivered_line(product["id"], 10, "2026-07-25")])
        set_clock("2026-07-15T10:15:00Z")
        deliver_order(ob["id"], driver["id"],
                      [delivered_line(product["id"], 10, "2026-07-25")])
        set_clock("2026-08-05T00:00:00Z")
        per8 = create_pricing_period("2026-08")
        publish_announcement(per8["id"], kind="PROVISIONAL", base=2100,
                             assessment=35, hauling=60, diesel=299)
        return {
            "distributor": distributor, "ra": ra, "rb": rb, "sa": sa, "sb": sb,
            "product": product, "driver": driver, "ta": ta, "tb": tb,
            "oa": oa, "ob": ob,
        }

    def test_original_basis_credits_price_paid_at_delivery(self, api):
        """PRD §3.6: "under `ORIGINAL`, the credit is priced at the delivered
        line's snapshotted `unit_price_cents` — what the store actually paid"
        PRD §3.6: "the return's `days_to_expiry_at_scan` is the
        `scanned_code_date` minus the current clock date in days — negative
        means out of code."

        Design: Difficulty/dual_variant_calc/return_credit_original_vs_current_basis
        """
        refs = self._setup_two_basis_routes(api)
        ret = create_return(
            refs["oa"]["id"], refs["sa"]["id"], refs["ta"]["id"],
            refs["product"]["id"], 10, "OUT_OF_CODE", "2026-07-25",
            refs["driver"]["id"],
        )
        assert ret["days_to_expiry_at_scan"] == -11
        assert ret["credit_pct"] == pytest.approx(1.0)
        assert ret["unit_credit_cents"] == pytest.approx(210.170, abs=0.001)
        assert ret["credit_amount_cents"] == 2102, "10 x 210.170 (July price)"

    def test_current_basis_credits_price_at_scan_month(self, api):
        """PRD §3.6: "under `CURRENT`, it is priced as of the scan date — for
        a regulated product, the announcement of the scan month applied
        through the same regulated price formula; for a non-regulated product,
        its `list_price_cents`. The two bases diverge whenever the price moved
        between delivery and scan."

        Design: Difficulty/dual_variant_calc/return_credit_original_vs_current_basis
        """
        refs = self._setup_two_basis_routes(api)
        ret = create_return(
            refs["ob"]["id"], refs["sb"]["id"], refs["tb"]["id"],
            refs["product"]["id"], 10, "OUT_OF_CODE", "2026-07-25",
            refs["driver"]["id"],
        )
        assert ret["unit_credit_cents"] == pytest.approx(218.770, abs=0.001)
        assert ret["credit_amount_cents"] == 2188, "10 x 218.770 (August price)"
        assert ret["credit_amount_cents"] - 2102 == 86


def test_return_referential_gates(api):
    """PRD §3.6: "The order must be `DELIVERED`; the named product must appear
    among the order's delivered lines, and cumulative returned units for that
    product may not exceed what was delivered — violations are
    `ERR_RETURN_PRODUCT_NOT_DELIVERED` (HTTP 422). The caller-supplied store
    context must match the order's store, else `ERR_RETURN_STORE_MISMATCH`
    (HTTP 422)."
    PRD §3.6: "An `OUT_OF_CODE` return requires `days_to_expiry_at_scan` below
    zero"

    Design: Corner/validations/return_referential_gates
    """
    refs = setup_delivered_order(prefix="CE", quantity_units=4, code_date="2026-08-25")
    store2 = create_store(refs["route"]["id"], refs["distributor"]["id"],
                          store_code="S-CE-2")
    other_product = create_product("REF-2", list_price_cents=250, shelf_life_days=30)
    driver_h = make_driver_headers(refs["driver"]["id"])

    base = {
        "order_id": refs["order"]["id"],
        "pickup_trip_id": refs["trip"]["id"],
        "quantity_units": 1,
        "scanned_code_date": "2026-08-25",
    }
    err1 = api.create_return(
        {**base, "store_id": refs["store"]["id"],
         "product_id": other_product["id"], "reason_code": "DAMAGED"},
        driver_h,
    )
    validate_error(err1, ApiErrorId.ERR_RETURN_PRODUCT_NOT_DELIVERED)

    err2 = api.create_return(
        {**base, "store_id": store2["id"],
         "product_id": refs["product"]["id"], "reason_code": "DAMAGED"},
        driver_h,
    )
    validate_error(err2, ApiErrorId.ERR_RETURN_STORE_MISMATCH)

    err3 = api.create_return(
        {**base, "store_id": refs["store"]["id"],
         "product_id": refs["product"]["id"], "reason_code": "OUT_OF_CODE"},
        driver_h,
    )
    validate_error(err3, ApiErrorId.ERR_RETURN_NOT_ELIGIBLE)


def test_memo_state_gates(api):
    """PRD §3.6: "the memo must be `ISSUED` or `PARTIALLY_APPLIED` (else
    `ERR_CREDIT_MEMO_NOT_APPLICABLE`), and the target invoice must exist,
    belong to the memo's store, and be `OPEN` (else `ERR_INVOICE_NOT_OPEN`)."
    PRD §3.6: "A `TerritoryManager` may void a memo in `ISSUED` or
    `PARTIALLY_APPLIED` (else `ERR_CREDIT_MEMO_NOT_VOIDABLE`)"
    PRD §3.6: "the target is the return's own order invoice if that invoice is
    still `OPEN`, otherwise the store's oldest `OPEN` invoice by `created_at`
    ascending"

    Design: Corner/state_machines/memo_state_gates
    """
    refs = setup_delivered_order(prefix="AK", quantity_units=4)
    d_id = refs["distributor"]["id"]
    s1 = refs["store"]["id"]
    inv1 = refs["invoice"]
    re1 = create_return(refs["order"]["id"], s1, refs["trip"]["id"],
                        refs["product"]["id"], 2, "DAMAGED", "2026-09-01",
                        refs["driver"]["id"])
    approve_return(re1["id"], d_id)
    memos, _ = validate_paginated(api.list_credit_memos(TM, params={"store_id": s1}))
    m1 = memos[0]
    assert m1["status"] == "APPLIED"
    pay_invoice(inv1["id"], s1, 750)

    # Second delivery on a second trip; its invoice is voided pristine.
    trip2 = create_trip(refs["route"]["id"], refs["driver"]["id"], d_id,
                        service_date="2026-08-11")
    order2 = create_order(s1, trip2["id"], [order_line(refs["product"]["id"], 4)], d_id,
                          delivery_window_start="2026-08-11T08:00:00Z",
                          delivery_window_end="2026-08-11T08:30:00Z")
    confirm_order(order2["id"], d_id)
    precool_and_depart(trip2["id"], refs["driver"]["id"], "2026-08-11")
    set_clock("2026-08-11T09:00:00Z")
    deliver_order(order2["id"], refs["driver"]["id"],
                  [delivered_line(refs["product"]["id"], 4, "2026-09-01")])
    inv2 = get_invoice_for_order(order2["id"])
    validate_success(api.void_invoice(inv2["id"], TM), 200)

    re2 = create_return(order2["id"], s1, trip2["id"], refs["product"]["id"],
                        2, "DAMAGED", "2026-09-01", refs["driver"]["id"])
    approve_return(re2["id"], d_id)
    memos2, _ = validate_paginated(api.list_credit_memos(TM, params={"return_id": re2["id"]}))
    m2 = memos2[0]
    assert m2["status"] == "ISSUED"
    assert m2["invoice_id"] is None, (
        "no OPEN invoice at approval: own order's invoice was VOID"
    )

    owner = make_distributor_owner_headers(d_id)
    err1 = api.void_credit_memo(m1["id"], TM)
    validate_error(err1, ApiErrorId.ERR_CREDIT_MEMO_NOT_VOIDABLE)

    err2 = api.apply_credit_memo(m1["id"], {"invoice_id": inv1["id"]}, owner)
    validate_error(err2, ApiErrorId.ERR_CREDIT_MEMO_NOT_APPLICABLE)

    err3 = api.apply_credit_memo(m2["id"], {"invoice_id": inv1["id"]}, owner)
    validate_error(err3, ApiErrorId.ERR_INVOICE_NOT_OPEN)

    voided = validate_success(api.void_credit_memo(m2["id"], TM), 200)
    assert voided["status"] == "VOID"

    err4 = api.apply_credit_memo(m2["id"], {"invoice_id": inv2["id"]}, owner)
    validate_error(err4, ApiErrorId.ERR_CREDIT_MEMO_NOT_APPLICABLE)


class TestCreditApplyVoidRestoresInvoice:
    def _setup_partially_applied_memo(self, api, prefix, with_third_invoice=False):
        """INV_A (10 regulated units @ 218.770 = 2188) paid off; INV_B (500)
        open. A 4-unit OUT_OF_CODE return on INV_A's order credits 875; on
        approval it auto-applies 500 to INV_B (the oldest OPEN invoice),
        settling it and leaving the memo PARTIALLY_APPLIED with 375."""
        refs = setup_two_delivery_scenario(
            prefix=prefix, first_units=10, second_units=2,
            product_overrides=dict(REGULATED),
            announcement={"base": 2100, "assessment": 35, "hauling": 60,
                          "diesel": 299},
        )
        d_id = refs["distributor"]["id"]
        s1 = refs["store"]["id"]
        assert refs["invoice"]["total_cents"] == 2188
        assert refs["invoice_b"]["total_cents"] == 500
        pay_invoice(refs["invoice"]["id"], s1, 2188)

        if with_third_invoice:
            trip_c = create_trip(refs["route"]["id"], refs["driver"]["id"], d_id,
                                 service_date="2026-08-11")
            order_c = create_order(s1, trip_c["id"],
                                   [order_line(refs["product_b"]["id"], 1)], d_id,
                                   delivery_window_start="2026-08-11T08:00:00Z",
                                   delivery_window_end="2026-08-11T08:30:00Z")
            confirm_order(order_c["id"], d_id)
            precool_and_depart(trip_c["id"], refs["driver"]["id"], "2026-08-11")
            set_clock("2026-08-11T09:00:00Z")
            deliver_order(order_c["id"], refs["driver"]["id"],
                          [delivered_line(refs["product_b"]["id"], 1, "2026-09-01")])
            refs["invoice_c"] = get_invoice_for_order(order_c["id"])

        set_clock("2026-08-30T00:00:00Z")
        ret = create_return(refs["order"]["id"], s1, refs["trip"]["id"],
                            refs["product"]["id"], 4, "OUT_OF_CODE", "2026-08-25",
                            refs["driver"]["id"])
        approve_return(ret["id"], d_id)
        memos, _ = validate_paginated(
            api.list_credit_memos(TM, params={"store_id": s1})
        )
        memo = memos[0]
        assert memo["amount_cents"] == 875, "round(4 x 218.770 x 1.0)"
        assert memo["applied_cents"] == 500
        assert memo["status"] == "PARTIALLY_APPLIED"
        inv_b = validate_success(api.get_invoice(refs["invoice_b"]["id"], TM), 200)
        assert inv_b["amount_due_cents"] == 0 and inv_b["status"] == "SETTLED"
        refs["memo"] = memo
        return refs

    def test_void_restores_settled_invoice_to_open(self, api):
        """PRD §3.6: "voiding compensates every application the memo ever made
        — each affected invoice's `credits_applied_cents` is reduced by the
        amount that memo had applied to it and its `amount_due_cents`
        increased accordingly, a `SETTLED` invoice reopens to `OPEN`, affected
        orders' `payment_status` re-derive, the memo becomes `VOID`, and the
        store's `open_ar_cents` recomputes."

        Design: Difficulty/compensating_invariant/credit_apply_void_restores_invoice
        """
        refs = self._setup_partially_applied_memo(api, "S")
        memo = refs["memo"]
        voided = validate_success(api.void_credit_memo(memo["id"], TM), 200)
        assert voided["status"] == "VOID"

        inv_b = validate_success(api.get_invoice(refs["invoice_b"]["id"], TM), 200)
        assert inv_b["amount_due_cents"] == 500, "apply-then-void leaves due unchanged"
        assert inv_b["status"] == "OPEN"
        assert inv_b["credits_applied_cents"] == 0

    def test_void_compensates_every_application_across_invoices(self, api):
        """PRD §3.6: "The applied amount is the smaller of the memo's
        `remaining_cents` and the invoice's `amount_due_cents`; the memo's
        `applied_cents` grows by it and its `invoice_id` is set"
        PRD §3.6: "voiding compensates every application the memo ever made —
        each affected invoice's `credits_applied_cents` is reduced by the
        amount that memo had applied to it and its `amount_due_cents`
        increased accordingly, a `SETTLED` invoice reopens to `OPEN`"

        Design: Difficulty/compensating_invariant/credit_apply_void_restores_invoice
        """
        refs = self._setup_partially_applied_memo(api, "S2", with_third_invoice=True)
        d_id = refs["distributor"]["id"]
        owner = make_distributor_owner_headers(d_id)
        memo = refs["memo"]
        inv_c = refs["invoice_c"]

        applied = validate_success(
            api.apply_credit_memo(memo["id"], {"invoice_id": inv_c["id"]}, owner), 200
        )
        assert applied["applied_cents"] == 750, "500 + min(375, 250)"
        assert applied["remaining_cents"] == 125
        assert applied["status"] == "PARTIALLY_APPLIED"
        inv_c_mid = validate_success(api.get_invoice(inv_c["id"], TM), 200)
        assert inv_c_mid["status"] == "SETTLED" and inv_c_mid["amount_due_cents"] == 0

        voided = validate_success(api.void_credit_memo(memo["id"], TM), 200)
        assert voided["status"] == "VOID"
        inv_b = validate_success(api.get_invoice(refs["invoice_b"]["id"], TM), 200)
        assert inv_b["status"] == "OPEN" and inv_b["amount_due_cents"] == 500
        inv_c_after = validate_success(api.get_invoice(inv_c["id"], TM), 200)
        assert inv_c_after["status"] == "OPEN" and inv_c_after["amount_due_cents"] == 250
        assert inv_c_after["credits_applied_cents"] == 0


class TestQaBreachCascadeFiveDeep:
    def _setup_breached_trip_in_qa(self, api, prefix):
        """Regulated 5-unit delivery (invoice 1094 OPEN); BOX readings 10:00
        41.0F -> 11:00 39.0F accrue 60.0 excursion minutes; trip COMPLETED
        with breach, parked in QA_REVIEW."""
        refs = setup_planned_order(
            prefix=prefix, quantity_units=5, product_overrides=dict(REGULATED),
        )
        d_id = refs["distributor"]["id"]
        period = create_pricing_period("2026-08")
        publish_announcement(period["id"], kind="PROVISIONAL", base=2100,
                             assessment=35, hauling=60, diesel=299)
        confirm_order(refs["order"]["id"], d_id)
        t1 = refs["trip"]["id"]
        dr1 = refs["driver"]["id"]
        precool_and_depart(t1, dr1, "2026-08-10")
        run_trip_readings(t1, dr1, [
            ("2026-08-10T10:00:00Z", 410, "BOX"),
            ("2026-08-10T11:00:00Z", 390, "BOX"),
        ])
        set_clock("2026-08-10T11:30:00Z")
        deliver_order(refs["order"]["id"], dr1,
                      [delivered_line(refs["product"]["id"], 5, "2026-08-20")])
        refs["invoice"] = get_invoice_for_order(refs["order"]["id"])
        trip = complete_trip_at(t1, dr1, "2026-08-10T12:00:00Z")
        assert trip["excursion_minutes"] == pytest.approx(60.0, abs=0.001)
        assert trip["cold_chain_breach"] is True
        qa = validate_success(api.qa_review_trip(t1, QI), 200)
        assert qa["status"] == "QA_REVIEW"
        return refs

    def test_confirm_breach_fires_five_level_cascade(self, api):
        """PRD §3.4: "A `CONFIRM_BREACH` verdict moves the trip to
        `BREACH_CONFIRMED` and fires a five-level cascade. First, every order
        on the trip with `fulfillment_status` `DELIVERED` has every line's
        `cold_chain_flag` set to true. Second, for each flagged order line,
        the system creates a `Return` with `reason_code` `COLD_CHAIN`,
        `quantity_units` equal to the line's `delivered_units`, the line's
        `scanned_code_date`, a `credit_pct` of 1.0, and `status` immediately
        `APPROVED`. Third, each such approved return creates a `CreditMemo`
        for its `credit_amount_cents` in `ISSUED` status. Fourth, each memo
        auto-applies to its own order's invoice — still `OPEN` by construction
        — increasing the invoice's `credits_applied_cents` by the memo amount,
        recomputing `amount_due_cents`, settling the invoice if the due
        reaches exactly zero, and moving the memo to `PARTIALLY_APPLIED` or
        `APPLIED` as its remaining balance dictates. Fifth, each affected
        order's `payment_status` is re-derived from its invoice, moving
        `INVOICED` → `PARTIALLY_PAID` or `PAID`."

        Design: Difficulty/transitive_cascade/qa_breach_cascade_five_deep
        """
        refs = self._setup_breached_trip_in_qa(api, "H")
        t1 = refs["trip"]["id"]

        trip = validate_success(
            api.adjudicate_trip(t1, {"verdict": "CONFIRM_BREACH"}, QI), 200
        )
        assert trip["status"] == "BREACH_CONFIRMED"

        order = validate_success(api.get_order(refs["order"]["id"], TM), 200)
        assert all(line["cold_chain_flag"] is True for line in order["lines"])

        returns, _ = validate_paginated(api.list_returns(TM, params={"order_id": order["id"]}))
        assert len(returns) == 1
        ret = returns[0]
        assert ret["reason_code"] == "COLD_CHAIN"
        assert ret["status"] == "CREDITED"
        assert ret["quantity_units"] == 5
        assert ret["credit_amount_cents"] == 1094, "round(5 x 218.770)"

        memos, _ = validate_paginated(
            api.list_credit_memos(TM, params={"store_id": refs["store"]["id"]})
        )
        assert len(memos) == 1
        assert memos[0]["amount_cents"] == 1094
        assert memos[0]["status"] == "APPLIED"
        assert memos[0]["applied_cents"] == 1094

        invoice = validate_success(api.get_invoice(refs["invoice"]["id"], TM), 200)
        assert invoice["credits_applied_cents"] == 1094
        assert invoice["amount_due_cents"] == 0
        assert invoice["status"] == "SETTLED"
        assert order["payment_status"] == "PAID"

    def test_cascade_return_fields_and_store_ar_recomputed(self, api):
        """PRD §3.4: "for each flagged order line, the system creates a
        `Return` with `reason_code` `COLD_CHAIN`, `quantity_units` equal to
        the line's `delivered_units`, the line's `scanned_code_date`, a
        `credit_pct` of 1.0"
        PRD §3.4: "the store's `open_ar_cents` — the sum of `amount_due_cents`
        over its `OPEN` invoices — is recomputed."

        Design: Difficulty/transitive_cascade/qa_breach_cascade_five_deep
        """
        refs = self._setup_breached_trip_in_qa(api, "H2")
        validate_success(
            api.adjudicate_trip(refs["trip"]["id"], {"verdict": "CONFIRM_BREACH"}, QI),
            200,
        )
        returns, _ = validate_paginated(
            api.list_returns(TM, params={"order_id": refs["order"]["id"]})
        )
        ret = returns[0]
        assert ret["reason_code"] == "COLD_CHAIN"
        assert ret["credit_pct"] == pytest.approx(1.0)
        assert ret["quantity_units"] == 5
        assert ret["scanned_code_date"] == "2026-08-20"

        store = get_store(refs["store"]["id"])
        assert store["open_ar_cents"] == 0, (
            "the cascade-settled invoice no longer contributes to open AR"
        )
