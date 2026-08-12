"""Order composition: quantity granularity, initial state, pricing fields (PRD §3.5, §3.6)."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_order, create_order_payload, order_line,
    set_clock, create_customer, create_product, create_route,
    setup_catalog_with_route, create_subscription, create_order,
    TEST_USERS,
)

CS = TEST_USERS["customer_service_headers"]
OM = TEST_USERS["operations_manager_headers"]
RP = TEST_USERS["route_planner_headers"]


class TestQuantityGranularity:
    def test_order_line_quantity_granularity_pellet_bag_integer(self, api):
        """PRD §3.5: "Quantity granularity is per kind: `CORD` and `HALF_CORD`
        accept any positive multiple of 0.5 (so a `HALF_CORD` quantity of 1.0 is
        exactly one half-cord unit), `PELLET_TON` accepts positive multiples of
        1.0, and `PELLET_BAG` accepts positive whole bags; anything else is
        `ERR_INVALID_QUANTITY`."

        Design: Corner/entities/order_line_quantity_granularity_pellet_bag_integer
        """
        set_clock()
        customer, product, _route = setup_catalog_with_route(
            sku="PB1", product_kind="PELLET_BAG", species="HARDWOOD_BLEND",
            seasoned_grade="KILN_DRIED", base_price_cents=700,
            moisture_ceiling_pct=10.0, available_qty=1000)
        res = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 1.5)]), CS)
        validate_error(res, "ERR_INVALID_QUANTITY", expected_status=422)

    def test_order_line_quantity_granularity_half_cord_half_step(self, api):
        """PRD §3.5: "Quantity granularity is per kind: `CORD` and `HALF_CORD`
        accept any positive multiple of 0.5 (so a `HALF_CORD` quantity of 1.0 is
        exactly one half-cord unit), `PELLET_TON` accepts positive multiples of
        1.0, and `PELLET_BAG` accepts positive whole bags; anything else is
        `ERR_INVALID_QUANTITY`."

        Design: Corner/entities/order_line_quantity_granularity_half_cord_half_step
        """
        set_clock()
        customer, product, _route = setup_catalog_with_route(
            sku="HC1", product_kind="CORD", species="OAK",
            seasoned_grade="KILN_DRIED", base_price_cents=40000,
            moisture_ceiling_pct=20.0, available_qty=100)
        res = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 1.3)]), CS)
        validate_error(res, "ERR_INVALID_QUANTITY", expected_status=422)
        ok = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 1.5)]), CS)
        validate_success(ok, 201)


class TestOrderInitialState:
    def test_order_initial_state_is_draft_and_unpaid(self, api):
        """PRD §3.5: "A new order is born in `DRAFT` on the fulfillment axis
        and `UNPAID` on the payment axis."

        Design: Corner/state_machines/order_initial_state_is_draft_and_unpaid
        """
        set_clock()
        customer, product, _route = setup_catalog_with_route()
        order = create_order(customer["id"], product["id"], 1.0)
        assert_order(order)
        assert order["fulfillment_status"] == "DRAFT"
        assert order["payment_status"] == "UNPAID"


class TestOrderPricingBreakdown:
    def test_get_order_returns_full_pricing_breakdown(self, api):
        """PRD §3.6: "All stage outputs land on the order as `subtotal_cents`,
        `volume_discount_cents`, `subscription_discount_cents`,
        `loyalty_discount_cents`, `seasonal_surcharge_cents`,
        `stacking_fee_cents`, `delivery_fee_cents`, and finally `total_cents`,
        alongside the order's `total_cord_equivalent`."
        PRD §3.6: "Otherwise the fee is a flat 3,500 cents plus 1,200 cents per
        whole cord-equivalent, with the order's `total_cord_equivalent` rounded
        up to the next whole cord before the per-cord charge is applied."

        Design: Corner/endpoints/get_order_returns_full_pricing_breakdown
        """
        set_clock()
        customer, product, _route = setup_catalog_with_route()
        res = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 2.0)],
            stacking_addon=True), CS)
        created = validate_success(res, 201)
        order = validate_success(api.get_order(created["id"], CS), 200)
        assert_order(order)
        for field in ("subtotal_cents", "volume_discount_cents",
                      "subscription_discount_cents", "loyalty_discount_cents",
                      "seasonal_surcharge_cents", "stacking_fee_cents",
                      "delivery_fee_cents", "total_cents"):
            assert field in order, f"order missing pricing field {field}"
        # 2.0 x 54000 (40000 x 1.35 KILN_DRIED)
        assert order["subtotal_cents"] == 108000
        # 3500 + ceil(2.0) * 1200
        assert order["stacking_fee_cents"] == 5900


class TestNoRoute:
    def test_err_no_route_when_no_prefix_matches(self, api):
        """PRD §3.6: "the system selects among active routes by longest-prefix
        match against `delivery_postal_code` with the tie-breaks of §3.4, and an
        empty candidate set rejects the pricing with `ERR_NO_ROUTE`."

        Design: Corner/errors/err_no_route_when_no_prefix_matches
        """
        set_clock()
        customer = create_customer(postal_code="99999")
        product = create_product(sku="PNR")
        res = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 1.0)],
            delivery_postal_code="99999"), CS)
        validate_error(res, "ERR_NO_ROUTE", expected_status=422)


class TestSubscriptionAttach:
    def test_subscription_mismatch_rejected(self, api):
        """PRD §3.5: "Attaching a subscription owned by a different customer is
        rejected with `ERR_SUBSCRIPTION_MISMATCH`, and attaching one whose
        season window does not contain the requested delivery date is rejected
        with `ERR_SUBSCRIPTION_OUT_OF_SEASON`."

        Design: Corner/validations/subscription_mismatch_rejected
        """
        set_clock()
        cust_a = create_customer(postal_code="01010")
        cust_b = create_customer(postal_code="01010")
        sub_b = create_subscription(cust_b["id"])
        product = create_product(sku="PSM")
        create_route(prefixes=("0",))
        res = api.create_order(create_order_payload(
            cust_a["id"], [order_line(product["id"], 1.0)],
            requested_delivery_date="2026-12-15",
            subscription_id=sub_b["id"]), CS)
        validate_error(res, "ERR_SUBSCRIPTION_MISMATCH", expected_status=422)


class TestCordEquivalentConversion:
    def test_cord_equivalent_conversion_per_kind(self, api):
        """PRD §3.6: "Each product kind carries a cord-equivalent factor: a
        `CORD` is 1.0, a `HALF_CORD` unit is 0.5, a `PELLET_TON` is 0.8, and a
        `PELLET_BAG` — a 40-lb bag, fifty to the ton — is 0.016."
        PRD §3.6: "The order's `total_cord_equivalent` is the sum of its lines."

        Design: Corner/calculations/cord_equivalent_conversion_per_kind
        """
        set_clock()
        customer = create_customer()
        p_cord = create_product(sku="CE_C", product_kind="CORD", species="OAK",
                                base_price_cents=40000, available_qty=100)
        p_half = create_product(sku="CE_H", product_kind="HALF_CORD", species="OAK",
                                base_price_cents=22000, available_qty=100)
        p_ton = create_product(sku="CE_T", product_kind="PELLET_TON",
                               species="HARDWOOD_BLEND", base_price_cents=30000,
                               moisture_ceiling_pct=10.0, available_qty=100)
        p_bag = create_product(sku="CE_B", product_kind="PELLET_BAG",
                               species="HARDWOOD_BLEND", base_price_cents=700,
                               moisture_ceiling_pct=10.0, available_qty=1000)
        create_route(prefixes=("0",))
        res = api.create_order(create_order_payload(
            customer["id"], [
                order_line(p_cord["id"], 1.0),
                order_line(p_half["id"], 1.0),
                order_line(p_ton["id"], 1.0),
                order_line(p_bag["id"], 50),
            ]), CS)
        order = validate_success(res, 201)
        assert_order(order)
        # 1.0 + 0.5 + 0.8 + (50 * 0.016) == 3.1
        assert order["total_cord_equivalent"] == pytest.approx(3.1, abs=1e-6)


class TestSeasonedGradeMultiplier:
    def test_seasoned_grade_price_multiplier_applied_correctly(self, api):
        """PRD §3.6: "When a line is added, its `unit_price_cents` is frozen
        from the product's `base_price_cents` at that moment, multiplied by the
        seasoned-grade multiplier: `GREEN` fuel prices at 0.75 of list,
        `SEMI_SEASONED` at 1.00, and `KILN_DRIED` at 1.35, with the product
        rounded half-up to integer cents."

        Design: Corner/calculations/seasoned_grade_price_multiplier_applied_correctly
        """
        set_clock()
        customer = create_customer()
        p_green = create_product(sku="PG", seasoned_grade="GREEN",
                                 base_price_cents=40000, moisture_ceiling_pct=60.0)
        p_semi = create_product(sku="PS", seasoned_grade="SEMI_SEASONED",
                                base_price_cents=40000, moisture_ceiling_pct=25.0)
        p_kiln = create_product(sku="PK", seasoned_grade="KILN_DRIED",
                                base_price_cents=40000, moisture_ceiling_pct=20.0)
        create_route(prefixes=("0",))
        res = api.create_order(create_order_payload(
            customer["id"], [
                order_line(p_green["id"], 1.0),
                order_line(p_semi["id"], 1.0),
                order_line(p_kiln["id"], 1.0),
            ]), CS)
        order = validate_success(res, 201)
        lines = get_success_data(api.list_order_lines(order["id"], CS))
        by_product = {line["product_id"]: line for line in lines}
        assert by_product[p_green["id"]]["unit_price_cents"] == 30000
        assert by_product[p_semi["id"]]["unit_price_cents"] == 40000
        assert by_product[p_kiln["id"]]["unit_price_cents"] == 54000
