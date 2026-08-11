"""Marginal volume-tier pricing and full pricing-pipeline evaluation order (PRD §3.6)."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_order_payload, order_line, set_clock, create_customer,
    create_product, create_route, create_window, create_order,
    setup_catalog_with_route, create_activated_subscription,
    submit_and_pay, schedule_order, deliver_scheduled_order,
    drive_customer_lifetime_ce, TEST_USERS,
)

CS = TEST_USERS["customer_service_headers"]
OM = TEST_USERS["operations_manager_headers"]


class TestVolumeTierMarginalStraddle:
    def test_volume_tier_marginal_straddle_across_boundary(self, api):
        """PRD §3.6: "A line that straddles a boundary is split at the boundary —
        the portion below prices at the lower tier's rate, the portion at or
        above at the next tier's rate."
        PRD §3.6: "the line's `extended_price_cents` is the sum of its portion
        prices, rounded half-up to integer cents exactly once per line —
        portions themselves are never individually rounded."
        A single 3.0-cord line straddles the 2.0 boundary: 2.0 at 0% and 1.0 at
        4% gives extended 60000 + 28800 = 88800 and a 1200 volume discount.

        Design: Difficulty/combinatorial_formula/volume_tier_marginal_straddle_across_boundary
        """
        set_clock()
        customer, product, _route = setup_catalog_with_route(
            sku="P_CORD", product_kind="CORD", species="MAPLE",
            seasoned_grade="SEMI_SEASONED", base_price_cents=30000,
            moisture_ceiling_pct=25.0, available_qty=50)
        res = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 3.0)],
            delivery_postal_code="01010",
            requested_delivery_date="2026-08-15"), CS)
        order = validate_success(res, 201)
        assert order["subtotal_cents"] == 90000
        assert order["volume_discount_cents"] == 1200
        lines = get_success_data(api.list_order_lines(order["id"], CS))
        assert lines[0]["volume_tier_applied"] == "T1"
        assert lines[0]["extended_price_cents"] == 88800

    def test_volume_tier_exactly_at_boundary_earns_no_discount(self, api):
        """PRD §3.6: "the first 2.0 cord-equivalents (tier `T0`) earn no
        discount; from 2.0 up to but not including 4.0 (`T1`) the discount is
        4 percent; from 4.0 up to but not including 8.0 (`T2`) it is 7 percent;
        and from 8.0 onward (`T3`) it is 11 percent."
        A 2.0-cord line lands exactly on the T1 boundary; its T1 portion is
        zero, so the volume discount is 0.

        Design: Difficulty/combinatorial_formula/volume_tier_marginal_straddle_across_boundary
        """
        set_clock()
        customer, product, _route = setup_catalog_with_route(
            sku="P_CORD2", product_kind="CORD", species="MAPLE",
            seasoned_grade="SEMI_SEASONED", base_price_cents=30000,
            moisture_ceiling_pct=25.0, available_qty=50)
        res = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 2.0)]), CS)
        order = validate_success(res, 201)
        assert order["subtotal_cents"] == 60000
        assert order["volume_discount_cents"] == 0
        lines = get_success_data(api.list_order_lines(order["id"], CS))
        assert lines[0]["extended_price_cents"] == 60000


class TestStackingFeeEvaluationOrder:
    """Full-pipeline pricing on a GOLD customer with an ESTATE subscription."""

    def _setup_gold_customer_with_estate(self, api):
        set_clock("2026-10-01T00:00:00Z")
        customer = create_customer(postal_code="20002")
        sub = create_activated_subscription(
            customer["id"], tier="ESTATE", season_year=2026,
            commitment_cord_equivalent=8.0, prepaid_cents=0, discount_pct=0.12)
        product = create_product(sku="P4", product_kind="CORD", species="OAK",
                                 seasoned_grade="KILN_DRIED", base_price_cents=40000,
                                 moisture_ceiling_pct=20.0, available_qty=50)
        route = create_route(route_code="R4", depot_name="Central",
                             prefixes=("2",), capacity=100.0)
        # Drive the customer to GOLD with 12.0 lifetime CE (two 6.0 deliveries).
        drive_customer_lifetime_ce(customer["id"], product["id"], route, 12.0,
                                   postal_code="20002", chunk_ce=6.0,
                                   first_service_date="2026-10-20")
        return customer, sub, product, route

    def test_stacking_fee_circular_evaluation_order_pinned_stages(self, api):
        """PRD §3.6: "When `requested_delivery_date` falls in the winter peak —
        December 15 through February 15 of the following year, both dates
        inclusive — the base after all three discounts is surcharged at 12
        percent for `STANDARD` customers, 8 percent for `SILVER`, and 0 percent
        for `GOLD`, whose tier waives the peak surcharge entirely; outside the
        peak the surcharge is zero."
        PRD §3.6: "If the order draws on a qualifying subscription — one that is
        `ACTIVE`, in its season window for the requested date, and with
        `stacking_included` true — stacking is complimentary and the fee is
        forced to 0."

        Design: Difficulty/combinatorial_formula/stacking_fee_circular_evaluation_order_pinned
        """
        customer, sub, product, _route = self._setup_gold_customer_with_estate(api)
        customer = get_success_data(api.get_customer(customer["id"], CS))
        assert customer["loyalty_tier"] == "GOLD"

        res = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 9.0)],
            delivery_street_address="4 Birch", delivery_postal_code="20002",
            requested_delivery_date="2026-12-20",
            subscription_id=sub["id"], stacking_addon=True), CS)
        order = validate_success(res, 201)
        # 9.0 x 40000 x 1.35
        assert order["subtotal_cents"] == 486000
        # Marginal split: 2.0@0% + 2.0@4% + 4.0@7% + 1.0@11% on 54000
        assert order["volume_discount_cents"] == 25380
        # round_half_up((486000 - 25380) * 0.12)
        assert order["subscription_discount_cents"] == 55274
        # round_half_up((486000 - 25380 - 55274) * 0.04)
        assert order["loyalty_discount_cents"] == 16214
        # GOLD waives the peak surcharge even inside the winter peak
        assert order["seasonal_surcharge_cents"] == 0
        # ESTATE subscription includes stacking
        assert order["stacking_fee_cents"] == 0

    def test_stacking_fee_circular_evaluation_order_pinned_total(self, api):
        """PRD §3.6: "The base zone fee is set by the length of the matched
        prefix: five characters or more is zone A at 4,500 cents, three or four
        characters is zone B at 6,500 cents, and one or two characters is zone C
        at 9,500 cents. Bulk adds to this: a `total_cord_equivalent` strictly
        greater than 4.0 adds 1,500 cents, and strictly greater than 8.0 adds a
        further 1,500 cents on top."
        PRD §3.6: "`total_cents` is `subtotal_cents` minus
        `volume_discount_cents` minus `subscription_discount_cents` minus
        `loyalty_discount_cents`, plus `seasonal_surcharge_cents`, plus
        `stacking_fee_cents`, plus `delivery_fee_cents`."
        Prefix "2" (length 1) is zone C at 9500; 9.0 CE adds both bulk
        surcharges: delivery fee 12500, total 401632.

        Design: Difficulty/combinatorial_formula/stacking_fee_circular_evaluation_order_pinned
        """
        customer, sub, product, _route = self._setup_gold_customer_with_estate(api)
        res = api.create_order(create_order_payload(
            customer["id"], [order_line(product["id"], 9.0)],
            delivery_street_address="4 Birch", delivery_postal_code="20002",
            requested_delivery_date="2026-12-20",
            subscription_id=sub["id"], stacking_addon=True), CS)
        order = validate_success(res, 201)
        assert order["delivery_fee_cents"] == 12500
        assert order["total_cents"] == 401632
