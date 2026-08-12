"""Inspection, refund settlement, and the append-only ledger: tiered
deductions with the free_returns override, per-line rounding order, the
provisional-vs-final divergence, zero-refund settlement, ledger append
legality, and the payable-conservation invariant."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    append_ledger_entry_payload,
    create_counter_order_dropped_off,
    create_location,
    create_order,
    create_return_item_line,
    fulfill_order_to_refund_posted,
    fulfill_order_via_pickup,
    get_order,
    get_projection,
    inspect_item,
    list_order_items,
    resolve_exception,
    setup_commercial_spine,
    start_investigation,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["support_agent_headers"]


def _pickup_spine(email, **plan_overrides):
    merged = {"pickup_enabled": True}
    merged.update(plan_overrides)
    return setup_commercial_spine(plan_overrides=merged, shopper_email=email,
                                  with_zone=True)


class TestInspection:

    def test_item_double_inspect_rejected(self, api):
        """PRD §3.8: "an item already `INSPECTED` rejects a second inspection
        with `ERR_ITEM_ALREADY_INSPECTED`."

        Design: Corner/state_machines/item_double_inspect_rejected
        """
        spine = _pickup_spine("sdi@x.com")
        order, items = fulfill_order_via_pickup(
            spine,
            items=[
                create_return_item_line(sku="D1", unit_price_cents=100),
                create_return_item_line(sku="D2", unit_price_cents=200),
            ],
        )
        inspect_item(items[0]["id"], "NEW")

        resp = api.inspect_return_item(
            items[0]["id"], {"condition": "DAMAGED"}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_ITEM_ALREADY_INSPECTED)

        # Second item still PENDING: the order stays INSPECTING.
        order_after = get_order(order["id"])
        assert order_after["status"] == "INSPECTING"

    def test_error_invalid_state_on_item_inspect_before_receipt(self, api):
        """PRD §3.8: "The parent order must be in `INSPECTING` or
        `EXCEPTION_PENDING`, else the attempt fails with `ERR_INVALID_STATE`,
        and an item already `INSPECTED` rejects a second inspection with
        `ERR_ITEM_ALREADY_INSPECTED`."

        Design: Corner/errors/error_invalid_state_on_item_inspect_before_receipt
        """
        spine = setup_commercial_spine(
            plan_overrides={"pickup_enabled": False}, shopper_email="sis@x.com"
        )
        location = create_location(name="L-IS", kind="COUNTER")
        order = create_counter_order_dropped_off(spine, location)
        items = list_order_items(order["id"])
        resp = api.inspect_return_item(items[0]["id"], {"condition": "NEW"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestDeductionMath:

    def test_item_deduction_condition_tier_plan_flag_interplay(self, api):
        """PRD §3.8: "the deduction percentage follows the *inspected*
        condition — zero for `NEW`, ten percent for `LIGHT_USE`, fifty percent
        for `DAMAGED`, zero for `DEFECTIVE`, and one hundred percent for
        `WRONG_ITEM`; then the plan override applies, so when the merchant's
        plan has `free_returns`, a `NEW` or `LIGHT_USE` line's percentage is
        waived to zero — while a `DAMAGED` line is never waived and always
        keeps its fifty percent."

        Design: Difficulty/combinatorial_formula/item_deduction_condition_tier_plan_flag_interplay
        """
        spine = _pickup_spine("st@x.com", free_returns=True)
        order, items = fulfill_order_via_pickup(
            spine,
            items=[
                create_return_item_line(sku="TA", unit_price_cents=4000,
                                        declared_condition="NEW",
                                        longest_side_cm=20, weight_grams=200),
                create_return_item_line(sku="TB", unit_price_cents=2500,
                                        declared_condition="LIGHT_USE",
                                        longest_side_cm=20, weight_grams=200),
            ],
        )
        item_a = inspect_item(items[0]["id"], "DAMAGED")
        inspect_item(items[1]["id"], "DEFECTIVE")

        assert item_a["deduction_cents"] == 2000  # 50% of 4000, never waived
        item_b = validate_success(api.get_return_item(items[1]["id"], ADMIN))
        assert item_b["deduction_cents"] == 0  # DEFECTIVE: 0% tier

        order_after = get_order(order["id"])
        assert order_after["refund_final_cents"] == 4500  # 2000 + 2500
        assert order_after["status"] == "REFUND_POSTED"

    def test_refund_per_line_rounding_then_sum_pinned(self, api):
        """PRD §2.6: "First, per-line rounding: each return item's
        `deduction_cents` is rounded half-up individually **before** any
        summation, and the order-level refund is then the sum of
        already-rounded lines. Summing unrounded line values and rounding the
        total is forbidden, because the two orders of operation diverge by
        cents on multi-line orders."

        Design: Difficulty/combinatorial_formula/refund_per_line_rounding_then_sum_pinned
        """
        spine = _pickup_spine("sr@x.com", free_returns=False)
        order, items = fulfill_order_via_pickup(
            spine,
            items=[
                create_return_item_line(sku="R1", unit_price_cents=3333,
                                        longest_side_cm=15),
                create_return_item_line(sku="R2", unit_price_cents=3333,
                                        longest_side_cm=15),
            ],
        )
        item_1 = inspect_item(items[0]["id"], "LIGHT_USE")
        item_2 = inspect_item(items[1]["id"], "LIGHT_USE")

        # round_half_up(3333 * 0.10) = 333 per line -> total deduction 666.
        assert item_1["deduction_cents"] == 333
        assert item_2["deduction_cents"] == 333
        projection = get_projection(order["id"])
        # Per-line-then-sum yields 6000; sum-then-round would yield 5999.
        assert projection["final_cents"] == 6000

    def test_refund_provisional_vs_final_free_returns_divergence(self, api):
        """PRD §3.3: "The provisional variant is deliberately pessimistic: each
        line's gross is its `unit_price_cents` multiplied by its `quantity`; a
        deduction percentage is taken from the *declared* condition — zero for
        `NEW`, ten percent for `LIGHT_USE`, fifty percent for `DAMAGED`, zero
        for `DEFECTIVE`, and one hundred percent for `WRONG_ITEM`; and the
        plan's `free_returns` waiver is *not* applied."
        PRD §3.8: "when the merchant's plan has `free_returns`, a `NEW` or
        `LIGHT_USE` line's percentage is waived to zero".

        Design: Difficulty/dual_variant_calc/refund_provisional_vs_final_free_returns_divergence
        """
        spine = _pickup_spine(
            "s1@x.com", free_returns=True, monthly_fee_cents=29900,
            included_returns=200, overage_fee_cents=200,
            oversize_surcharge_cents=1500, pickup_fee_cents=700,
        )
        # One line: qty 2 at 5000 declared LIGHT_USE -> gross 10000,
        # provisional deduction 10% = 1000 -> estimate 9000.
        order, items = fulfill_order_via_pickup(
            spine,
            items=[create_return_item_line(sku="A", quantity=2,
                                           unit_price_cents=5000,
                                           declared_condition="LIGHT_USE",
                                           longest_side_cm=40,
                                           weight_grams=800)],
        )
        order_at_create = get_order(order["id"])
        assert order_at_create["refund_estimate_cents"] == 9000

        inspect_item(items[0]["id"], "LIGHT_USE", note="ok")

        order_after = get_order(order["id"])
        # Final: free_returns waives LIGHT_USE -> deduction 0 -> 10000.
        assert order_after["refund_final_cents"] == 10000
        assert order_after["status"] == "REFUND_POSTED"

        projection = get_projection(order["id"])
        assert projection["final_cents"] == 10000
        assert projection["payable_cents"] == 10000
        assert projection["refund_status"] == "POSTED"


class TestZeroRefund:

    def test_zero_refund_full_deduction_posts_cleanly(self, api):
        """PRD §3.8: "one hundred percent for `WRONG_ITEM`".
        PRD §3.8: "If an exception *is* still open, the order simply stays in
        `EXCEPTION_PENDING` and resolution is deferred until the exception
        itself resolves."
        PRD §3.9: "A rejected case whose kind carries no terminal cascade
        follows that same re-evaluation with item conditions unchanged."

        Design: Corner/calculations/zero_refund_full_deduction_posts_cleanly
        """
        spine = _pickup_spine("szr@x.com")
        order, items = fulfill_order_via_pickup(
            spine,
            items=[create_return_item_line(sku="ZR", unit_price_cents=4000)],
        )
        inspect_item(items[0]["id"], "WRONG_ITEM")

        # The last item being WRONG_ITEM auto-created a system exception.
        from test_helpers import api_client
        cases = validate_success(
            api_client.list_order_exception_cases(order["id"], ADMIN)
        )
        case = start_investigation(cases[0]["id"])
        resolve_exception(case["id"], "REJECTED")

        projection = get_projection(order["id"])
        assert projection["final_cents"] == 0
        assert projection["payable_cents"] == 0
        assert projection["refund_status"] == "POSTED"
        order_after = get_order(order["id"])
        assert order_after["status"] == "REFUND_POSTED"


class TestLedgerLegality:

    def _posted_order(self, email, unit_price_cents=10000):
        spine = _pickup_spine(email)
        order, _projection = fulfill_order_to_refund_posted(
            spine, items=[create_return_item_line(
                sku="LD", unit_price_cents=unit_price_cents,
                longest_side_cm=20)]
        )
        return spine, order

    def test_error_adjustment_exceeds_payable(self, api):
        """PRD §3.8: "the ledger must never be driven underwater: any entry
        that would push the order's payable amount below zero is rejected with
        `ERR_ADJUSTMENT_EXCEEDS_PAYABLE`."

        Design: Corner/errors/error_adjustment_exceeds_payable
        """
        _spine, order = self._posted_order("sax@x.com")
        resp = api.append_ledger_entry(
            order["id"],
            append_ledger_entry_payload("ADJUSTMENT", -20000, "clawback attempt"),
            AGENT,
        )
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_PAYABLE)

    def test_error_correction_requires_admin(self, api):
        """PRD §3.8: "a `CORRECTION` is reserved for a `PlatformAdmin` and any
        other role attempting one is refused with
        `ERR_CORRECTION_REQUIRES_ADMIN`."

        Design: Corner/errors/error_correction_requires_admin
        """
        _spine, order = self._posted_order("scr@x.com")
        resp = api.append_ledger_entry(
            order["id"],
            append_ledger_entry_payload("CORRECTION", -100, "agent attempt"),
            AGENT,
        )
        validate_error(resp, ApiErrorId.ERR_CORRECTION_REQUIRES_ADMIN)

    def test_error_final_append_via_endpoint_rejected(self, api):
        """PRD §3.8: "`ESTIMATE` and `FINAL` entries are system-only and
        always non-negative; exactly one `FINAL` may ever exist for an order,
        and any attempt that would introduce a second is refused with
        `ERR_REFUND_FINAL_POSTED`."

        Design: Corner/errors/error_final_append_via_endpoint_rejected
        """
        _spine, order = self._posted_order("sfp@x.com", unit_price_cents=100)
        resp = api.append_ledger_entry(
            order["id"],
            append_ledger_entry_payload("FINAL", 100, "fake final"),
            ADMIN,
        )
        # PRD §3.8 pins ERR_REFUND_FINAL_POSTED for a second-FINAL attempt,
        # while §4 scopes this endpoint to "an ADJUSTMENT or CORRECTION
        # entry", which a faithful reader may enforce as ERR_INVALID_REQUEST
        # at shape level — the PRD does not pin which fires first.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_REFUND_FINAL_POSTED.value,
                   ApiErrorId.ERR_INVALID_REQUEST.value],
        )

    def test_error_ledger_append_on_unposted_order_rejected(self, api):
        """PRD §3.8: "Human agents append the other two kinds against an order
        that has already posted its refund".
        PRD §2.8: "the target resource is in a valid from-state for the
        requested transition and terminal resources reject everything, else
        `ERR_INVALID_STATE` or `ERR_ALREADY_TERMINAL`."

        Design: Corner/errors/error_ledger_append_on_unposted_order_rejected
        """
        spine = _pickup_spine("slu@x.com")
        order = create_order(spine, method="COUNTER_DROP")
        resp = api.append_ledger_entry(
            order["id"],
            append_ledger_entry_payload("ADJUSTMENT", 100, "too early"),
            AGENT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_ledger_adjustment_correction_conserves_payable(self, api):
        """PRD §3.8: "The `payable_cents` is the latest `FINAL` amount (or
        zero when none exists) plus the sum of all `ADJUSTMENT` entries plus
        the sum of all `CORRECTION` entries."

        Design: Difficulty/compensating_invariant/ledger_adjustment_correction_conserves_payable
        """
        _spine, order = self._posted_order("sle@x.com")

        pre = get_projection(order["id"])
        assert pre["payable_cents"] == 10000
        assert pre["entry_count"] == 2  # ESTIMATE + FINAL

        validate_success(
            api.append_ledger_entry(
                order["id"],
                append_ledger_entry_payload("ADJUSTMENT", 500, "goodwill"),
                AGENT,
            ),
            expected_status=201,
        )
        mid = get_projection(order["id"])
        assert mid["payable_cents"] == 10500

        validate_success(
            api.append_ledger_entry(
                order["id"],
                append_ledger_entry_payload("CORRECTION", -500,
                                            "reverse goodwill"),
                ADMIN,
            ),
            expected_status=201,
        )
        post = get_projection(order["id"])
        assert post["payable_cents"] == 10000
        assert post["entry_count"] == 4
