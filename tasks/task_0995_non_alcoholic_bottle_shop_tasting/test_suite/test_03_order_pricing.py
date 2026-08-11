"""Order pricing: retail/DTC channel divergence, club-discount composition,
per-line rounding, line mutation side effects, and immediate consistency of
computed totals (PRD §3.8, §2.2).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_line,
    assert_order,
    assert_order_line,
    assert_order_totals_reconcile,
    create_draft_order,
    fresh_order_version,
    get_order,
    get_sku,
    make_category,
    make_lot,
    make_member,
    make_member_headers,
    make_shipping_rule,
    make_sku,
    set_clock,
    setup_submitted_order,
    submit_order_fresh,
    subscribe_member,
    make_club_plan,
    validate_success,
)

STAFF = TEST_USERS["shop_staff_headers"]


def _setup_retail_and_dtc_orders(api):
    """Shared setup: one SKU @ 1000 cents, CA rule (tax 1000 bps), WA rule
    (surcharge 300, tax 500 bps); a RETAIL and a DTC-to-WA order, each with
    2 units, both submitted. Returns (retail_order, dtc_order, member)."""
    set_clock()
    category = make_category(code="sparkling-tea", display_name="Sparkling Tea")
    sku = make_sku(category["id"], sku_code="tea-001", base_price_cents=1000)
    make_lot(sku["id"], lot_code="L1", qty_received=100, expires_on="2027-01-01")
    member = make_member(email="m1@x.com")
    make_shipping_rule(state_code="CA", tax_rate_bps=1000)
    make_shipping_rule(state_code="WA", surcharge_cents_per_order=300,
                       tax_rate_bps=500)
    retail = create_draft_order(member["id"], channel="RETAIL")
    add_line(retail["id"], member["id"], sku["id"], qty=2)
    retail = validate_success(submit_order_fresh(retail["id"], member["id"]), 200)
    dtc = create_draft_order(member["id"], channel="DTC", ship_to_state_code="WA")
    add_line(dtc["id"], member["id"], sku["id"], qty=2)
    dtc = validate_success(submit_order_fresh(dtc["id"], member["id"]), 200)
    return retail, dtc, member


class TestRetailVsDtcDivergence:
    def test_retail_order_has_zero_shipping_and_home_state_tax(self, api):
        """PRD §3.8: "Shipping applies only to `DTC` orders. The shipping
        charge has three components summed together: a flat base of 500 cents,
        plus 150 cents per bottle where the bottle count is the sum of `qty`
        across all lines, plus the destination state's
        `surcharge_cents_per_order`. Because an order must have at least one
        line with `qty` at least 1, the bottle count is always at least one
        and the surcharge always applies. For `RETAIL` orders the shipping
        charge is zero."
        PRD §3.8: "For `RETAIL` orders, the destination-state rule used for
        tax is the shop's home state rule — for the purposes of this
        specification the shop is pinned to California, so retail orders tax
        at the California rate."

        Design: Difficulty/dual_variant_calc/order_total_retail_vs_dtc_divergence
        """
        retail, _dtc, member = _setup_retail_and_dtc_orders(api)
        retail = get_order(retail["id"], make_member_headers(member["id"]))
        assert_order(retail)
        # subtotal = 1000 * 2 = 2000; shipping 0; tax = 2000 * 1000/10000 = 200
        assert retail["subtotal_cents"] == 2000
        assert retail["shipping_charge_cents"] == 0, (
            "RETAIL shipping charge must be zero"
        )
        assert retail["tax_cents"] == 200
        assert retail["grand_total_cents"] == 2200
        assert_order_totals_reconcile(retail)

    def test_dtc_order_has_shipping_and_destination_state_tax(self, api):
        """PRD §3.8: "Shipping applies only to `DTC` orders. The shipping
        charge has three components summed together: a flat base of 500 cents,
        plus 150 cents per bottle where the bottle count is the sum of `qty`
        across all lines, plus the destination state's
        `surcharge_cents_per_order`."
        PRD §3.8: "For `DTC` orders the tax rate comes from the destination
        state's rule."
        PRD §3.8: "The grand total is then `subtotal_cents` minus
        `discount_cents` plus `shipping_charge_cents` plus `tax_cents`."

        Design: Difficulty/dual_variant_calc/order_total_retail_vs_dtc_divergence
        """
        retail, dtc, member = _setup_retail_and_dtc_orders(api)
        dtc = get_order(dtc["id"], make_member_headers(member["id"]))
        retail = get_order(retail["id"], make_member_headers(member["id"]))
        assert_order(dtc)
        # subtotal = 2000; shipping = 500 + 150*2 + 300 = 1100
        # taxable = 3100; tax = round_half_up(3100 * 500/10000) = 155
        assert dtc["subtotal_cents"] == 2000
        assert dtc["shipping_charge_cents"] == 1100
        assert dtc["tax_cents"] == 155
        assert dtc["grand_total_cents"] == 3255
        assert_order_totals_reconcile(dtc)
        assert retail["grand_total_cents"] != dtc["grand_total_cents"], (
            "identical lines must price differently across the two channel variants"
        )


def _setup_club_dtc_order(api, sku_specs, discount_bps, plan_code="PLAN-A"):
    """Member with an ACTIVE club subscription (trial_days=0) places a DTC
    order to CA (surcharge 200, tax 800 bps) carrying the given
    [(sku_price, qty)] lines. Returns the submitted order."""
    set_clock()
    category = make_category(code="tea3", display_name="Tea 3")
    skus = []
    for i, (price, qty) in enumerate(sku_specs):
        sku = make_sku(category["id"], sku_code=f"sku-{plan_code.lower()}-{i}",
                       base_price_cents=price)
        make_lot(sku["id"], qty_received=50)
        skus.append((sku, qty))
    member = make_member(email="m3@x.com")
    plan = make_club_plan(code=plan_code, allowed_category_ids=[category["id"]],
                          discount_bps_on_retail=discount_bps)
    subscription = subscribe_member(plan["id"], member["id"])
    make_shipping_rule(state_code="CA", surcharge_cents_per_order=200,
                       tax_rate_bps=800)
    order = create_draft_order(
        member["id"], channel="DTC", ship_to_state_code="CA",
        applied_club_subscription_id=subscription["id"],
    )
    for sku, qty in skus:
        add_line(order["id"], member["id"], sku["id"], qty=qty)
    return validate_success(submit_order_fresh(order["id"], member["id"]), 200)


class TestClubDiscountComposition:
    def test_club_discount_subtotal_per_line(self, api):
        """PRD §3.8: "If the order has an `applied_club_subscription_id`
        (which must reference a currently `ACTIVE` subscription), the line's
        `unit_price_cents` is the list price multiplied by the quantity (10000
        minus the plan's `discount_bps_on_retail`) and divided by 10000,
        rounded half-up to a whole cent. Otherwise the `unit_price_cents`
        equals the list price unchanged. The line's `extended_price_cents` is
        `unit_price_cents` multiplied by `qty`. The order's `subtotal_cents`
        is the sum of `extended_price_cents` across all lines — per-line
        rounding wins, and no cross-line reallocation is performed."

        Design: Difficulty/combinatorial_formula/order_total_mode_a_nested_min_max
        """
        # 10% club discount: line A unit = round(1000*9000/10000) = 900,
        # extended 900*3 = 2700; line B unit = round(500*0.9) = 450, ext 900.
        order = _setup_club_dtc_order(api, [(1000, 3), (500, 2)], 1000)
        assert order["subtotal_cents"] == 3600

    def test_club_discount_shipping_tax_grand_total(self, api):
        """PRD §3.8: "Shipping applies only to `DTC` orders. The shipping
        charge has three components summed together: a flat base of 500 cents,
        plus 150 cents per bottle where the bottle count is the sum of `qty`
        across all lines, plus the destination state's
        `surcharge_cents_per_order`."
        PRD §3.8: "The taxable base is `subtotal_cents` minus the
        loyalty-discount cents plus the shipping charge. The tax amount is
        this taxable base multiplied by the destination state's `tax_rate_bps`
        and divided by 10000, rounded half-up to a whole cent."
        PRD §3.8: "The grand total is then `subtotal_cents` minus
        `discount_cents` plus `shipping_charge_cents` plus `tax_cents`."

        Design: Difficulty/combinatorial_formula/order_total_mode_a_nested_min_max
        """
        # bottles = 5; shipping = 500 + 150*5 + 200 = 1450
        # taxable = 3600 + 1450 = 5050; tax = round(5050 * 800/10000) = 404
        order = _setup_club_dtc_order(api, [(1000, 3), (500, 2)], 1000)
        assert order["shipping_charge_cents"] == 1450
        assert order["tax_cents"] == 404
        assert order["grand_total_cents"] == 5454
        assert_order_totals_reconcile(order)


class TestPerLineRounding:
    def _rounding_order(self, api):
        """33.33% club discount on a 299-cent SKU, qty 3, RETAIL with a
        zero-tax CA rule to isolate the rounding behavior."""
        set_clock()
        category = make_category(code="tea4", display_name="Tea 4")
        sku = make_sku(category["id"], sku_code="sku-r", base_price_cents=299)
        make_lot(sku["id"], lot_code="LR", qty_received=100)
        member = make_member(email="m4@x.com")
        plan = make_club_plan(code="PLAN-B", bottles_per_shipment=1,
                              price_cents_per_cycle=1000,
                              allowed_category_ids=[category["id"]],
                              discount_bps_on_retail=3333)
        subscription = subscribe_member(plan["id"], member["id"])
        make_shipping_rule(state_code="CA", allows_dtc=False, tax_rate_bps=0)
        order = create_draft_order(
            member["id"], channel="RETAIL",
            applied_club_subscription_id=subscription["id"],
        )
        add_line(order["id"], member["id"], sku["id"], qty=3)
        return validate_success(submit_order_fresh(order["id"], member["id"]), 200)

    def test_per_line_rounding_subtotal(self, api):
        """PRD §3.8: "If the order has an `applied_club_subscription_id`
        (which must reference a currently `ACTIVE` subscription), the line's
        `unit_price_cents` is the list price multiplied by the quantity (10000
        minus the plan's `discount_bps_on_retail`) and divided by 10000,
        rounded half-up to a whole cent."
        PRD §3.8: "The order's `subtotal_cents` is the sum of
        `extended_price_cents` across all lines — per-line rounding wins, and
        no cross-line reallocation is performed."

        Design: Difficulty/combinatorial_formula/per_line_rounding_vs_sum_then_round_mode_b
        """
        # unit = round_half_up(299 * 6667 / 10000) = round_half_up(199.3433) = 199
        # extended = 199 * 3 = 597; sum-then-round would give 598.
        order = self._rounding_order(api)
        assert order["subtotal_cents"] == 597, (
            "per-line rounding must win over sum-then-round"
        )
        assert order["subtotal_cents"] != 598

    def test_per_line_rounding_grand_total(self, api):
        """PRD §3.8: "This is an explicit design choice: the sum of
        per-line-rounded extended prices must equal the order's
        `subtotal_cents` exactly."
        PRD §3.8: "The grand total is then `subtotal_cents` minus
        `discount_cents` plus `shipping_charge_cents` plus `tax_cents`."
        PRD §3.8: "A state whose `tax_rate_bps` is zero produces a tax of
        zero."

        Design: Difficulty/combinatorial_formula/per_line_rounding_vs_sum_then_round_mode_b
        """
        # RETAIL: shipping 0; CA rule tax_rate_bps 0 -> tax 0; no redemption.
        order = self._rounding_order(api)
        assert order["grand_total_cents"] == 597
        assert_order_totals_reconcile(order)


class TestOrderLineComputation:
    def test_order_line_unit_and_extended_price_computed(self, api):
        """PRD §3.8: "Each `OrderLine` references the order via `order_id`
        and the SKU via `sku_id`, and carries a `qty` (at least 1), a
        `unit_price_cents` locked at creation, an `extended_price_cents`
        computed as the per-line rounded multiplication, and a
        `lot_allocation` list (empty until the order is submitted)."
        PRD §3.8: "Otherwise the `unit_price_cents` equals the list price
        unchanged. The line's `extended_price_cents` is `unit_price_cents`
        multiplied by `qty`."

        Design: Corner/entities/order_line_computed_unit_price_ignores_input
        """
        set_clock()
        category = make_category(code="cc", display_name="CC")
        sku = make_sku(category["id"], sku_code="sc2", base_price_cents=700)
        make_lot(sku["id"], qty_received=10)
        member = make_member(email="mcc@x.com")
        order = create_draft_order(member["id"], channel="RETAIL")
        line = validate_success(
            api.add_order_line(
                order["id"], {"sku_id": sku["id"], "qty": 2},
                make_member_headers(member["id"]),
            ),
            201,
        )
        assert_order_line(line)
        assert line["unit_price_cents"] == 700
        assert line["extended_price_cents"] == 1400
        assert line["lot_allocation"] == []

    def test_submit_response_carries_computed_totals(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify
        a resource will return the created or updated resource object in the
        data field."
        PRD §3.8: "Successful submission transitions the order from `DRAFT` to
        `PICKING` on the fulfillment axis, sets `payment_status` to
        `AUTHORIZED`, runs the lot-allocation walk to populate each line's
        `lot_allocation` (decrementing `InventoryLot.qty_remaining` and
        recomputing `on_hand_cached` for affected SKUs), recomputes the
        order's totals, and bumps the order's `version` by one."

        Design: Corner/consistency_model/order_totals_visible_in_submit_response
        """
        set_clock()
        category = make_category(code="cic", display_name="CIC")
        sku = make_sku(category["id"], sku_code="sic", base_price_cents=1000)
        make_lot(sku["id"], qty_received=5)
        member = make_member(email="mic@x.com")
        make_shipping_rule(state_code="CA", tax_rate_bps=0)
        order = create_draft_order(member["id"], channel="RETAIL")
        add_line(order["id"], member["id"], sku["id"], qty=1)
        submitted = validate_success(
            submit_order_fresh(order["id"], member["id"]), 200
        )
        assert_order(submitted)
        assert submitted["subtotal_cents"] == 1000
        assert submitted["grand_total_cents"] == 1000
        assert submitted["fulfillment_status"] == "PICKING"
        assert submitted["payment_status"] == "AUTHORIZED"

    def test_line_delete_recomputes_subtotal(self, api):
        """PRD §3.8: "Adding or removing a line recomputes the order's
        `subtotal_cents` and bumps the order's `version` by one."
        PRD §4: "deletions are returned with HTTP 204."

        Design: Corner/endpoints/order_lines_deleted_recomputes_subtotal
        """
        set_clock()
        category = make_category(code="cdel", display_name="CDEL")
        s1 = make_sku(category["id"], sku_code="sdel1", base_price_cents=100)
        s2 = make_sku(category["id"], sku_code="sdel2", base_price_cents=200)
        make_lot(s1["id"], qty_received=10)
        make_lot(s2["id"], qty_received=10)
        member = make_member(email="mdel@x.com")
        order = create_draft_order(member["id"], channel="RETAIL")
        line1 = add_line(order["id"], member["id"], s1["id"], qty=2)
        add_line(order["id"], member["id"], s2["id"], qty=3)
        before = get_order(order["id"], make_member_headers(member["id"]))
        assert before["subtotal_cents"] == 100 * 2 + 200 * 3
        resp = api.delete_order_line(
            order["id"], line1["id"], make_member_headers(member["id"])
        )
        assert resp.status_code == 204, (
            f"line deletion must return 204, got {resp.status_code}: {resp.text}"
        )
        after = get_order(order["id"], make_member_headers(member["id"]))
        assert after["subtotal_cents"] == 600
        assert after["version"] == before["version"] + 1

    def test_draft_line_delete_leaves_inventory_untouched(self, api):
        """PRD §3.8: "Each `OrderLine` references the order via `order_id`
        and the SKU via `sku_id`, and carries a `qty` (at least 1), a
        `unit_price_cents` locked at creation, an `extended_price_cents`
        computed as the per-line rounded multiplication, and a
        `lot_allocation` list (empty until the order is submitted)."
        PRD §3.1: "The cache is recomputed every time any lot under the SKU
        is inserted, updated, or deleted."

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_on_hand_after_line_delete
        """
        set_clock()
        category = make_category(code="cdr", display_name="CDR")
        sku = make_sku(category["id"], sku_code="sdr", base_price_cents=100)
        make_lot(sku["id"], qty_received=10)
        member = make_member(email="mdr@x.com")
        order = create_draft_order(member["id"], channel="RETAIL")
        line = add_line(order["id"], member["id"], sku["id"], qty=3)
        assert get_sku(sku["id"])["on_hand_cached"] == 10
        resp = api.delete_order_line(
            order["id"], line["id"], make_member_headers(member["id"])
        )
        assert resp.status_code == 204
        # DRAFT lines never allocated inventory, so deletion cannot restore it.
        assert get_sku(sku["id"])["on_hand_cached"] == 10
