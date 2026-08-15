"""Submission pricing, promotion resolution, and the minimum-order floor."""
from test_helpers import (
    ADMIN,
    PLANNER,
    ApiErrorId,
    activate_planogram,
    confirm_order,
    create_draft_planogram,
    create_location,
    create_operator,
    create_order,
    create_product,
    create_promotion,
    create_route,
    deliver_order,
    find_order_line,
    get_order,
    make_operator_manager_headers,
    setup_selling_location,
    submit_order,
    validate_error,
    validate_success,
)

PROMO_START = "2026-07-01T00:00:00Z"
PROMO_END = "2026-09-01T00:00:00Z"


def _rounding_world(api):
    """Two products at 995 base, each with a global EXCLUSIVE 10% promotion."""
    world = setup_selling_location(
        products_spec=[
            {"sku": "RND-A", "name": "Round A", "case_pack_qty": 1,
             "base_price_cents": 995, "cost_cents": 500},
            {"sku": "RND-B", "name": "Round B", "case_pack_qty": 1,
             "base_price_cents": 995, "cost_cents": 500},
        ],
        slots_spec=[
            {"slot_code": "A1", "product_index": 0, "par_level_units": 10,
             "vend_price_cents": 200},
            {"slot_code": "A2", "product_index": 1, "par_level_units": 10,
             "vend_price_cents": 200},
        ],
        route_code="R-RND",
    )
    for product in world["products"]:
        create_promotion(product["id"], "PERCENT_OFF", 10,
                         PROMO_START, PROMO_END, "EXCLUSIVE")
    order = create_order(
        world,
        [
            {"product_id": world["products"][0]["id"], "quantity_cases": 1},
            {"product_id": world["products"][1]["id"], "quantity_cases": 1},
        ],
    )
    return world, order


class TestPinnedPerLineRounding:
    def test_per_line_rounding_totals(self, api):
        """PRD §3.5: "The alternative of summing raw discounts and rounding
        once is explicitly not used: consider two lines at a 995-cent base with
        10 percent off — per-line rounding prices each line at 895 cents, a
        200-cent total discount and a 1790-cent order total, where the rejected
        alternative would produce 199 and 1791."

        Design: Difficulty/combinatorial_formula/order_pricing_per_line_rounding_pinned
        """
        world, order = _rounding_world(api)
        submitted = submit_order(world, order["id"])
        assert submitted["order_total_cents"] == 1790
        assert submitted["promo_discount_cents"] == 200, (
            "per-line round_half_up(995*10/100)=100 summed, not round-once 199"
        )
        assert submitted["fulfillment_status"] == "SUBMITTED"

    def test_per_line_pinned_unit_prices(self, api):
        """PRD §3.5: "Pricing computes at submission using the pinned rounding
        order of §2.6: round per line per case, then sum." and "the pinned
        `unit_price_cents` is the product's `base_price_cents` minus that
        discount, floored at zero; the pinned `line_total_cents` is the unit
        price times `quantity_cases`, in exact integer arithmetic."

        Design: Difficulty/combinatorial_formula/order_pricing_per_line_rounding_pinned
        """
        world, order = _rounding_world(api)
        submit_order(world, order["id"])
        reread = get_order(order["id"])
        for product in world["products"]:
            line = find_order_line(reread, product["id"])
            # round_half_up(995 * 10 / 100) == 100 discount -> 895 pinned.
            assert line["unit_price_cents"] == 895
            assert line["line_total_cents"] == 895


class TestPromotionResolution:
    def test_promo_exclusive_overrides_stackable(self, api):
        """PRD §3.5: "If any eligible promotion is `EXCLUSIVE`, the single
        `EXCLUSIVE` promotion with the largest effective value wins alone —
        ties break toward the earliest `created_at`, never toward an identifier
        — and all `STACKABLE` promotions are ignored."

        Design: Corner/calculations/promo_exclusive_overrides_stackable
        """
        world = setup_selling_location(
            products_spec=[{"sku": "EXC-1", "name": "Excl item",
                            "case_pack_qty": 1, "base_price_cents": 1000}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 10, "vend_price_cents": 200}],
            route_code="R-EXC",
        )
        product = world["products"][0]
        create_promotion(product["id"], "PERCENT_OFF", 20,
                         PROMO_START, PROMO_END, "EXCLUSIVE")
        create_promotion(product["id"], "CENTS_OFF", 100,
                         PROMO_START, PROMO_END, "STACKABLE",
                         operator_id=world["operator"]["id"])
        order = create_order(
            world, [{"product_id": product["id"], "quantity_cases": 1}],
        )
        submitted = submit_order(world, order["id"])
        # EXCLUSIVE 20% of 1000 = 200 applies ALONE; the 100-cent stackable
        # is ignored (a stacked result would be 700 total / 300 discount).
        assert submitted["order_total_cents"] == 800
        assert submitted["promo_discount_cents"] == 200

    def test_promo_stackable_sum_and_scope_filtering(self, api):
        """PRD §3.5: "If no `EXCLUSIVE` promotion is eligible, the effective
        values of all eligible `STACKABLE` promotions sum together."
        PRD §3.5: "each `ACTIVE`, its window covering the current logical
        instant, its product matching the line, and its scope global or equal
        to the order's operator"

        Design: Corner/calculations/promo_stackable_sum_and_scope_filtering
        """
        op_s = create_operator("Op StkS")
        op_t = create_operator("Op StkT")
        route = create_route("R-STK", ("MON",), 50, 0)
        product = create_product(sku="STK-1", name="Stk item", case_pack_qty=1)
        create_promotion(product["id"], "CENTS_OFF", 30,
                         PROMO_START, PROMO_END, "STACKABLE")
        create_promotion(product["id"], "CENTS_OFF", 20,
                         PROMO_START, PROMO_END, "STACKABLE",
                         operator_id=op_s["id"])

        def _order_for(operator, loc_name):
            loc = create_location(operator["id"], route["id"], loc_name)
            om = make_operator_manager_headers(operator["id"])
            pg = create_draft_planogram(
                loc["id"],
                [{"slot_code": "A1", "product_id": product["id"],
                  "par_level_units": 10, "vend_price_cents": 200}],
                operator["id"], "PG-" + loc_name,
            )
            activate_planogram(pg["id"], loc["id"], operator["id"])
            resp = api.create_order(
                {
                    "location_id": loc["id"],
                    "requested_delivery_date": "2026-08-03",
                    "lines": [{"product_id": product["id"], "quantity_cases": 1}],
                },
                om,
            )
            created = validate_success(resp, 201)
            return validate_success(api.submit_order(created["id"], om), 200)

        submitted_s = _order_for(op_s, "L-StkS")
        submitted_t = _order_for(op_t, "L-StkT")
        # Operator S sees global 30 + own-scoped 20; operator T sees global 30.
        assert submitted_s["order_total_cents"] == 950
        assert submitted_s["promo_discount_cents"] == 50
        assert submitted_t["order_total_cents"] == 970
        assert submitted_t["promo_discount_cents"] == 30

    def test_promo_expired_window_not_applied(self, api):
        """PRD §3.5: "each `ACTIVE`, its window covering the current logical
        instant"
        PRD §2.5: "Promotion windows are half-open: `starts_at` is inclusive
        and `ends_at` is exclusive."

        Design: Corner/calculations/promo_expired_window_not_applied
        """
        world = setup_selling_location(
            products_spec=[{"sku": "EXP-1", "name": "Exp promo item",
                            "case_pack_qty": 1}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 10, "vend_price_cents": 200}],
            route_code="R-EXPP",
        )
        product = world["products"][0]
        # Window closed before the default logical instant 2026-08-01.
        create_promotion(product["id"], "PERCENT_OFF", 50,
                         "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z",
                         "EXCLUSIVE")
        order = create_order(
            world, [{"product_id": product["id"], "quantity_cases": 1}],
        )
        submitted = submit_order(world, order["id"])
        assert submitted["order_total_cents"] == 1000
        assert submitted["promo_discount_cents"] == 0


class TestPriceFloorAndZeroTotalDelivery:
    def test_promo_floor_zero_and_auto_settle_on_delivery(self, api):
        """PRD §3.5: "the pinned `unit_price_cents` is the product's
        `base_price_cents` minus that discount, floored at zero"
        PRD §3.6: "The settlement dimension advances `UNINVOICED` → `OPEN` and
        `amount_due_cents` is set to `order_total_cents`; if that total is
        zero, the settlement dimension goes straight to `SETTLED`."

        Design: Corner/calculations/promo_floor_zero_and_auto_settle_on_delivery
        """
        world = setup_selling_location(
            products_spec=[{"sku": "FLR-1", "name": "Floor item",
                            "category": "CANDY", "base_price_cents": 1000,
                            "cost_cents": 400, "shelf_life_days": 120}],
            slots_spec=[{"slot_code": "A1", "product_index": 0,
                         "par_level_units": 10, "vend_price_cents": 150}],
            route_code="R-FLR",
        )
        product = world["products"][0]
        create_promotion(product["id"], "CENTS_OFF", 1500,
                         PROMO_START, PROMO_END, "STACKABLE")
        order = create_order(
            world, [{"product_id": product["id"], "quantity_cases": 1}],
        )
        submitted = submit_order(world, order["id"])
        # max(0, 1000 - 1500) == 0; discount accounts base minus line total.
        assert submitted["order_total_cents"] == 0
        assert submitted["promo_discount_cents"] == 1000
        # round_half_up((150*10*1 - 0)/10) == 150
        assert submitted["provisional_margin_per_vend_cents"] == 150

        confirm_order(order["id"])
        delivered = deliver_order(order["id"])
        assert delivered["settlement_status"] == "SETTLED", (
            "a zero-total order never stops at OPEN"
        )
        assert delivered["amount_due_cents"] == 0


class TestPromotionWindowOverlap:
    def _overlap_setup(self, api):
        product = create_product(sku="PROM-O", name="Promo overlap item")
        first = create_promotion(product["id"], "CENTS_OFF", 100,
                                 "2026-08-01T00:00:00Z", "2026-08-10T00:00:00Z",
                                 "STACKABLE")
        return product, first

    def test_overlapping_window_rejected(self, api):
        """PRD §3.5: "Creation rejects with `ERR_PROMOTION_WINDOW_OVERLAP` when
        the half-open window overlaps another `ACTIVE` promotion for the same
        product and an equal operator scope"

        Design: Difficulty/resource_temporal_overlap/promotion_window_overlap_half_open
        """
        product, first = self._overlap_setup(api)
        err = api.create_promotion(
            {
                "product_id": product["id"],
                "discount_type": "CENTS_OFF",
                "discount_value": 50,
                "starts_at": "2026-08-05T00:00:00Z",
                "ends_at": "2026-08-15T00:00:00Z",
                "stacking_class": "STACKABLE",
            },
            ADMIN,
        )
        validate_error(err, ApiErrorId.ERR_PROMOTION_WINDOW_OVERLAP)

        reread = validate_success(api.get_promotion(first["id"], ADMIN), 200)
        assert reread["status"] == "ACTIVE", "original promotion untouched"

    def test_adjacent_window_allowed(self, api):
        """PRD §2.5: "Promotion windows are half-open: `starts_at` is inclusive
        and `ends_at` is exclusive. Two windows that merely touch — one
        promotion's `ends_at` equal to another's `starts_at` — do not overlap."

        Design: Difficulty/resource_temporal_overlap/promotion_window_overlap_half_open
        """
        product, _ = self._overlap_setup(api)
        # [08-10, 08-20) merely touches the incumbent [08-01, 08-10).
        resp = api.create_promotion(
            {
                "product_id": product["id"],
                "discount_type": "CENTS_OFF",
                "discount_value": 25,
                "starts_at": "2026-08-10T00:00:00Z",
                "ends_at": "2026-08-20T00:00:00Z",
                "stacking_class": "STACKABLE",
            },
            ADMIN,
        )
        adjacent = validate_success(resp, 201)
        assert adjacent["status"] == "ACTIVE"


class TestMinOrderFloor:
    def _min_order_world(self, api):
        world = setup_selling_location(
            products_spec=[
                {"sku": "PB-1", "name": "Boundary 895", "case_pack_qty": 1,
                 "base_price_cents": 895, "cost_cents": 500},
                {"sku": "PB-2", "name": "Boundary 894", "case_pack_qty": 1,
                 "base_price_cents": 894, "cost_cents": 500},
            ],
            slots_spec=[
                {"slot_code": "A1", "product_index": 0, "par_level_units": 5,
                 "vend_price_cents": 100},
                {"slot_code": "A2", "product_index": 1, "par_level_units": 5,
                 "vend_price_cents": 100},
            ],
            route_code="R-MIN",
            min_order_cents=1790,
        )
        return world

    def test_min_order_exact_equality_passes(self, api):
        """PRD §3.5: "the fiscal floor (the computed `order_total_cents` at
        least the route's `min_order_cents` — exact equality passes — else
        `ERR_MIN_ORDER_NOT_MET`)"

        Design: Difficulty/boundary_precision_check/min_order_exact_boundary
        """
        world = self._min_order_world(api)
        order = create_order(
            world,
            [{"product_id": world["products"][0]["id"], "quantity_cases": 2}],
        )
        submitted = submit_order(world, order["id"])
        assert submitted["order_total_cents"] == 1790
        assert submitted["fulfillment_status"] == "SUBMITTED", (
            "1790 >= 1790 passes at exact equality"
        )

    def test_min_order_one_cent_below_fails(self, api):
        """PRD §3.5: "the fiscal floor (the computed `order_total_cents` at
        least the route's `min_order_cents` — exact equality passes — else
        `ERR_MIN_ORDER_NOT_MET`)"

        Design: Difficulty/boundary_precision_check/min_order_exact_boundary
        """
        world = self._min_order_world(api)
        order = create_order(
            world,
            [
                {"product_id": world["products"][0]["id"], "quantity_cases": 1},
                {"product_id": world["products"][1]["id"], "quantity_cases": 1},
            ],
        )
        # 895 + 894 = 1789 < 1790.
        err = api.submit_order(order["id"], world["om_headers"])
        validate_error(err, ApiErrorId.ERR_MIN_ORDER_NOT_MET)
        assert get_order(order["id"])["fulfillment_status"] == "DRAFT"


class TestImmediateConsistency:
    def test_submit_response_contains_computed_pricing(self, api):
        """PRD §2.4: "Derived-field recomputation counts as modification. ...
        every mutation is visible in the response of the operation that caused
        it."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/submit_response_contains_computed_pricing
        """
        world = setup_selling_location(
            products_spec=[{"sku": "CON-1", "name": "Cons item"}],
            route_code="R-CONS",
        )
        product = world["products"][0]
        create_promotion(product["id"], "PERCENT_OFF", 10,
                         PROMO_START, PROMO_END, "EXCLUSIVE")
        order = create_order(
            world, [{"product_id": product["id"], "quantity_cases": 1}],
        )
        # The submit RESPONSE itself carries the computed pricing.
        submitted = validate_success(
            api.submit_order(order["id"], world["om_headers"]), 200,
        )
        assert submitted["order_total_cents"] == 900
        assert submitted["promo_discount_cents"] == 100
        assert submitted["fulfillment_status"] == "SUBMITTED"
