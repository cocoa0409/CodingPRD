"""Pricing engine: delivery fee (quote vs settled), service fee, dasher pay,
surge tiers, small-order fee, ETA, and immediate computed-field consistency.

Canonical "DT" zone: base 300, per_km 120 (route 4 -> raw distance fee 780),
service_fee_bps 850, small_order_threshold 1500, small_order_fee 200,
cap 2000, guarantee 700, dasher base 250, dasher_per_km 100 (route 4 -> base 650),
surge tier_1 at demand 5 (m 1.25), tier_2 at demand 10 (m 1.6).
"""
import pytest

from test_helpers import (
    validate_success,
    api_client,
    make_dasher_headers, make_customer_headers,
    setup_demand_then_measure, setup_order_picked_up,
    setup_market, place_simple_order, dispatch,
    create_zone, create_restaurant, create_menu_item, create_customer,
    place_order, line_item,
)


# ===========================================================================
# dual_variant_calc — delivery fee quote vs final on the Order domain
# ===========================================================================
class TestDeliveryFeeQuoteVsFinal:
    def test_quote_counts_self_in_demand(self, api):
        """PRD §3.5: "It is **forward-looking**: the surge tier is selected from projected demand that *includes the order being placed*, read from the zone's `active_order_count` (which already counts this order at the moment of placement)."

        Demand=5 at placement -> tier-1 multiplier 1.25 -> raw 780*1.25=975.

        Design: Difficulty/dual_variant_calc/delivery_fee_quote_vs_final_on_order
        """
        ctx = setup_demand_then_measure(
            filler_count=4, with_dasher=True, dasher_overrides={"max_batch_size": 5})
        order = api_client.get_order(ctx["order"]["id"],
                                     make_customer_headers(ctx["customer"]["id"]))
        data = validate_success(order)
        assert data["surge_multiplier_applied"] == 1.25, \
            f"quote demand 5 must select tier-1 multiplier 1.25, got {data['surge_multiplier_applied']}"
        assert data["delivery_fee_quote_cents"] == 975, \
            f"expected quote 975, got {data['delivery_fee_quote_cents']}"

    def test_final_excludes_self_diverges_from_quote(self, api):
        """PRD §3.9: "At completion the order is leaving the active pool, so the
        demand used for surge **excludes this order**: it is the zone's
        `active_order_count` reduced by one."

        Demand at completion 5-1=4 -> tier-0 multiplier 1.0 -> final 780, which
        differs from the quote 975.

        Design: Difficulty/dual_variant_calc/delivery_fee_quote_vs_final_on_order
        """
        ctx = setup_demand_then_measure(
            filler_count=4, with_dasher=True, dasher_overrides={"max_batch_size": 5})
        order_id = ctx["order"]["id"]
        rest = ctx["restaurant"]
        dasher = ctx["dasher"]
        # Dispatch / accept / pickup / deliver the measured order while the four
        # fillers remain PLACED (demand at completion = 5).
        measured = api_client.get_order(order_id, make_customer_headers(ctx["customer"]["id"]))
        ver = validate_success(measured)["version"]
        delivery = dispatch(order_id, rest["id"], ver)
        dh = make_dasher_headers(dasher["id"])
        validate_success(api_client.accept_delivery(delivery["id"], dh))
        validate_success(api_client.pickup_delivery(delivery["id"], dh))
        validate_success(api_client.deliver_delivery(delivery["id"], dh))
        final = validate_success(
            api_client.get_order(order_id, make_customer_headers(ctx["customer"]["id"])))
        assert final["delivery_fee_final_cents"] == 780, \
            f"expected final 780 (demand 4, tier-0), got {final['delivery_fee_final_cents']}"
        assert final["delivery_fee_quote_cents"] == 975
        assert final["delivery_fee_quote_cents"] != final["delivery_fee_final_cents"], \
            "quote and final must diverge across the surge boundary"


# ===========================================================================
# dual_variant_calc — dasher pay quote vs settled on the Earnings domain
# ===========================================================================
class TestDasherPayQuoteVsSettled:
    def _setup_pay_scenario(self):
        """Single ASAP order, tip 0, dasher max_batch_size 2. Dispatch + accept,
        then raise tip by +200 before pickup, then pickup + deliver."""
        zone, restaurant, item, dasher, customer = setup_market(
            dasher_overrides={"max_batch_size": 2})
        order = place_simple_order(customer["id"], restaurant["id"], item["id"], tip_cents=0)
        delivery = dispatch(order["id"], restaurant["id"], order["version"])
        dh = make_dasher_headers(dasher["id"])
        delivery = validate_success(api_client.accept_delivery(delivery["id"], dh))
        ch = make_customer_headers(customer["id"])
        validate_success(api_client.adjust_tip(order["id"], {"delta_cents": 200}, ch),
                         expected_status=201)
        validate_success(api_client.pickup_delivery(delivery["id"], dh))
        validate_success(api_client.deliver_delivery(delivery["id"], dh))
        return delivery["id"], dasher["id"]

    def test_pay_quote_sits_on_guarantee_floor_at_dispatch(self, api):
        """PRD §3.9: "For the quote (`pay_quote_cents`, captured at dispatch and
        recorded on both the delivery and the accruing earnings record), the tip
        component uses the order's `tip_cents` as it stood at dispatch."

        Base 650 + tip 0 = 650 < guarantee 700 -> top-up to 700.

        Design: Difficulty/dual_variant_calc/dasher_pay_quote_vs_settled_on_earnings
        """
        delivery_id, dasher_id = self._setup_pay_scenario()
        data = validate_success(
            api_client.get_delivery(delivery_id, make_dasher_headers(dasher_id)))
        assert data["pay_quote_cents"] == 700, \
            f"quote (base 650 + tip 0, floored to 700) expected 700, got {data['pay_quote_cents']}"

    def test_settled_pay_reads_raised_tip_eliminating_topup(self, api):
        """PRD §3.9: "For the settled figure (`settled_pay_cents`, computed at
        drop-off), the tip component uses the order's *current* `tip_cents`,
        reflecting any tip adjustments applied before completion, and the
        guarantee is re-evaluated against that new pre-guarantee total."

        Base 650 + tip 200 = 850 >= guarantee 700 -> no top-up -> settled 850,
        differing from the quote 700.

        Design: Difficulty/dual_variant_calc/dasher_pay_quote_vs_settled_on_earnings
        """
        delivery_id, dasher_id = self._setup_pay_scenario()
        data = validate_success(
            api_client.get_delivery(delivery_id, make_dasher_headers(dasher_id)))
        assert data["settled_pay_cents"] == 850, \
            f"settled (base 650 + tip 200, no top-up) expected 850, got {data['settled_pay_cents']}"
        assert data["pay_quote_cents"] != data["settled_pay_cents"], \
            "quote 700 and settled 850 must diverge"


# ===========================================================================
# combinatorial_formula — tiered surge with cap (mode a)
# ===========================================================================
class TestTieredSurgeWithCap:
    def test_tier2_surge_applied_under_cap(self, api):
        """PRD §3.5: "If that demand is at or above the zone's
        `surge_tier_2_demand`, the multiplier is `surge_multiplier_tier_2`"
        PRD §3.5: "That raw fee is multiplied by the chosen multiplier and
        rounded half up, then capped at the smaller of the result and the zone's
        `delivery_fee_cap_cents`."

        Demand 10 -> tier-2 m 1.6 -> raw 780*1.6=1248, under cap 2000.

        Design: Difficulty/combinatorial_formula/delivery_fee_tiered_surge_with_cap_mode_a
        """
        ctx = setup_demand_then_measure(filler_count=9)
        order = validate_success(
            api_client.get_order(ctx["order"]["id"],
                                 make_customer_headers(ctx["customer"]["id"])))
        assert order["surge_multiplier_applied"] == 1.6, \
            f"demand 10 must select tier-2 multiplier 1.6, got {order['surge_multiplier_applied']}"
        assert order["delivery_fee_quote_cents"] == 1248, \
            f"expected 780*1.6=1248, got {order['delivery_fee_quote_cents']}"

    def test_tier2_multiplier_frozen_into_surge_applied(self, api):
        """PRD §3.5: "The sum is stored in `delivery_fee_quote_cents`, and the chosen multiplier is frozen into `surge_multiplier_applied`."

        Verifies the tier-2 boundary (demand exactly 10) freezes 1.6.

        Design: Difficulty/combinatorial_formula/delivery_fee_tiered_surge_with_cap_mode_a
        """
        ctx = setup_demand_then_measure(filler_count=9)
        order = validate_success(
            api_client.get_order(ctx["order"]["id"],
                                 make_customer_headers(ctx["customer"]["id"])))
        assert order["surge_multiplier_applied"] == 1.6


# ===========================================================================
# combinatorial_formula — per-line service fee rounding (mode b)
# ===========================================================================
class TestPerLineServiceFee:
    def _place_three_line_order(self):
        zone = create_zone(service_fee_bps=850)
        restaurant = create_restaurant(zone["id"])
        item_a = create_menu_item(restaurant["id"], name="A", price_cents=333)
        item_b = create_menu_item(restaurant["id"], name="B", price_cents=250)
        item_c = create_menu_item(restaurant["id"], name="C", price_cents=149)
        customer = create_customer()
        order = place_order(
            customer["id"], restaurant["id"],
            [line_item(item_a["id"], 3), line_item(item_b["id"], 2), line_item(item_c["id"], 1)])
        return order

    def test_service_fee_rounds_per_line_then_sums(self, api):
        """PRD §3.4: "For each `ORDERED` line, the line's own `service_fee_cents` is the line's `extended_price_cents` multiplied by the zone's `service_fee_bps`, divided by 10000, rounded half up. The order's `service_fee_cents` is then the sum of those rounded per-line fees."

        Lines [999,500,149] at 850 bps -> per-line [85,43,13]=141 (not the
        sum-then-round 140).

        Design: Difficulty/combinatorial_formula/service_fee_round_per_line_mode_b
        """
        order = self._place_three_line_order()
        assert order["order_subtotal_cents"] == 1648, \
            f"expected subtotal 999+500+149=1648, got {order['order_subtotal_cents']}"
        assert order["service_fee_cents"] == 141, \
            f"per-line round-then-sum expected 141, got {order['service_fee_cents']}"

    def test_per_line_rounding_distinct_from_sum_then_round(self, api):
        """PRD §3.4: "Rounding each line first and then adding can differ by a
        cent from adding first and rounding once; the former is the required
        behavior."

        Asserts the result is the per-line value 141, never the 140 that
        sum-then-round would yield.

        Design: Difficulty/combinatorial_formula/service_fee_round_per_line_mode_b
        """
        order = self._place_three_line_order()
        assert order["service_fee_cents"] == 141
        assert order["service_fee_cents"] != 140, \
            "must not collapse to the forbidden sum-then-round value 140"


# ===========================================================================
# boundary_precision_check — surge tier >= boundary (demand 4 vs 5)
# ===========================================================================
class TestSurgeTierBoundary:
    def test_demand_below_boundary_stays_tier0(self, api):
        """PRD §3.5: "otherwise, if it is at or above `surge_tier_1_demand`, the multiplier is `surge_multiplier_tier_1`; otherwise it is `surge_multiplier_tier_0`."

        The 4th order (demand 4 < 5) stays tier-0 multiplier 1.0.

        Design: Difficulty/boundary_precision_check/surge_tier_boundary_demand_5_inclusive
        """
        # Three fillers then a 4th measured order -> demand 4 at placement.
        ctx = setup_demand_then_measure(filler_count=3)
        order = validate_success(
            api_client.get_order(ctx["order"]["id"],
                                 make_customer_headers(ctx["customer"]["id"])))
        assert order["surge_multiplier_applied"] == 1.0, \
            f"demand 4 (< tier-1 boundary 5) must be tier-0 1.0, got {order['surge_multiplier_applied']}"

    def test_demand_at_boundary_inclusive_triggers_tier1(self, api):
        """PRD §3.5: "If that demand is at or above the zone's
        `surge_tier_2_demand`, the multiplier is `surge_multiplier_tier_2`;
        otherwise, if it is at or above `surge_tier_1_demand`, the multiplier is
        `surge_multiplier_tier_1`; otherwise it is `surge_multiplier_tier_0`."

        Demand exactly 5 (>= boundary, inclusive) triggers tier-1 multiplier 1.25.

        Design: Difficulty/boundary_precision_check/surge_tier_boundary_demand_5_inclusive
        """
        ctx = setup_demand_then_measure(filler_count=4)
        order = validate_success(
            api_client.get_order(ctx["order"]["id"],
                                 make_customer_headers(ctx["customer"]["id"])))
        assert order["surge_multiplier_applied"] == 1.25, \
            f"demand 5 (>= boundary) must be tier-1 1.25, got {order['surge_multiplier_applied']}"


# ===========================================================================
# Corner: calculations
# ===========================================================================
class TestCalculationCorners:
    def test_small_order_fee_applied_below_threshold(self, api):
        """PRD §3.5: "Finally, if the `order_subtotal_cents` is strictly below the zone's `small_order_threshold_cents`, the zone's `small_order_fee_cents` is added on top of the capped amount; otherwise nothing is added."

        Subtotal 1000 (< 1500) at demand 1 (m 1.0) -> 780 + 200 = 980.

        Design: Corner/calculations/small_order_fee_applied_below_threshold
        """
        zone = create_zone()
        restaurant = create_restaurant(zone["id"])
        item = create_menu_item(restaurant["id"], name="Snack", price_cents=1000)
        customer = create_customer()
        order = place_simple_order(customer["id"], restaurant["id"], item["id"])
        assert order["order_subtotal_cents"] == 1000
        assert order["delivery_fee_quote_cents"] == 980, \
            f"expected 780 + 200 small-order = 980, got {order['delivery_fee_quote_cents']}"

    def test_eta_minutes_computed_correctly(self, api):
        """PRD §3.5: "The arrival estimate, `eta_minutes`, is the restaurant's `prep_minutes` plus its `route_distance_km` multiplied by three minutes per kilometer."

        prep 15 + route 4 * 3 = 27.

        Design: Corner/calculations/eta_minutes_computed_correctly
        """
        zone = create_zone()
        restaurant = create_restaurant(zone["id"], prep_minutes=15, route_distance_km=4)
        item = create_menu_item(restaurant["id"])
        customer = create_customer()
        order = place_simple_order(customer["id"], restaurant["id"], item["id"])
        assert order["eta_minutes"] == 27, \
            f"expected 15 + 4*3 = 27, got {order['eta_minutes']}"

    def test_immediate_consistency_computed_fields_in_create_response(self, api):
        """PRD §2.5: "every affected entity independently has its `updated_at` refreshed" and PRD §3.4–§3.5 compute subtotal, per-line service fee, the
        delivery quote, and the ETA at placement.

        Single $20 item, route 4, demand 1: subtotal 2000, fee 780, service_fee
        round_half_up(2000*850/10000)=170, eta 27 — all present in the POST
        /orders response.

        Design: Corner/consistency_model/immediate_consistency_order_fields_in_create_response
        """
        zone = create_zone()
        restaurant = create_restaurant(zone["id"], prep_minutes=15, route_distance_km=4)
        item = create_menu_item(restaurant["id"], price_cents=2000)
        customer = create_customer()
        order = place_simple_order(customer["id"], restaurant["id"], item["id"])
        assert order["order_subtotal_cents"] == 2000
        assert order["delivery_fee_quote_cents"] == 780
        assert order["service_fee_cents"] == 170, \
            f"expected round_half_up(2000*850/10000)=170, got {order['service_fee_cents']}"
        assert order["eta_minutes"] == 27
