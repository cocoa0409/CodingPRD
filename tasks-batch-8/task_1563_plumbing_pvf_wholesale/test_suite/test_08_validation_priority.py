"""Validation-pipeline precedence: which error wins when several checks fail (PRD §2.7)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_order_line_payload,
    create_order_payload,
    create_picked_up_order,
    create_submitted_order,
    get_order_line,
    get_stock_row,
    make_account,
    make_branch,
    make_product,
    make_slot,
    make_stock,
    setup_branch_product_account,
    validate_error,
    validate_success,
)

REP = TEST_USERS["counterrep_headers"]
SALES = TEST_USERS["sales_headers"]

PIPELINE = (
    'PRD §2.7: "Every request is validated against an ordered pipeline, and when '
    'several checks would fail on the same request, the check that sits earliest '
    'in this order determines the returned error"'
)


class TestStateBeatsFiscal:
    def _setup(self):
        """Account limit 100000; order 1 picked up (INVOICED 54000); order 2
        submitted (OPEN, total 42100 — forward exposure 96100)."""
        branch = make_branch()
        p1 = make_product(sku="P1")
        p2 = make_product(
            sku="P2", description="Ball valve", category="VALVE",
            list_price_cents=4000, cost_cents=2000, cubes_per_unit=5,
        )
        account = make_account(credit_limit_cents=100000)
        make_stock(branch["id"], p1["id"], 30)
        make_stock(branch["id"], p2["id"], 30)
        create_picked_up_order(account["id"], branch["id"], [(p1["id"], 6)])
        order2, line2 = create_submitted_order(account["id"], branch["id"], [(p2["id"], 11)], will_call=True)
        return branch, p2, account, order2, line2[0]

    def test_double_submit_reports_state_not_fiscal(self, api):
        """PRD §2.7: "Every request is validated against an ordered pipeline, and
        when several checks would fail on the same request, the check that sits
        earliest in this order determines the returned error". State-machine
        gating (step 7: "State-machine gating — the target entity's current
        status permits the requested transition; otherwise `ERR_INVALID_STATE`")
        precedes the fiscal credit-limit rule (step 8: "and finally fiscal rules
        (credit limit, price floor, override authority)").

        The second submit violates both — the order is already OPEN, and
        re-counting its 42100 would push exposure 96100 + 42100 = 138200 past
        the 100000 limit — so the state error must win.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_double_submit
        """
        _, _, _, order2, _ = self._setup()
        res = api.submit_order(order2["id"], REP)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_double_submit_leaves_order_and_stock_untouched(self, api, sales_headers):
        """PRD §2.7: "State-machine gating — the target entity's current status
        permits the requested transition; otherwise `ERR_INVALID_STATE`."
        PRD §3.7: "On a successful submission the order's `fulfillment_status`
        moves from `DRAFT` to `OPEN`, and each line reserves stock per §2.10".

        A rejected re-submit performs no reservation: the order stays
        submitted (OPEN, or PICKING once the all-lines-allocated bubble-up of
        §3.7 lands) with its version unchanged, and the P2 stock row keeps its
        reservation of 11.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_double_submit
        """
        branch, p2, _, order2, line2_id = self._setup()
        version_before = order2["version"]
        res = api.submit_order(order2["id"], REP)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

        after = validate_success(api.get_order(order2["id"], sales_headers))
        assert after["fulfillment_status"] in ("OPEN", "PICKING")
        assert after["version"] == version_before, "a rejected submit must not mutate the order"
        row = get_stock_row(branch["id"], p2["id"])
        assert row["reserved"] == 11, f"no second reservation may happen, got {row['reserved']}"


class TestExistenceBeatsState:
    def _setup_open_order(self):
        branch, product, account = setup_branch_product_account(stock=5)
        order, line_ids = create_submitted_order(account["id"], branch["id"], [(product["id"], 1)])
        return branch, product, account, order, line_ids[0]

    def test_unknown_product_on_open_order_reports_existence_not_state(self, api):
        """PRD §2.7: body-referenced identifiers (step 6: "Body-referenced identifiers — foreign keys carried in the payload (the `product_id` on a line add, the `slot_id` on a booking, the `order_id` on a return, the `account_id` and `branch_id` on creates, the `substitute_product_id` on a substitute proposal) resolve to existing resources; otherwise the corresponding not-found error, such as `ERR_PRODUCT_NOT_FOUND`, is returned.") precede state-machine gating (step 7: "State-machine gating — the target entity's current status permits the requested transition; otherwise `ERR_INVALID_STATE`.").

        The order is already OPEN (line add is a DRAFT-only mutation), but the
        bogus product id must surface ERR_PRODUCT_NOT_FOUND first.

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_line_add
        """
        _, _, _, order, _ = self._setup_open_order()
        res = api.add_order_line(
            order["id"], create_order_line_payload(NON_EXISTENT_UUID, 1), REP
        )
        validate_error(res, ApiErrorId.ERR_PRODUCT_NOT_FOUND)

    def test_rejected_line_add_leaves_order_untouched(self, api, sales_headers):
        """PRD §2.7: "Body-referenced identifiers — foreign keys carried in the payload (the `product_id` on a line add, the `slot_id` on a booking, the `order_id` on a return, the `account_id` and `branch_id` on creates, the `substitute_product_id` on a substitute proposal) resolve to existing resources; otherwise the corresponding not-found error, such as `ERR_PRODUCT_NOT_FOUND`, is returned."

        The rejected add changes nothing: the order still has exactly its one
        original line and stays OPEN.

        Design: Difficulty/priority_pair_validation_conflict/existence_beats_state_on_line_add
        """
        _, _, _, order, line_id = self._setup_open_order()
        res = api.add_order_line(
            order["id"], create_order_line_payload(NON_EXISTENT_UUID, 1), REP
        )
        validate_error(res, ApiErrorId.ERR_PRODUCT_NOT_FOUND)

        lines = validate_success(api.get_order_lines(order["id"], sales_headers))
        rows = lines if isinstance(lines, list) else lines.get("data", [])
        assert [r["id"] for r in rows] == [line_id]
        after = validate_success(api.get_order(order["id"], sales_headers))
        assert after["fulfillment_status"] in ("OPEN", "PICKING")


class TestTemporalBeatsCapacity:
    def _setup(self):
        """Slot with a past window (creation does not sweep it) and capacity 1;
        submitted order whose cubes_total is 2."""
        branch = make_branch()
        big = make_product(
            sku="PBIG", description="Big valve", category="VALVE",
            list_price_cents=4000, cost_cents=2000, cubes_per_unit=2,
        )
        account = make_account()
        slot = make_slot(
            branch["id"],
            window_start="2026-07-20T08:00:00Z", window_end="2026-07-20T12:00:00Z",
            capacity_cubes=1,
        )
        make_stock(branch["id"], big["id"], 5)
        order, _ = create_submitted_order(account["id"], branch["id"], [(big["id"], 1)])
        return branch, account, order, slot

    def test_past_window_reports_temporal_not_capacity(self, api):
        """PRD §2.7 step 8: "Account-standing gates, quote freshness, optimistic-concurrency freshness, temporal business rules (delivery-window past, return window, program period), business constraints (uniqueness, overlaps, capacity, segregation of duties, returnability, kit membership, substitute eligibility, line-order membership), and finally fiscal rules (credit limit, price floor, override authority) — each detailed in §2.8 through §2.11 and in the workflow narratives of §3." — temporal rules precede capacity in the pipeline.
        PRD §3.9: "The slot's `window_end` must still be ahead of the logical
        clock, else `ERR_DELIVERY_WINDOW_PAST`."

        The booking violates both the temporal rule (window ended 2026-07-20)
        and capacity (0 + 2 > 1); the temporal error must win.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_capacity_on_slot_booking
        """
        _, _, order, slot = self._setup()
        res = api.book_delivery(
            order["id"],
            {"slot_id": slot["id"], "expected_order_version": order["version"]},
            REP,
        )
        validate_error(res, ApiErrorId.ERR_DELIVERY_WINDOW_PAST)

    def test_rejected_booking_changes_nothing(self, api, sales_headers):
        """PRD §3.9: "The slot's `window_end` must still be ahead of the logical
        clock, else `ERR_DELIVERY_WINDOW_PAST`."
        PRD §2.11: "its `booked_cubes` is the sum of `cubes_total` over orders
        holding an active booking in that slot".

        The rejected booking leaves the slot empty and the order unbooked.

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_capacity_on_slot_booking
        """
        _, _, order, slot = self._setup()
        res = api.book_delivery(
            order["id"],
            {"slot_id": slot["id"], "expected_order_version": order["version"]},
            REP,
        )
        validate_error(res, ApiErrorId.ERR_DELIVERY_WINDOW_PAST)

        slot_after = validate_success(api.get_slot(slot["id"], sales_headers))
        assert slot_after["booked_cubes"] == 0
        order_after = validate_success(api.get_order(order["id"], sales_headers))
        assert order_after["delivery_slot_id"] is None
