"""Return program: window boundary, availability accounting, restocking-fee
arithmetic, the reject/resubmit cycle, and receipt dispositions."""
from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    assert_product_unit_invariant,
    close_ordering_at_window_end,
    create_campaign,
    create_group,
    create_product,
    create_received_return,
    create_return_request,
    create_seller,
    create_submitted_paid_order,
    drive_campaign_to_distribution_complete,
    get_group_ledger,
    get_order_line_id,
    get_success_data,
    make_treasurer_headers,
    reset_clock,
    setup_open_campaign_with_seller,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
TREAS = TEST_USERS["treasurer_headers"]
TREAS2 = make_treasurer_headers("treas-2")


def _distributed_context(api, quantity=3, **product_overrides):
    """Campaign at DISTRIBUTION_COMPLETE with one fully paid order, clock
    inside the return window. Returns the context."""
    reset_clock()
    campaign = create_campaign()
    group = create_group(campaign["id"])
    product = create_product(campaign["id"], **product_overrides)
    seller = create_seller(group["id"])
    get_success_data(api.open_campaign(campaign["id"], ADMIN))
    order = create_submitted_paid_order(seller["id"], product["id"], quantity)
    close_ordering_at_window_end(campaign["id"])
    drive_campaign_to_distribution_complete(campaign["id"], product["id"], 12)
    reset_clock(TEST_DEFAULTS["INSIDE_RETURN_WINDOW"])
    line_id = get_order_line_id(order["id"])
    return campaign, group, product, seller, order, line_id


class TestReturnWindowBoundary:
    def test_return_window_last_day_allowed_next_second_rejected(self, api):
        """PRD §3.6: "the logical clock must be at or before
        `distribution_completed_at` plus 7 days — the final instant of day
        seven is still eligible; later attempts are rejected with
        `ERR_RETURN_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/return_window_last_day_allowed_next_second_rejected
        """
        campaign, group, product, seller, order, line_id = (
            _distributed_context(api, quantity=2))
        # distribution_completed_at == 2026-09-06T16:00:00Z (the fixture's
        # distribution instant); the final instant of day seven is eligible.
        reset_clock(TEST_DEFAULTS["RETURN_WINDOW_LAST_INSTANT"])
        created = create_return_request(seller["id"], order["id"], line_id, 1,
                                        "UNSOLD")
        assert created["status"] == "REQUESTED"

        reset_clock("2026-09-13T16:00:01Z")
        resp = api.create_return_request({
            "seller_id": seller["id"], "order_id": order["id"],
            "order_line_id": line_id, "quantity": 1, "reason": "UNSOLD",
        }, COORD)
        validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED)

    def test_return_window_boundary_inclusive_final_instant(self, api):
        """PRD §3.6: "the logical clock must be at or before
        `distribution_completed_at` plus 7 days — the final instant of day
        seven is still eligible".

        Design: Difficulty/boundary_precision_check/return_window_last_day_allowed_next_second_rejected
        """
        campaign, group, product, seller, order, line_id = (
            _distributed_context(api, quantity=2))
        reset_clock(TEST_DEFAULTS["RETURN_WINDOW_LAST_INSTANT"])
        created = create_return_request(seller["id"], order["id"], line_id, 2,
                                        "FAMILY_CHANGED_MIND")
        assert created["status"] == "REQUESTED", (
            "a return at exactly distribution_completed_at + 7 days succeeds")


class TestReturnCreditArithmetic:
    def test_return_credit_tiered_fee_waive_and_availability(self, api):
        """PRD §3.6: "the per-unit restocking fee is zero when the reason is
        `DEFECTIVE` or `WRONG_ITEM`, and otherwise is the line's snapshotted
        `unit_price_cents` times 1000 basis points divided by 10000, rounded
        half up to whole cents per unit; the return's `restocking_fee_cents`
        is that per-unit fee times the `quantity`, and its `refund_cents` is
        the `quantity` times the snapshotted `unit_price_cents` minus the
        `restocking_fee_cents`."

        Design: Difficulty/combinatorial_formula/return_credit_tiered_fee_waive_and_availability
        """
        campaign, group, product, seller, order, line_id = (
            _distributed_context(api, quantity=3))
        received = create_received_return(seller["id"], order["id"], line_id,
                                          2, "UNSOLD", "RESTOCKABLE")
        assert received["status"] == "RECEIVED_RESTOCKED"
        # per-unit fee round_half_up(1000 * 1000/10000) == 100; times 2 == 200.
        assert received["restocking_fee_cents"] == 200
        assert received["refund_cents"] == 1800, "2*1000 - 200"

        ledger = get_group_ledger(group["id"])
        return_debits = [e for e in ledger
                         if e["entry_type"] == "RETURN_DEBIT"]
        assert len(return_debits) == 1
        # round_half_up(2 * (1000-600) * 5000/10000) == 400, debits negative.
        assert return_debits[0]["amount_cents"] == -400
        group_view = get_success_data(api.get_group(group["id"], TREAS))
        assert group_view["proceeds_balance_cents"] == 200, (
            "provisional 600 - 400 return debit")

        product_view = get_success_data(api.get_product(product["id"], TREAS))
        assert product_view["restocked_units"] == 2
        assert product_view["distributed_units"] == 1
        assert product_view["surplus_units"] == 9
        assert_product_unit_invariant(product_view)

        order_view = get_success_data(api.get_order(order["id"], TREAS))
        assert order_view["fulfillment_status"] == "PARTIALLY_RETURNED"

    def test_return_availability_reduced_by_sibling_open_returns(self, api):
        """PRD §3.6: "The requested quantity must not exceed the line's
        availability: the line's `quantity` minus its `returned_qty`, its
        `claim_resolved_refund_qty`, and its `sort_shortage_qty`, further
        reduced by the quantities of sibling return requests on the same line
        still in `REQUESTED` or `APPROVED` — a request beyond that is rejected
        with `ERR_RETURN_QTY_EXCEEDS_AVAILABLE`."

        Design: Difficulty/combinatorial_formula/return_credit_tiered_fee_waive_and_availability
        """
        campaign, group, product, seller, order, line_id = (
            _distributed_context(api, quantity=3))
        create_return_request(seller["id"], order["id"], line_id, 2, "UNSOLD")
        # Sibling REQUESTED return reserves 2 of 3: only 1 remains available.
        resp = api.create_return_request({
            "seller_id": seller["id"], "order_id": order["id"],
            "order_line_id": line_id, "quantity": 2, "reason": "UNSOLD",
        }, COORD)
        validate_error(resp, ApiErrorId.ERR_RETURN_QTY_EXCEEDS_AVAILABLE)

    def test_restock_fee_rounding_half_up(self, api):
        """PRD §3.6: "otherwise is the line's snapshotted `unit_price_cents`
        times 1000 basis points divided by 10000, rounded half up to whole
        cents per unit; the return's `restocking_fee_cents` is that per-unit
        fee times the `quantity`, and its `refund_cents` is the `quantity`
        times the snapshotted `unit_price_cents` minus the
        `restocking_fee_cents`."
        PRD §2.6: "rounding is always to the nearest whole cent using round
        half up (a fraction of exactly one-half cent rounds away from zero)".

        Design: Corner/calculations/restock_fee_rounding_half_up
        """
        campaign, group, product, seller, order, line_id = (
            _distributed_context(api, quantity=1, name="Tumbler",
                                 sku="TMB-01", unit_price_cents=1055))
        ret = create_return_request(seller["id"], order["id"], line_id, 1,
                                    "UNSOLD")
        resp = api.approve_return_request(ret["id"], TREAS2)
        approved = validate_success(resp, 200)
        # round_half_up(1055 * 1000/10000) == round_half_up(105.5) == 106.
        assert approved["restocking_fee_cents"] == 106
        assert approved["refund_cents"] == 949, "1055 - 106"


class TestReturnCycleAndReceipt:
    def test_return_request_reject_resubmit_cycle(self, api):
        """PRD §3.6: "A `REJECTED` return may be resubmitted by a coordinator
        with a revised `quantity` and `reason` while the return window is
        still open (else `ERR_RETURN_WINDOW_EXPIRED`); the revised quantity
        must satisfy the same availability check as creation (else
        `ERR_RETURN_QTY_EXCEEDS_AVAILABLE`), and the resubmission moves the
        request back to `REQUESTED` and increments `resubmission_count` by 1."
        PRD §3.6: "the per-unit restocking fee is zero when the reason is
        `DEFECTIVE` or `WRONG_ITEM`".

        Design: Difficulty/non_linear_state_machine/return_request_reject_resubmit_cycle
        """
        campaign, group, product, seller, order, line_id = (
            _distributed_context(api, quantity=3))
        ret = create_return_request(seller["id"], order["id"], line_id, 1,
                                    "UNSOLD")
        get_success_data(api.reject_return_request(
            ret["id"], TREAS, {"reason": "photos required"}))
        resp = api.resubmit_return_request(
            ret["id"], {"quantity": 2, "reason": "WRONG_ITEM"}, COORD)
        resubmitted = validate_success(resp, 200)
        assert resubmitted["status"] == "REQUESTED", (
            "REJECTED -> REQUESTED on the same entity")
        assert resubmitted["resubmission_count"] == 1

        get_success_data(api.approve_return_request(ret["id"], TREAS))
        received = get_success_data(api.receive_return_request(
            ret["id"], {"disposition": "DAMAGED_WRITE_OFF"}, TREAS))
        assert received["status"] == "RECEIVED_WRITTEN_OFF"
        assert received["restocking_fee_cents"] == 0, (
            "WRONG_ITEM waives the restocking fee")
        assert received["refund_cents"] == 2000, "2 * 1000 - 0"

        product_view = get_success_data(api.get_product(product["id"], TREAS))
        assert product_view["written_off_units"] == 2
        assert product_view["distributed_units"] == 1
        order_view = get_success_data(api.get_order(order["id"], TREAS))
        assert order_view["fulfillment_status"] == "PARTIALLY_RETURNED"

    def test_return_resubmit_increments_count_each_cycle(self, api):
        """PRD §3.6: "the resubmission moves the request back to `REQUESTED`
        and increments `resubmission_count` by 1."

        Design: Difficulty/non_linear_state_machine/return_request_reject_resubmit_cycle
        """
        campaign, group, product, seller, order, line_id = (
            _distributed_context(api, quantity=3))
        ret = create_return_request(seller["id"], order["id"], line_id, 1,
                                    "UNSOLD")
        get_success_data(api.reject_return_request(ret["id"], TREAS))
        get_success_data(api.resubmit_return_request(
            ret["id"], {"quantity": 1, "reason": "UNSOLD"}, COORD))
        get_success_data(api.reject_return_request(ret["id"], TREAS))
        again = get_success_data(api.resubmit_return_request(
            ret["id"], {"quantity": 1, "reason": "DEFECTIVE"}, COORD))
        assert again["resubmission_count"] == 2, (
            "each rejection cycle adds one to resubmission_count")

    def test_return_full_quantity_marks_order_returned(self, api):
        """PRD §3.6: "When every line's `returned_qty` plus
        `claim_resolved_refund_qty` reaches its full `quantity`, the order
        moves to the terminal `RETURNED`, either in one step from
        `DISTRIBUTED` or from `PARTIALLY_RETURNED`."
        PRD §3.6: "the per-unit restocking fee is zero when the reason is
        `DEFECTIVE` or `WRONG_ITEM`".

        Design: Corner/state_machines/return_full_quantity_marks_order_returned
        """
        campaign, group, product, seller, order, line_id = (
            _distributed_context(api, quantity=2))
        received = create_received_return(seller["id"], order["id"], line_id,
                                          2, "DEFECTIVE", "RESTOCKABLE")
        assert received["status"] == "RECEIVED_RESTOCKED"
        assert received["refund_cents"] == 2000, (
            "DEFECTIVE waives the fee: 2 * 1000 - 0")
        order_view = get_success_data(api.get_order(order["id"], TREAS))
        assert order_view["fulfillment_status"] == "RETURNED", (
            "a full-quantity return drives fulfillment to its RETURNED "
            "terminal state in one step")
        seller_view = get_success_data(api.get_seller(seller["id"], COORD))
        assert seller_view["units_sold"] == 0

    def test_return_qty_exceeds_available_rejected(self, api):
        """PRD §3.6: "The requested quantity must not exceed the line's
        availability: the line's `quantity` minus its `returned_qty`, its
        `claim_resolved_refund_qty`, and its `sort_shortage_qty`, further
        reduced by the quantities of sibling return requests on the same line
        still in `REQUESTED` or `APPROVED` — a request beyond that is rejected
        with `ERR_RETURN_QTY_EXCEEDS_AVAILABLE`."

        Design: Corner/validations/return_qty_exceeds_available_rejected
        """
        campaign, group, product, seller, order, line_id = (
            _distributed_context(api, quantity=2))
        create_received_return(seller["id"], order["id"], line_id, 2,
                               "UNSOLD", "RESTOCKABLE")
        resp = api.create_return_request({
            "seller_id": seller["id"], "order_id": order["id"],
            "order_line_id": line_id, "quantity": 1, "reason": "UNSOLD",
        }, COORD)
        validate_error(resp, ApiErrorId.ERR_RETURN_QTY_EXCEEDS_AVAILABLE)

    def test_return_non_returnable_product_rejected(self, api):
        """PRD §3.6: "The product must be `returnable`, else
        `ERR_PRODUCT_NOT_RETURNABLE`."

        Design: Corner/validations/return_non_returnable_product_rejected
        """
        campaign, group, product, seller, order, line_id = (
            _distributed_context(api, quantity=1, returnable=False))
        resp = api.create_return_request({
            "seller_id": seller["id"], "order_id": order["id"],
            "order_line_id": line_id, "quantity": 1, "reason": "UNSOLD",
        }, COORD)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_RETURNABLE)


class TestUnitConservation:
    def test_verify_then_restock_return_conserves_product_units(self, api):
        """PRD §3.8: "each product conserves units across five buckets whose
        invariant must always hold: `delivered_units` equals the sum of
        `distributed_units`, `restocked_units`, `written_off_units`,
        `surplus_units`, and `lost_units`."

        Design: Difficulty/compensating_invariant/verify_then_restock_return_conserves_product_units
        """
        reset_clock()
        campaign, group, product, seller = setup_open_campaign_with_seller()
        order = create_submitted_paid_order(seller["id"], product["id"], 3)
        close_ordering_at_window_end(campaign["id"])
        drive_campaign_to_distribution_complete(
            campaign["id"], product["id"], 12)

        after_dist = get_success_data(api.get_product(product["id"], ADMIN))
        assert after_dist["delivered_units"] == 12
        assert after_dist["distributed_units"] == 3
        assert after_dist["surplus_units"] == 9
        assert_product_unit_invariant(after_dist)

        reset_clock("2026-09-11T12:00:00Z")
        line_id = get_order_line_id(order["id"])
        create_received_return(seller["id"], order["id"], line_id, 2,
                               "UNSOLD", "RESTOCKABLE")
        final = get_success_data(api.get_product(product["id"], ADMIN))
        assert final["delivered_units"] == 12
        assert final["distributed_units"] == 1
        assert final["restocked_units"] == 2
        assert final["surplus_units"] == 9
        assert final["written_off_units"] == 0
        assert final["lost_units"] == 0
        assert_product_unit_invariant(final)

    def test_unit_buckets_at_delivery(self, api):
        """PRD §3.8: "The buckets move at five moments — supplier delivery
        (sets `delivered_units`, adds into `surplus_units`)".

        Design: Difficulty/compensating_invariant/verify_then_restock_return_conserves_product_units
        """
        reset_clock()
        campaign, group, product, seller = setup_open_campaign_with_seller()
        create_submitted_paid_order(seller["id"], product["id"], 3)
        close_ordering_at_window_end(campaign["id"])
        from test_helpers import drive_campaign_to_delivered
        drive_campaign_to_delivered(campaign["id"], product["id"], 12)
        view = get_success_data(api.get_product(product["id"], ADMIN))
        assert view["delivered_units"] == 12
        assert view["surplus_units"] == 12
        assert view["distributed_units"] == 0
        assert view["lost_units"] == 0
        assert_product_unit_invariant(view)
