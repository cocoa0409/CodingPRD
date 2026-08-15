"""Order drafting, listing, and the pinned pricing pipeline: per-line
rounding, rollup evaluation order, delivery-minimum boundary, fuel surcharge
variants, and effective unit price from contract bids."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_order,
    create_facility,
    create_order_draft,
    create_order_payload,
    create_product,
    deliver_order,
    get_order_lines,
    make_facility_manager_headers,
    order_line,
    place_order,
    setup_awarded_bid,
    setup_facility_with_product,
    setup_placed_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["distributor_admin_headers"]
MISSING_UUID = "00000000-0000-4000-8000-000000000000"


class TestOrderDrafting:
    def test_new_order_initial_state_draft(self, api):
        """PRD: "The order is born `DRAFT` with `source` `MANUAL`, a null
        `standing_order_id`, `trial_credit_cents` of zero, and its lines born
        `PENDING`."
        PRD: "The `committed_cents` counter is the sum of `total_cents` over
        all of the facility's orders whose status is `PLACED`,
        `PARTIALLY_BLOCKED`, or `DELIVERED`, computed over all time with no
        window."

        Design: Corner/state_machines/new_order_initial_state_draft
        """
        facility, product = setup_facility_with_product(facility_name="Fac U")
        order = create_order_draft(facility, [order_line(product["id"], 1)])
        assert_order(order)
        assert order["status"] == "DRAFT"
        assert order["source"] == "MANUAL"
        refreshed = validate_success(api.get_facility(facility["id"], ADMIN))
        assert refreshed["committed_cents"] == 0, (
            "DRAFT orders do not commit credit")

    def test_create_order_computed_fields_input_ignored(self, api):
        """PRD: "A manual order is drafted by a `FacilityManager` (for their
        facility) or a `DistributorAdmin` supplying the `facility_id`, the
        `lines` array (each entry naming a `product_id`, a `qty` of at least
        one, and an optional `discount_pct` expressed as a fraction between 0
        and 1, defaulting to 0), the requested `delivery_date`, and the
        `fuel_index` — the diesel index quoted at placement, which becomes the
        basis of the quoted fuel surcharge."
        PRD: "The order is born `DRAFT` with `source` `MANUAL`, a null
        `standing_order_id`, `trial_credit_cents` of zero, and its lines born
        `PENDING`."

        Design: Corner/entities/create_order_computed_fields_input_ignored
        """
        facility, product = setup_facility_with_product(facility_name="Fac R")
        payload = create_order_payload(
            facility["id"], [order_line(product["id"], 1)])
        payload["merchandise_subtotal_cents"] = 999999
        payload["total_cents"] = 1
        resp = api.create_order(payload, make_facility_manager_headers(
            facility["id"]))
        order = validate_success(resp, 201)
        assert order["status"] == "DRAFT"
        assert order.get("total_cents") != 1, (
            "Client-supplied total_cents is ignored")
        assert order.get("merchandise_subtotal_cents") != 999999, (
            "Client-supplied merchandise_subtotal_cents is ignored")

    def test_create_order_with_unknown_product_returns_not_found(self, api):
        """PRD: "identifiers referenced in the request body (for example, a
        payload carrying a `facility_id` and a `product_id`) must likewise
        refer to existing resources. The first identifier that does not
        correspond to an existing resource produces an `ERR_NOT_FOUND`
        rejection"

        Design: Corner/entities/create_order_with_unknown_product_returns_not_found
        """
        facility = create_facility(name="Fac T")
        payload = create_order_payload(
            facility["id"], [order_line(MISSING_UUID, 1)])
        resp = api.create_order(
            payload, make_facility_manager_headers(facility["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_list_orders_pagination_and_filter(self, api):
        """PRD: "The `limit` parameter specifies the maximum number of items to
        return; it defaults to 10, with a minimum of 1 and a maximum of 100.
        The `offset` parameter specifies how many items to skip and defaults
        to 0."
        PRD: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."
        PRD: "the order list accepts `facility_id`, `standing_order_id`, and
        `status` filters"

        Design: Corner/entities/list_orders_pagination_and_filter
        """
        facility, product = setup_facility_with_product(facility_name="Fac S")
        for day in ("2026-08-05T00:00:00Z", "2026-08-06T00:00:00Z",
                    "2026-08-07T00:00:00Z"):
            create_order_draft(facility, [order_line(product["id"], 1)],
                               delivery_date=day)

        page1, meta1 = validate_paginated(api.list_orders(
            ADMIN, params={"facility_id": facility["id"], "limit": 2,
                           "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(api.list_orders(
            ADMIN, params={"facility_id": facility["id"], "limit": 2,
                           "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestPerLineRounding:
    def test_line_totals_round_per_line_then_sum(self, api):
        """PRD: "Second, order line totals are rounded to integer cents per
        line first, and only then summed into the merchandise subtotal;
        summing unrounded raw values and rounding once at the end is a
        different, non-conformant result."
        PRD: "Each `line_total_cents` is the quantity times the unit price
        times one minus the discount fraction, rounded half up to integer
        cents — per line first, per §2.6 — and `merchandise_subtotal_cents` is
        the sum of those rounded line totals"

        Design: Difficulty/combinatorial_formula/order_line_pricing_per_line_rounding
        """
        facility = create_facility(name="Fac C")
        prod_a = create_product(sku="SKU-PA", name="A", base_price_cents=101,
                                unit_of_measure="EACH")
        prod_b = create_product(sku="SKU-PB", name="B", base_price_cents=103,
                                unit_of_measure="EACH")
        order = create_order_draft(
            facility,
            [order_line(prod_a["id"], 1, 0.5),
             order_line(prod_b["id"], 1, 0.5)])
        placed = place_order(order["id"], facility)
        lines = {line["product_id"]: line
                 for line in get_order_lines(order["id"])}
        assert lines[prod_a["id"]]["line_total_cents"] == 51, (
            "round half up of 1 * 101 * 0.5 = 50.5 -> 51")
        assert lines[prod_b["id"]]["line_total_cents"] == 52, (
            "round half up of 1 * 103 * 0.5 = 51.5 -> 52")
        assert placed["merchandise_subtotal_cents"] == 103, (
            "Per-line-then-sum is 51 + 52 = 103; sum-then-round of raw "
            "values would be 102")

    def test_rollup_after_per_line_rounding(self, api):
        """PRD: "Second, order line totals are rounded to integer cents per
        line first, and only then summed into the merchandise subtotal;
        summing unrounded raw values and rounding once at the end is a
        different, non-conformant result."
        PRD: "then `delivery_fee_cents`, which covers the shortfall between
        the subtotal and the 5,000-cent ($50.00) delivery minimum and is zero
        when the subtotal meets or exceeds it; then `fuel_surcharge_cents`,
        computed on the combined base of subtotal plus delivery fee"

        Design: Difficulty/combinatorial_formula/order_line_pricing_per_line_rounding
        """
        facility = create_facility(name="Fac C")
        prod_a = create_product(sku="SKU-PA", name="A", base_price_cents=101,
                                unit_of_measure="EACH")
        prod_b = create_product(sku="SKU-PB", name="B", base_price_cents=103,
                                unit_of_measure="EACH")
        order = create_order_draft(
            facility,
            [order_line(prod_a["id"], 1, 0.5),
             order_line(prod_b["id"], 1, 0.5)])
        placed = place_order(order["id"], facility)
        assert placed["merchandise_subtotal_cents"] == 103
        assert placed["delivery_fee_cents"] == 4897, "5000 - 103 = 4897"
        assert placed["fuel_surcharge_cents"] == 200, (
            "round half up of (103 + 4897) * 0.04 * 1.0 = 200")
        assert placed["total_cents"] == 5200


class TestRollupEvaluationOrder:
    def test_delivery_fee_covers_shortfall_to_minimum(self, api):
        """PRD: "The rollup then proceeds in a pinned order that breaks the
        fee-versus-surcharge circularity: first the merchandise subtotal; then
        `delivery_fee_cents`, which covers the shortfall between the subtotal
        and the 5,000-cent ($50.00) delivery minimum and is zero when the
        subtotal meets or exceeds it"

        Design: Difficulty/combinatorial_formula/order_total_rollup_pinned_evaluation_order
        """
        _facility, _product, order = setup_placed_order(
            qty=4, base_price_cents=1000, fuel_index=2.50,
            facility_name="Fac D")
        assert order["merchandise_subtotal_cents"] == 4000
        assert order["delivery_fee_cents"] == 1000, "5000 - 4000 = 1000"

    def test_surcharge_base_includes_delivery_fee(self, api):
        """PRD: "then `fuel_surcharge_cents`, computed on the combined base of
        subtotal plus delivery fee as that base times a diesel-index
        percentage — 4 percent when the index is below 3.00, 6 percent when it
        is at least 3.00 but below 4.00, and 9 percent when it is 4.00 or
        higher — times a distance multiplier read from the facility's
        `delivery_distance_miles` — 1.0 under 25 miles, 1.25 at 25 miles or
        more but under 75, and 1.5 at 75 miles or more — with the result
        rounded half up to integer cents; and finally `total_cents`, the
        subtotal plus fee plus surcharge minus `trial_credit_cents`, floored
        at zero."

        Design: Difficulty/combinatorial_formula/order_total_rollup_pinned_evaluation_order
        """
        _facility, _product, order = setup_placed_order(
            qty=4, base_price_cents=1000, fuel_index=2.50,
            facility_name="Fac D")
        assert order["fuel_surcharge_cents"] == 200, (
            "Base is subtotal + fee = 5000, so surcharge is 200; computing "
            "on the subtotal alone would give 160")
        assert order["total_cents"] == 5200


class TestDeliveryMinimumBoundary:
    def test_delivery_fee_zero_at_exact_minimum(self, api):
        """PRD: "then `delivery_fee_cents`, which covers the shortfall between
        the subtotal and the 5,000-cent ($50.00) delivery minimum and is zero
        when the subtotal meets or exceeds it"

        Design: Difficulty/boundary_precision_check/delivery_fee_zero_at_exact_minimum
        """
        _facility, _product, order = setup_placed_order(
            qty=5, base_price_cents=1000, fuel_index=2.50,
            facility_name="Fac J")
        assert order["merchandise_subtotal_cents"] == 5000
        assert order["delivery_fee_cents"] == 0, (
            "At exactly the minimum the fee is zero")
        assert order["fuel_surcharge_cents"] == 200
        assert order["total_cents"] == 5200

    def test_delivery_fee_one_cent_below_minimum(self, api):
        """PRD: "then `delivery_fee_cents`, which covers the shortfall between
        the subtotal and the 5,000-cent ($50.00) delivery minimum and is zero
        when the subtotal meets or exceeds it"

        Design: Difficulty/boundary_precision_check/delivery_fee_zero_at_exact_minimum
        """
        _facility, _product, order = setup_placed_order(
            qty=1, base_price_cents=4999, fuel_index=2.50,
            facility_name="Fac J")
        assert order["merchandise_subtotal_cents"] == 4999
        assert order["delivery_fee_cents"] == 1, "One cent below -> fee 1"
        assert order["fuel_surcharge_cents"] == 200, (
            "Base is 4999 + 1 = 5000")
        assert order["total_cents"] == 5200


class TestFuelSurchargeVariants:
    def test_quoted_surcharge_at_placement(self, api):
        """PRD: "At placement this surcharge is the `QUOTED` variant, computed
        from the order's `fuel_index`, and `fuel_surcharge_variant` reads
        `QUOTED`; `placed_at` is stamped, the order moves `DRAFT → PLACED`,
        and the facility's `committed_cents` rises by `total_cents`."

        Design: Difficulty/dual_variant_calc/fuel_surcharge_quoted_vs_actual
        """
        _facility, _product, order = setup_placed_order(
            qty=5, base_price_cents=1000, fuel_index=2.50,
            facility_name="Fac B")
        assert order["status"] == "PLACED"
        assert order["merchandise_subtotal_cents"] == 5000
        assert order["delivery_fee_cents"] == 0
        assert order["fuel_surcharge_cents"] == 200, (
            "QUOTED at index 2.50: 4 percent of 5000 at 1.0 distance")
        assert order["fuel_surcharge_variant"] == "QUOTED"
        assert order["total_cents"] == 5200

    def test_actual_surcharge_at_confirm_delivery(self, api):
        """PRD: "The surcharge is recomputed under the `ACTUAL` variant from
        that index on the same combined base, `total_cents` is recomputed,
        `fuel_surcharge_variant` flips to `ACTUAL`"
        PRD: "Identical order data therefore yields a different surcharge
        whenever the diesel index moved between quote and delivery."

        Design: Difficulty/dual_variant_calc/fuel_surcharge_quoted_vs_actual
        """
        _facility, _product, order = setup_placed_order(
            qty=5, base_price_cents=1000, fuel_index=2.50,
            facility_name="Fac B")
        delivered = deliver_order(order["id"], fuel_index_at_delivery=3.50)
        assert delivered["status"] == "DELIVERED"
        assert delivered["fuel_surcharge_cents"] == 300, (
            "ACTUAL at index 3.50: 6 percent of 5000 at 1.0 distance")
        assert delivered["fuel_surcharge_variant"] == "ACTUAL"
        assert delivered["total_cents"] == 5300


class TestEffectiveUnitPrice:
    def test_effective_price_uses_awarded_bid_inside_window(self, api):
        """PRD: "The candidate set is every `AWARDED` bid whose
        `facility_group_code` equals the facility's group, whose lines include
        the product, and whose closed protection window covers the current
        clock time."
        PRD: "A non-empty candidate set yields the covering bid's
        `bid_price_cents`; otherwise the product's `base_price_cents`
        applies."

        Design: Corner/calculations/effective_price_uses_awarded_bid_inside_window
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac AD", facility_group_code="GPO-7")
        setup_awarded_bid(product, facility_group_code="GPO-7",
                          bid_price_cents=800,
                          protection_start="2026-07-01T00:00:00Z",
                          protection_end="2026-12-31T00:00:00Z")
        order = create_order_draft(facility, [order_line(product["id"], 5)])
        placed = place_order(order["id"], facility)
        line = get_order_lines(order["id"])[0]
        assert line["unit_price_cents"] == 800, (
            "The covering AWARDED bid's price applies, not base 1000")
        assert placed["merchandise_subtotal_cents"] == 4000
        assert placed["delivery_fee_cents"] == 1000
        assert placed["fuel_surcharge_cents"] == 200
        assert placed["total_cents"] == 5200

    def test_effective_price_outside_window_uses_base(self, api):
        """PRD: "The candidate set is every `AWARDED` bid whose
        `facility_group_code` equals the facility's group, whose lines include
        the product, and whose closed protection window covers the current
        clock time."
        PRD: "A non-empty candidate set yields the covering bid's
        `bid_price_cents`; otherwise the product's `base_price_cents`
        applies."

        Design: Corner/calculations/effective_price_outside_window_uses_base
        """
        facility, product = setup_facility_with_product(
            facility_name="Fac AE", facility_group_code="GPO-8")
        setup_awarded_bid(product, facility_group_code="GPO-8",
                          bid_price_cents=800,
                          protection_start="2026-09-01T00:00:00Z",
                          protection_end="2026-12-31T00:00:00Z")
        order = create_order_draft(facility, [order_line(product["id"], 5)])
        placed = place_order(order["id"], facility)
        line = get_order_lines(order["id"])[0]
        assert line["unit_price_cents"] == 1000, (
            "The window opens 2026-09-01, after the default clock "
            "2026-08-01, so the base price applies")
        assert placed["merchandise_subtotal_cents"] == 5000


class TestImmediateConsistency:
    def test_place_response_reflects_all_mutations_immediately(self, api):
        """PRD: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the
        data field."
        PRD: "Both counters start at zero and are recomputed — or adjusted by
        the exact delta — on every order event that moves money: placement
        adds the new order's total to `committed_cents`"

        Design: Corner/consistency_model/place_response_reflects_all_mutations_immediately
        """
        facility, product = setup_facility_with_product(facility_name="Fac CD")
        order = create_order_draft(facility, [order_line(product["id"], 5)])
        resp = api.place_order(
            order["id"], make_facility_manager_headers(facility["id"]))
        placed = validate_success(resp, 200)
        assert placed["status"] == "PLACED", (
            "The place response body itself carries the new status")
        assert placed["total_cents"] == 5200, (
            "The place response body itself carries the computed total")
        refreshed = validate_success(api.get_facility(facility["id"], ADMIN))
        assert refreshed["committed_cents"] == 5200, (
            "The ledger read after place shows the commitment with no lag")
