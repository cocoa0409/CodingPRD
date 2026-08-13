"""Order pricing stack (break -> surcharge -> pallet), freight classification
boundaries, oversize surcharge tiers, sourcing selection, and promise dates."""
from test_helpers import (
    OPS,
    TEST_USERS,
    add_line,
    api_client,
    assert_order,
    assert_order_line,
    create_account,
    create_custom_product,
    create_draft_order,
    create_inventory,
    create_quantity_break_payload,
    create_stock_product,
    create_warehouse,
    date_component,
    get_success_data,
    make_buyer_headers,
    set_clock,
    setup_custom_order_with_job,
    setup_submitted_stock_order,
    setup_warehouse_and_account,
    validate_success,
)

CATALOG = TEST_USERS["catalog_manager_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def _add_break(product_id, **overrides):
    return validate_success(api_client.create_quantity_break(
        product_id, create_quantity_break_payload(**overrides), CATALOG), expected_status=201)


class TestBreakSurchargePalletStacking:
    """Custom product base 500 with breaks 50 -> 450 and 200 -> 400; the
    200-unit line resolves unit 400, surcharge ceil(400 x 1.15) = 460,
    4 pallets x floor(460 x 0.03) = 52."""

    def _setup(self, api):
        wh, acct = setup_warehouse_and_account()
        prod = create_custom_product(sku="BX-C2", name="Custom Mailer", category="MAILERS",
                                     base_price_cents=500, lead_time_days=3, pallet_qty=50,
                                     weight_lbs_per_unit=2)
        _add_break(prod["id"], min_qty=50, unit_price_cents=450, sort_seq=1)
        _add_break(prod["id"], min_qty=200, unit_price_cents=400, sort_seq=2)
        set_clock("2026-08-03T10:00:00Z")
        order = create_draft_order(acct["id"], ship_zone=5)
        line = add_line(order["id"], acct["id"], prod["id"], 200,
                        print_artwork_ref="art-9", over_under_tolerance_pct=10)
        return wh, acct, prod, order, line

    def test_break_then_surcharge_then_pallet_pricing(self, api):
        """PRD section 3.4: "Pricing is resolved per line, always in the pinned
        order — quantity break first, custom-print surcharge second, pallet
        incentive third"
        PRD section 3.4: "For a custom-print product the resolved unit price is
        then uplifted by fifteen percent, rounding up to the next cent per
        unit."
        PRD section 3.2: "The selected break's price is a flat per-unit price
        for the entire line, never a marginal per-tier rate, and it may
        legitimately exceed the base price for a premium pack."

        Design: Difficulty/combinatorial_formula/break_surcharge_pallet_stacking_multi_input
        """
        wh, acct, prod, order, line = self._setup(api)
        # Unit price is resolved already at line add: break 400, then ceil(400 x 1.15).
        assert line["unit_price_cents"] == 460

        submitted = validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))
        assert_order(submitted)
        assert submitted["subtotal_cents"] == 92000          # 460 x 200
        assert submitted["pallet_discount_cents"] == 52      # 4 pallets x floor(460 x 0.03) = 4 x 13

    def test_stacked_order_freight_grand_total_and_status(self, api, platform_admin_headers):
        """PRD section 3.7: "the per-pound rate is: class `50` at $0.90, class
        `55` at $1.05, classes `60` through `92.5` at $1.20, classes `100`
        through `125` at $1.45, classes `150` through `200` at $1.75, and
        classes `250` and above at $2.10."
        PRD section 3.7: "The zone factor is one plus twelve hundredths times
        the zone distance minus one, where the zone distance is the absolute
        difference between the order's `ship_zone` and the `zone` of the
        warehouse shipping the majority of the order, and is always at least
        one."
        PRD section 3.4: "the order's `grand_total_cents` is the subtotal minus
        the pallet discount plus `oversize_surcharge_cents` plus
        `freight_estimate_cents`."
        PRD section 3.4: "any custom line puts the order in `CUSTOM_PRODUCTION`"

        Design: Difficulty/combinatorial_formula/break_surcharge_pallet_stacking_multi_input
        """
        wh, acct, prod, order, line = self._setup(api)
        submitted = validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))
        # 400 lbs at class 70 ($1.20/lb), zone distance 3 -> factor 1.24,
        # provisional uplift 1.10: ceil(400 x 120 x 1.24 x 1.10) = 65472.
        assert submitted["freight_estimate_cents"] == 65472
        assert submitted["oversize_surcharge_cents"] == 0
        assert submitted["grand_total_cents"] == 157420      # 92000 - 52 + 0 + 65472
        assert submitted["status"] == "CUSTOM_PRODUCTION"

        fetched = validate_success(api.get_order_line(line["id"], platform_admin_headers))
        assert_order_line(fetched)
        assert fetched["freight_class"] == "70"


class TestFreightClassBoundaries:
    def test_density_exact_table_bounds_resolve_to_upper_interval(self, api, platform_admin_headers):
        """PRD section 2.10: "Worked boundary pins: a density of exactly 15.0
        resolves to class `85`; 15.0001 resolves to `77.5`; exactly 50.0
        resolves to `55`; exactly 8.0 resolves to `150`; exactly 1.0 resolves
        to `500`."
        PRD section 2.10: "The resolved class is stored on the line as the
        string field `freight_class` (values such as `50`, `65`, up to `500`)."

        Design: Corner/calculations/freight_class_density_exact_boundaries
        """
        wh, acct = setup_warehouse_and_account()
        p1 = create_stock_product(sku="J-1", category="CUSHIONING", base_price_cents=100,
                                  pallet_qty=10, weight_lbs_per_unit=1, density_pcf=15.0)
        p2 = create_stock_product(sku="J-2", category="CUSHIONING", base_price_cents=100,
                                  pallet_qty=10, weight_lbs_per_unit=1, density_pcf=15.0001)
        p3 = create_stock_product(sku="J-3", category="CUSHIONING", base_price_cents=100,
                                  pallet_qty=10, weight_lbs_per_unit=1, density_pcf=1.0)
        for p in (p1, p2, p3):
            create_inventory(p["id"], wh["id"], 10)
        set_clock("2026-08-03T10:00:00Z")
        order = create_draft_order(acct["id"], ship_zone=5)
        l1 = add_line(order["id"], acct["id"], p1["id"], 1)
        l2 = add_line(order["id"], acct["id"], p2["id"], 1)
        l3 = add_line(order["id"], acct["id"], p3["id"], 1)
        validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))

        assert validate_success(api.get_order_line(l1["id"], platform_admin_headers))["freight_class"] == "85"
        assert validate_success(api.get_order_line(l2["id"], platform_admin_headers))["freight_class"] == "77.5"
        assert validate_success(api.get_order_line(l3["id"], platform_admin_headers))["freight_class"] == "500"


class TestOversizeSurchargeTiers:
    def test_distance_and_heavy_line_tiers_stack(self, api):
        """PRD section 3.7: "When the order contains oversize lines shipping
        `FREIGHT`, `oversize_surcharge_cents` starts at 8,900 cents, gains
        another 2,500 cents when the zone distance is at least 4, and gains
        another 5,000 cents when any single line's total weight — its quantity
        times `weight_lbs_per_unit` — exceeds 150 pounds; with no oversize
        freight lines the surcharge is zero."
        PRD section 3.7: "the zone distance is the absolute difference between
        the order's `ship_zone` and the `zone` of the warehouse shipping the
        majority of the order, and is always at least one."

        Design: Corner/calculations/oversize_surcharge_distance_and_heavy_line_tiers
        """
        wh_atl = create_warehouse(code="ATL", zone=2)
        wh_rno = create_warehouse(code="RNO", name="Reno DC", zone=7,
                                  ship_cutoff_time="14:00", timezone="America/Los_Angeles")
        acct = create_account()
        prod = create_stock_product(sku="PL-9", name="Oversize Crate", base_price_cents=5000,
                                    pallet_qty=10, weight_lbs_per_unit=100, density_pcf=12,
                                    oversize=True)
        create_inventory(prod["id"], wh_atl["id"], 50)
        create_inventory(prod["id"], wh_rno["id"], 50)
        set_clock("2026-08-03T10:00:00Z")

        # Order A: ship_zone 5, qty 1. Both warehouses cover; nearest is RNO
        # (distance 2 < 4) and 100 lbs is not heavy -> base tier only.
        order_a = create_draft_order(acct["id"], ship_zone=5)
        add_line(order_a["id"], acct["id"], prod["id"], 1)
        sub_a = validate_success(api.submit_order(order_a["id"], make_buyer_headers(acct["id"])))
        assert sub_a["oversize_surcharge_cents"] == 8900

        # Order B: ship_zone 3, qty 2 pinned to RNO -> distance |3-7| = 4
        # (+2500) and 200 lbs > 150 (+5000).
        order_b = create_draft_order(acct["id"], ship_zone=3)
        add_line(order_b["id"], acct["id"], prod["id"], 2, requested_warehouse_code="RNO")
        sub_b = validate_success(api.submit_order(order_b["id"], make_buyer_headers(acct["id"])))
        assert sub_b["oversize_surcharge_cents"] == 16400


class TestCustomLeadTimePromise:
    def test_friday_submit_plus_three_business_days_skips_weekend(self, api):
        """PRD section 3.4: "A custom-print line overrides the stock promise
        whenever its lead-time projection — the product's `lead_time_days`
        business days after the submit date, counting the submit day as day
        zero and skipping weekends — lands later."

        Design: Corner/calculations/custom_lead_time_business_day_projection
        """
        ctx = setup_custom_order_with_job(qty=5, lead_time_days=3, sku="K-1",
                                          category="LABELS", base_price_cents=100,
                                          pallet_qty=10, weight_lbs_per_unit=1,
                                          clock="2026-08-07T10:00:00Z", artwork="art-k")
        # Friday 2026-08-07 + 3 business days (Mon 10th, Tue 11th, Wed 12th).
        assert date_component(ctx["order"]["promised_ship_date"]) == "2026-08-12"


class TestSourcingSelector:
    def test_cover_first_then_nearest_zone_then_requested_override(self, api):
        """PRD section 3.4: "the deterministic sourcing selector builds a
        candidate set: warehouses that are `ACTIVE`, that match the line's
        `requested_warehouse_code` when one was given, that are
        oversize-capable when the product is oversize, and that hold an
        inventory row for the product."
        PRD section 3.4: "Candidates are ranked by full cover first — those
        whose `available_qty` reaches the line quantity outrank those that fall
        short — then by nearest zone, the absolute difference between the
        order's `ship_zone` and the warehouse's `zone`, ascending; then by
        preference for the account's `default_warehouse_code`; and finally by
        warehouse `code` ascending as the deterministic tie-break."

        Design: Corner/calculations/selector_zone_distance_and_requested_warehouse
        """
        wh_atl = create_warehouse(code="ATL", zone=2)
        wh_rno = create_warehouse(code="RNO", name="Reno DC", zone=7,
                                  ship_cutoff_time="14:00", timezone="America/Los_Angeles")
        acct = create_account()
        prod = create_stock_product(sku="L-1", base_price_cents=100, pallet_qty=10,
                                    weight_lbs_per_unit=1)
        create_inventory(prod["id"], wh_atl["id"], 100)
        create_inventory(prod["id"], wh_rno["id"], 100)
        set_clock("2026-08-03T10:00:00Z")

        order = create_draft_order(acct["id"], ship_zone=4)
        plain = add_line(order["id"], acct["id"], prod["id"], 1)
        pinned = add_line(order["id"], acct["id"], prod["id"], 1,
                          requested_warehouse_code="RNO")
        validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))

        plain_after = get_success_data(api.get_order_line(plain["id"], ADMIN))
        pinned_after = get_success_data(api.get_order_line(pinned["id"], ADMIN))
        # Distances from ship_zone 4: ATL 2 beats RNO 3 on the plain line.
        assert plain_after["allocated_warehouse_id"] == wh_atl["id"]
        # The explicit request pins the candidate set to RNO.
        assert pinned_after["allocated_warehouse_id"] == wh_rno["id"]


class TestSameDayCutoffBoundary:
    """Warehouse ATL cutoff 15:00 America/New_York (UTC-4 in August)."""

    def _setup(self, api):
        wh, acct = setup_warehouse_and_account()
        prod = create_stock_product(sku="BX-100")
        create_inventory(prod["id"], wh["id"], 100)
        return wh, acct, prod

    def test_submit_one_minute_before_cutoff_promises_same_day(self, api):
        """PRD section 3.4: "For stock lines, the clock reading is rendered in
        the selected warehouse's `timezone`; if the local time-of-day is
        strictly earlier than that facility's `ship_cutoff_time`, the promise
        is that same calendar date, otherwise it is the next business day."

        Design: Difficulty/boundary_precision_check/cutoff_exact_equality_rolls_to_next_day
        """
        wh, acct, prod = self._setup(api)
        order = create_draft_order(acct["id"], ship_zone=5)
        add_line(order["id"], acct["id"], prod["id"], 1)
        set_clock("2026-08-03T18:59:00Z")  # 14:59 local, strictly before 15:00
        submitted = validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))
        assert date_component(submitted["promised_ship_date"]) == "2026-08-03"

    def test_submit_exactly_at_cutoff_rolls_to_next_business_day(self, api):
        """PRD section 3.4: "For stock lines, the clock reading is rendered in
        the selected warehouse's `timezone`; if the local time-of-day is
        strictly earlier than that facility's `ship_cutoff_time`, the promise
        is that same calendar date, otherwise it is the next business day."

        Design: Difficulty/boundary_precision_check/cutoff_exact_equality_rolls_to_next_day
        """
        wh, acct, prod = self._setup(api)
        order = create_draft_order(acct["id"], ship_zone=5)
        add_line(order["id"], acct["id"], prod["id"], 1)
        set_clock("2026-08-03T19:00:00Z")  # exactly 15:00 local: NOT strictly earlier
        submitted = validate_success(api.submit_order(order["id"], make_buyer_headers(acct["id"])))
        # Tuesday 2026-08-04 is the next business day.
        assert date_component(submitted["promised_ship_date"]) == "2026-08-04"
