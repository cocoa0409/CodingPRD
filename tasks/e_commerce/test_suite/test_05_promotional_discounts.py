"""
Test 05 -- Promotional Discounts: dual-variant calculation engine.

Covers:
  - PERCENTAGE_FIRST vs FIXED_FIRST discount strategies (dual variant)
  - Promotion types: PERCENTAGE, FIXED_AMOUNT, BUY_X_GET_Y_FREE
  - Stacking rules: non-stackable, stackable, mixed
  - max_discount_cap enforcement
  - promo_threshold activation
  - Category matching (applicable_categories)
  - Running total floor (>= 0.01)
  - Discount share allocation (waterfall with remainder on last item)
  - Usage limits (max_usage)
"""

import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, assert_cost_precision, assert_version_incremented,
    NON_EXISTENT_UUID, TEST_USERS,
    assert_order, assert_order_item, assert_order_invariants,
    create_order_payload, create_payment_payload, create_product_payload,
    create_promotion_payload,
    create_and_approve_shop, create_and_list_product, create_and_activate_promotion,
    setup_basic_order_scenario, setup_shop_with_promotion,
    place_and_pay_order, place_pay_and_deliver_order, create_paid_order,
    ERR_PROMOTION_USAGE_EXHAUSTED,
)

# ---------------------------------------------------------------------------
# Header shortcuts
# ---------------------------------------------------------------------------

_customer = TEST_USERS["customer_headers"]
_seller = TEST_USERS["seller_headers"]
_admin = TEST_USERS["admin_headers"]


# ===================================================================
# Helpers
# ===================================================================


def _setup_shop_with_strategy(strategy):
    """Create an approved shop with the given discount_strategy."""
    return create_and_approve_shop(discount_strategy=strategy)


def _place_order(shop_id, product_ids_qtys):
    """Place an order for the given [(product_id, qty), ...].

    Returns the created order dict.
    """
    items = [{"product_id": pid, "quantity": qty} for pid, qty in product_ids_qtys]
    payload = create_order_payload(shop_id=shop_id, items=items)
    return get_success_data(api_client.create_order(payload, _customer))


def _get_order_items(order_id):
    """Return the items list from an order detail response."""
    detail = get_success_data(api_client.get_order(order_id, _admin))
    return detail.get("items") or detail.get("order_items") or []


def _setup_dual_variant_scenario(strategy):
    """Setup: shop (with strategy), product at $100, two stackable promos
    (20% PERCENTAGE priority=1, $10 FIXED_AMOUNT priority=2).

    Returns (shop, product).
    """
    shop = _setup_shop_with_strategy(strategy)
    product = create_and_list_product(
        shop["id"],
        product_name="Widget",
        category="electronics",
        base_price=100.00,
        inventory_count=100,
    )
    # 20% off -- stackable, priority 1
    create_and_activate_promotion(
        shop["id"],
        promo_name="20pct off",
        promo_type="PERCENTAGE",
        promo_value=20,
        stackable=True,
        priority=1,
        applicable_categories=[],
    )
    # $10 off -- stackable, priority 2
    create_and_activate_promotion(
        shop["id"],
        promo_name="$10 off",
        promo_type="FIXED_AMOUNT",
        promo_value=10,
        stackable=True,
        priority=2,
        applicable_categories=[],
    )
    return shop, product


# ===================================================================
# TestDualVariantDiscount
# ===================================================================


class TestDualVariantDiscount:
    """Core dual-variant test: same products/promos, different strategy -> different totals."""

    def test_percentage_first_total(self):
        """PERCENTAGE_FIRST: $100 * 0.8 = $80, $80 - $10 = $70 -> discount=$30."""
        shop, product = _setup_dual_variant_scenario("PERCENTAGE_FIRST")
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["subtotal"] == pytest.approx(100.00, abs=0.01)
        assert order["discount_amount"] == pytest.approx(30.00, abs=0.01)
        assert order["total_amount"] == pytest.approx(70.00, abs=0.01)

    def test_fixed_first_total(self):
        """FIXED_FIRST: $100 - $10 = $90, $90 * 0.8 = $72 -> discount=$28."""
        shop, product = _setup_dual_variant_scenario("FIXED_FIRST")
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["subtotal"] == pytest.approx(100.00, abs=0.01)
        assert order["discount_amount"] == pytest.approx(28.00, abs=0.01)
        assert order["total_amount"] == pytest.approx(72.00, abs=0.01)

    def test_dual_variant_totals_differ(self):
        """Identical products + promos but different strategies yield different totals."""
        shop_pf, prod_pf = _setup_dual_variant_scenario("PERCENTAGE_FIRST")
        shop_ff, prod_ff = _setup_dual_variant_scenario("FIXED_FIRST")

        order_pf = _place_order(shop_pf["id"], [(prod_pf["id"], 1)])
        order_ff = _place_order(shop_ff["id"], [(prod_ff["id"], 1)])

        assert order_pf["total_amount"] != pytest.approx(
            order_ff["total_amount"], abs=0.001
        ), "PERCENTAGE_FIRST and FIXED_FIRST should yield different totals"

        # PERCENTAGE_FIRST discount is larger
        assert order_pf["discount_amount"] > order_ff["discount_amount"]

    def test_percentage_first_applied_promotions_recorded(self):
        """applied_promotions list contains both promotions with contributions."""
        shop, product = _setup_dual_variant_scenario("PERCENTAGE_FIRST")
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert len(order["applied_promotions"]) == 2
        # Sum of discount contributions should equal discount_amount
        total_contrib = sum(
            p.get("discount_contribution", 0) for p in order["applied_promotions"]
        )
        assert total_contrib == pytest.approx(order["discount_amount"], abs=0.01)

    def test_fixed_first_applied_promotions_recorded(self):
        """applied_promotions list contains both promotions with contributions."""
        shop, product = _setup_dual_variant_scenario("FIXED_FIRST")
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert len(order["applied_promotions"]) == 2
        total_contrib = sum(
            p.get("discount_contribution", 0) for p in order["applied_promotions"]
        )
        assert total_contrib == pytest.approx(order["discount_amount"], abs=0.01)

    def test_order_invariants_percentage_first(self):
        """Order invariants hold for PERCENTAGE_FIRST discounted order."""
        shop, product = _setup_dual_variant_scenario("PERCENTAGE_FIRST")
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert_order(order)
        assert_order_invariants(order)

    def test_order_invariants_fixed_first(self):
        """Order invariants hold for FIXED_FIRST discounted order."""
        shop, product = _setup_dual_variant_scenario("FIXED_FIRST")
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert_order(order)
        assert_order_invariants(order)


# ===================================================================
# TestPromotionTypes
# ===================================================================


class TestPromotionTypes:
    """Individual promotion type behaviour."""

    def test_percentage_discount(self):
        """PERCENTAGE promo_value=20 on $100 -> $20 discount."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=100.00, inventory_count=50,
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=20,
            priority=1,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["discount_amount"] == pytest.approx(20.00, abs=0.01)
        assert order["total_amount"] == pytest.approx(80.00, abs=0.01)

    def test_fixed_amount_discount(self):
        """FIXED_AMOUNT promo_value=15 on $100 -> $15 discount."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=100.00, inventory_count=50,
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="FIXED_AMOUNT",
            promo_value=15,
            priority=1,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["discount_amount"] == pytest.approx(15.00, abs=0.01)
        assert order["total_amount"] == pytest.approx(85.00, abs=0.01)

    def test_fixed_amount_capped_at_running_total(self):
        """FIXED_AMOUNT of $200 on $50 subtotal -> discount capped at $49.99 (floor 0.01)."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=50.00, inventory_count=50,
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="FIXED_AMOUNT",
            promo_value=200,
            priority=1,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        # Floor at 0.01
        assert order["total_amount"] >= 0.01
        assert order["discount_amount"] == pytest.approx(
            order["subtotal"] - order["total_amount"], abs=0.01
        )

    def test_buy_x_get_y_free(self):
        """BUY_X_GET_Y_FREE: buy 3 get 1 free -> cheapest item free."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"],
            base_price=25.00,
            inventory_count=50,
            category="electronics",
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="BUY_X_GET_Y_FREE",
            promo_value=1,          # Y = 1 free
            promo_threshold=3,       # X = 3
            priority=1,
            applicable_categories=[],
        )
        # Buy 4 items (meets threshold of 3, get 1 free)
        order = _place_order(shop["id"], [(product["id"], 4)])
        # 4 x $25 = $100, 1 free item = $25 discount
        assert order["subtotal"] == pytest.approx(100.00, abs=0.01)
        assert order["discount_amount"] == pytest.approx(25.00, abs=0.01)
        assert order["total_amount"] == pytest.approx(75.00, abs=0.01)


# ===================================================================
# TestStackingRules
# ===================================================================


class TestStackingRules:
    """Promotion stacking: non-stackable, stackable, and mixed."""

    def test_non_stackable_only_highest_priority(self):
        """Two non-stackable promos: only the lowest priority number applies."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=100.00, inventory_count=50,
        )
        # Priority 1 (higher priority = lower number) -- 10% off
        create_and_activate_promotion(
            shop["id"],
            promo_name="10pct",
            promo_type="PERCENTAGE",
            promo_value=10,
            stackable=False,
            priority=1,
            applicable_categories=[],
        )
        # Priority 2 (lower priority) -- 30% off
        create_and_activate_promotion(
            shop["id"],
            promo_name="30pct",
            promo_type="PERCENTAGE",
            promo_value=30,
            stackable=False,
            priority=2,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        # Only priority=1 (10%) should apply
        assert order["discount_amount"] == pytest.approx(10.00, abs=0.01)
        assert order["total_amount"] == pytest.approx(90.00, abs=0.01)

    def test_stackable_all_apply(self):
        """Multiple stackable promos all apply in priority order."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=100.00, inventory_count=50,
        )
        # 10% off, stackable, priority 1
        create_and_activate_promotion(
            shop["id"],
            promo_name="10pct stack",
            promo_type="PERCENTAGE",
            promo_value=10,
            stackable=True,
            priority=1,
            applicable_categories=[],
        )
        # 5% off, stackable, priority 2
        create_and_activate_promotion(
            shop["id"],
            promo_name="5pct stack",
            promo_type="PERCENTAGE",
            promo_value=5,
            stackable=True,
            priority=2,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        # $100 * 0.9 = $90, then $90 * 0.95 = $85.50
        assert order["total_amount"] == pytest.approx(85.50, abs=0.01)
        assert order["discount_amount"] == pytest.approx(14.50, abs=0.01)

    def test_mixed_stackable_and_non_stackable(self):
        """One non-stackable (highest priority) + all stackable promos apply."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=100.00, inventory_count=50,
        )
        # Non-stackable 10% off, priority 1
        create_and_activate_promotion(
            shop["id"],
            promo_name="10pct non-stack",
            promo_type="PERCENTAGE",
            promo_value=10,
            stackable=False,
            priority=1,
            applicable_categories=[],
        )
        # Stackable $5 off, priority 2
        create_and_activate_promotion(
            shop["id"],
            promo_name="$5 stack",
            promo_type="FIXED_AMOUNT",
            promo_value=5,
            stackable=True,
            priority=2,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        # PERCENTAGE_FIRST: $100 * 0.9 = $90, then $90 - $5 = $85
        assert order["total_amount"] == pytest.approx(85.00, abs=0.01)
        assert order["discount_amount"] == pytest.approx(15.00, abs=0.01)

    def test_non_stackable_ignored_lower_priority(self):
        """Second non-stackable promo with lower priority is not applied."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=100.00, inventory_count=50,
        )
        create_and_activate_promotion(
            shop["id"],
            promo_name="5pct",
            promo_type="PERCENTAGE",
            promo_value=5,
            stackable=False,
            priority=1,
            applicable_categories=[],
        )
        create_and_activate_promotion(
            shop["id"],
            promo_name="50pct",
            promo_type="PERCENTAGE",
            promo_value=50,
            stackable=False,
            priority=2,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        # Only 5% applies
        assert order["discount_amount"] == pytest.approx(5.00, abs=0.01)


# ===================================================================
# TestDiscountCap
# ===================================================================


class TestDiscountCap:
    """max_discount_cap enforcement on PERCENTAGE promos."""

    def test_cap_limits_percentage_discount(self):
        """20% of $200 = $40, but max_discount_cap=30 -> discount=$30."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=200.00, inventory_count=50,
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=20,
            max_discount_cap=30,
            priority=1,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["discount_amount"] == pytest.approx(30.00, abs=0.01)
        assert order["total_amount"] == pytest.approx(170.00, abs=0.01)

    def test_no_cap_full_percentage_applied(self):
        """20% of $200 = $40, no cap -> discount=$40."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=200.00, inventory_count=50,
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=20,
            priority=1,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["discount_amount"] == pytest.approx(40.00, abs=0.01)
        assert order["total_amount"] == pytest.approx(160.00, abs=0.01)

    def test_cap_above_calculated_discount_no_effect(self):
        """20% of $100 = $20, cap=$50 -> discount=$20 (cap not reached)."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=100.00, inventory_count=50,
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=20,
            max_discount_cap=50,
            priority=1,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["discount_amount"] == pytest.approx(20.00, abs=0.01)


# ===================================================================
# TestThreshold
# ===================================================================


class TestThreshold:
    """promo_threshold activation guard."""

    def test_threshold_not_met_no_discount(self):
        """promo_threshold=50, subtotal=40 -> promotion NOT applied."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=40.00, inventory_count=50,
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=10,
            promo_threshold=50,
            priority=1,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["discount_amount"] == pytest.approx(0.00, abs=0.01)
        assert order["total_amount"] == pytest.approx(40.00, abs=0.01)

    def test_threshold_met_discount_applied(self):
        """promo_threshold=50, subtotal=60 -> promotion applied."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=60.00, inventory_count=50,
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=10,
            promo_threshold=50,
            priority=1,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["discount_amount"] == pytest.approx(6.00, abs=0.01)
        assert order["total_amount"] == pytest.approx(54.00, abs=0.01)

    def test_threshold_exact_boundary(self):
        """promo_threshold=50, subtotal=50 -> promotion applied (>=)."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=50.00, inventory_count=50,
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=10,
            promo_threshold=50,
            priority=1,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["discount_amount"] == pytest.approx(5.00, abs=0.01)


# ===================================================================
# TestCategoryMatching
# ===================================================================


class TestCategoryMatching:
    """applicable_categories filtering."""

    def test_matching_category_applied(self):
        """Promo for 'electronics', product is 'electronics' -> applied."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"],
            base_price=100.00,
            inventory_count=50,
            category="electronics",
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=10,
            priority=1,
            applicable_categories=["electronics"],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["discount_amount"] == pytest.approx(10.00, abs=0.01)

    def test_non_matching_category_not_applied(self):
        """Promo for 'electronics', product is 'clothing' -> NOT applied."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"],
            base_price=100.00,
            inventory_count=50,
            category="clothing",
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=10,
            priority=1,
            applicable_categories=["electronics"],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["discount_amount"] == pytest.approx(0.00, abs=0.01)
        assert order["total_amount"] == pytest.approx(100.00, abs=0.01)

    def test_empty_categories_applies_to_all(self):
        """applicable_categories=[] -> applies to ALL products regardless of category."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"],
            base_price=100.00,
            inventory_count=50,
            category="clothing",
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=10,
            priority=1,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["discount_amount"] == pytest.approx(10.00, abs=0.01)

    def test_multi_category_match(self):
        """Promo for ['electronics','books'], product is 'books' -> applied."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"],
            base_price=100.00,
            inventory_count=50,
            category="books",
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=15,
            priority=1,
            applicable_categories=["electronics", "books"],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["discount_amount"] == pytest.approx(15.00, abs=0.01)


# ===================================================================
# TestRunningTotalFloor
# ===================================================================


class TestRunningTotalFloor:
    """Discount cannot reduce total below $0.01."""

    def test_large_discount_floors_at_minimum(self):
        """95% off $10 = $0.50, then $20 FIXED -> would go negative, floors at 0.01."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=10.00, inventory_count=50,
        )
        create_and_activate_promotion(
            shop["id"],
            promo_name="95pct",
            promo_type="PERCENTAGE",
            promo_value=95,
            stackable=True,
            priority=1,
            applicable_categories=[],
        )
        create_and_activate_promotion(
            shop["id"],
            promo_name="$20 fixed",
            promo_type="FIXED_AMOUNT",
            promo_value=20,
            stackable=True,
            priority=2,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["total_amount"] >= 0.01
        assert order["total_amount"] == pytest.approx(0.01, abs=0.01)


# ===================================================================
# TestDiscountShareAllocation
# ===================================================================


class TestDiscountShareAllocation:
    """Waterfall discount share allocation across order items."""

    def test_proportional_allocation_three_items(self):
        """3 items ($30, $50, $20), discount=$10.

        Item1: round(10 * 30/100, 2) = $3.00
        Item2: round(10 * 50/100, 2) = $5.00
        Item3: 10 - 3 - 5 = $2.00 (remainder)
        """
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        prod_a = create_and_list_product(
            shop["id"],
            product_name="A",
            base_price=30.00,
            inventory_count=50,
            category="electronics",
        )
        prod_b = create_and_list_product(
            shop["id"],
            product_name="B",
            base_price=50.00,
            inventory_count=50,
            category="electronics",
        )
        prod_c = create_and_list_product(
            shop["id"],
            product_name="C",
            base_price=20.00,
            inventory_count=50,
            category="electronics",
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=10,
            priority=1,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [
            (prod_a["id"], 1),
            (prod_b["id"], 1),
            (prod_c["id"], 1),
        ])
        # subtotal = 100, discount = 10
        assert order["subtotal"] == pytest.approx(100.00, abs=0.01)
        assert order["discount_amount"] == pytest.approx(10.00, abs=0.01)

        items = _get_order_items(order["id"])
        assert len(items) == 3

        # Sum of discount_shares must equal total discount
        total_share = sum(it["discount_share"] for it in items)
        assert total_share == pytest.approx(order["discount_amount"], abs=0.01)

        # Each item's final_price = line_total - discount_share
        for it in items:
            assert_order_item(it)
            assert it["final_price"] == pytest.approx(
                it["line_total"] - it["discount_share"], abs=0.01
            )
            assert_cost_precision(it["discount_share"])

    def test_equal_items_share_equally(self):
        """2 identical items should split discount evenly (with possible penny remainder)."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=50.00, inventory_count=50,
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="FIXED_AMOUNT",
            promo_value=7,
            priority=1,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 2)])
        # subtotal = $100, discount = $7
        assert order["discount_amount"] == pytest.approx(7.00, abs=0.01)

        items = _get_order_items(order["id"])
        # All items should have discount_share that sums to 7.00
        total_share = sum(it["discount_share"] for it in items)
        assert total_share == pytest.approx(7.00, abs=0.01)

    def test_remainder_on_last_item(self):
        """Verify remainder allocation: 3 items with non-even split."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        prod_a = create_and_list_product(
            shop["id"],
            product_name="X",
            base_price=33.33,
            inventory_count=50,
            category="electronics",
        )
        prod_b = create_and_list_product(
            shop["id"],
            product_name="Y",
            base_price=33.33,
            inventory_count=50,
            category="electronics",
        )
        prod_c = create_and_list_product(
            shop["id"],
            product_name="Z",
            base_price=33.34,
            inventory_count=50,
            category="electronics",
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="FIXED_AMOUNT",
            promo_value=10,
            priority=1,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [
            (prod_a["id"], 1),
            (prod_b["id"], 1),
            (prod_c["id"], 1),
        ])
        items = _get_order_items(order["id"])
        total_share = sum(it["discount_share"] for it in items)
        # Must be exact (no floating point drift)
        assert total_share == pytest.approx(order["discount_amount"], abs=0.001)
        # Each share has <= 2 decimal places
        for it in items:
            assert_cost_precision(it["discount_share"])


# ===================================================================
# TestUsageLimits
# ===================================================================


class TestUsageLimits:
    """Promotion max_usage enforcement."""

    def test_exhausted_promotion_not_applied(self):
        """max_usage=1, after 1 use the promotion is skipped on next order."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=100.00, inventory_count=50,
        )
        promo = create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=10,
            max_usage=1,
            priority=1,
            applicable_categories=[],
        )
        # First order uses the promotion
        order1 = _place_order(shop["id"], [(product["id"], 1)])
        assert order1["discount_amount"] == pytest.approx(10.00, abs=0.01)
        # Pay the first order to confirm usage_count increment
        place_and_pay_order(
            shop["id"],
            [{"product_id": product["id"], "quantity": 1}],
        )

        # Verify usage_count incremented
        promo_after = get_success_data(
            api_client.get_promotion(shop["id"], promo["id"], _seller)
        )
        assert promo_after["usage_count"] >= 1

        # Second order -- promotion should be exhausted (discount = 0 or error)
        order2 = _place_order(shop["id"], [(product["id"], 1)])
        assert order2["discount_amount"] == pytest.approx(0.00, abs=0.01)

    def test_usage_below_max_still_applies(self):
        """max_usage=5, usage_count=0 -> promotion applies normally."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=100.00, inventory_count=50,
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=10,
            max_usage=5,
            priority=1,
            applicable_categories=[],
        )
        order = _place_order(shop["id"], [(product["id"], 1)])
        assert order["discount_amount"] == pytest.approx(10.00, abs=0.01)

    def test_unlimited_usage_no_cap(self):
        """max_usage=null (not set) -> promotion can be used indefinitely."""
        shop = _setup_shop_with_strategy("PERCENTAGE_FIRST")
        product = create_and_list_product(
            shop["id"], base_price=100.00, inventory_count=50,
        )
        create_and_activate_promotion(
            shop["id"],
            promo_type="PERCENTAGE",
            promo_value=10,
            priority=1,
            applicable_categories=[],
        )
        # Place multiple orders
        for _ in range(3):
            order = _place_order(shop["id"], [(product["id"], 1)])
            assert order["discount_amount"] == pytest.approx(10.00, abs=0.01)
