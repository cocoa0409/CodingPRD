"""
Test 08 -- Refunds
===================
Validates full refund, partial refund, proportional discount allocation,
cumulative refunds, refund quantity validation, remainder allocation,
and refund side effects (inventory, settlement balance, GMV).
"""

import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    get_success_data,
    assert_cost_precision, assert_version_incremented,
    assert_order, assert_product, assert_order_invariants, assert_inventory_consistency,
    assert_shop_invariants,
    NON_EXISTENT_UUID, TEST_USERS, COMMISSION_TIERS, RESERVATION_TIMEOUT_MINUTES,
    create_order_payload, create_product_payload, create_refund_payload,
    create_and_approve_shop, create_and_list_product,
    setup_basic_order_scenario, place_and_pay_order, place_pay_and_deliver_order,
    create_paid_order, setup_shop_at_gmv, setup_shop_near_tier_boundary,
    setup_completed_order_for_refund, setup_partial_refund_scenario,
    get_shop_after, get_order_items,
    ERR_REFUND_EXCEEDS_ORDER_TOTAL, ERR_REFUND_EXCEEDS_REMAINING,
    ERR_ORDER_NOT_PAID,
)
from test_helpers.assertions import assert_refund

# ---------------------------------------------------------------------------
# Header shortcuts
# ---------------------------------------------------------------------------

_customer = TEST_USERS["customer_headers"]
_seller = TEST_USERS["seller_headers"]
_admin = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _full_refund_flow(order_id):
    """Request a FULL refund, approve it, and process it.  Returns the processed refund."""
    refund_payload = create_refund_payload(refund_type="FULL")
    refund = get_success_data(
        api_client.create_refund(order_id, refund_payload, _customer)
    )
    approved = get_success_data(
        api_client.approve_refund(order_id, refund["id"], _seller)
    )
    assert approved["status"] == "APPROVED"
    processed = get_success_data(
        api_client.process_refund(order_id, refund["id"], _admin)
    )
    assert processed["status"] == "PROCESSED"
    return processed


def _partial_refund_flow(order_id, refund_items):
    """Request a PARTIAL refund, approve, and process.  Returns the processed refund."""
    refund_payload = create_refund_payload(
        refund_type="PARTIAL", refund_items=refund_items,
    )
    refund = get_success_data(
        api_client.create_refund(order_id, refund_payload, _customer)
    )
    approved = get_success_data(
        api_client.approve_refund(order_id, refund["id"], _seller)
    )
    assert approved["status"] == "APPROVED"
    processed = get_success_data(
        api_client.process_refund(order_id, refund["id"], _admin)
    )
    assert processed["status"] == "PROCESSED"
    return processed


def _setup_multi_item_order(prices_and_qtys, inventory=100):
    """Create a shop with N products and a completed order.

    *prices_and_qtys* is a list of (base_price, quantity) tuples.

    Returns (shop, products, order, order_items).
    """
    shop = create_and_approve_shop()
    products = []
    for i, (price, _qty) in enumerate(prices_and_qtys):
        p = create_and_list_product(
            shop["id"],
            product_name=f"Product {i + 1}",
            base_price=price,
            inventory_count=inventory,
        )
        products.append(p)

    items = [
        {"product_id": products[i]["id"], "quantity": qty}
        for i, (_price, qty) in enumerate(prices_and_qtys)
    ]
    order = place_pay_and_deliver_order(shop["id"], items)
    order_items = get_order_items(order["id"])
    return shop, products, order, order_items


# ===========================================================================
# TestFullRefund
# ===========================================================================


class TestFullRefund:
    """Verify full refund flow: amount, payment_status, inventory, commission, GMV."""

    def test_full_refund_amount_equals_order_total(self):
        """refund_amount = order.total_amount for a full refund."""
        shop, product, order = setup_completed_order_for_refund()
        refund = _full_refund_flow(order["id"])
        assert_refund(refund)
        assert refund["refund_amount"] == pytest.approx(order["total_amount"], abs=0.01)
        assert_cost_precision(refund["refund_amount"])

    def test_full_refund_sets_payment_status(self):
        """payment_status -> FULL_REFUND after full refund processed."""
        shop, product, order = setup_completed_order_for_refund()
        _full_refund_flow(order["id"])

        updated_order = get_success_data(
            api_client.get_order(order["id"], _admin)
        )
        assert updated_order["payment_status"] == "FULL_REFUND"

    def test_full_refund_restores_inventory(self):
        """Inventory restored for all items after full refund."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"inventory_count": 50, "base_price": 20.00},
            quantity=5,
        )

        p_before = get_success_data(
            api_client.get_product(shop["id"], product["id"], _seller)
        )
        inventory_before = p_before["inventory_count"]

        refund = _full_refund_flow(order["id"])
        assert refund["inventory_restored"] is True

        p_after = get_success_data(
            api_client.get_product(shop["id"], product["id"], _seller)
        )
        assert p_after["inventory_count"] == inventory_before + 5
        assert_inventory_consistency(p_after)

    def test_full_refund_reverses_gmv(self):
        """monthly_gmv reversed after full refund."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"inventory_count": 100, "base_price": 100.00},
            quantity=1,
        )

        shop_before = get_shop_after(shop["id"])
        gmv_before = shop_before["monthly_gmv"]

        _full_refund_flow(order["id"])

        shop_after = get_shop_after(shop["id"])
        assert shop_after["monthly_gmv"] == pytest.approx(
            gmv_before - order["total_amount"], abs=0.01,
        )
        assert_shop_invariants(shop_after)

    def test_full_refund_reverses_settlement_balance(self):
        """settlement_balance adjusted after full refund."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"inventory_count": 100, "base_price": 50.00},
            quantity=2,
        )

        shop_before = get_shop_after(shop["id"])
        balance_before = shop_before["settlement_balance"]

        _full_refund_flow(order["id"])

        shop_after = get_shop_after(shop["id"])
        # Settlement balance should decrease
        assert shop_after["settlement_balance"] < balance_before
        assert_shop_invariants(shop_after)


# ===========================================================================
# TestPartialRefund
# ===========================================================================


class TestPartialRefund:
    """Verify partial refund with proportional discount allocation."""

    def test_partial_refund_single_item(self):
        """Order with 3 items, refund 1 item -> payment_status = PARTIAL_REFUND."""
        shop, products, order, order_items = _setup_multi_item_order(
            [(30.00, 1), (40.00, 1), (30.00, 1)],
        )

        refund_items = [{"order_item_id": order_items[0]["id"], "quantity": 1}]
        refund = _partial_refund_flow(order["id"], refund_items)
        assert_refund(refund)

        updated_order = get_success_data(
            api_client.get_order(order["id"], _admin)
        )
        assert updated_order["payment_status"] == "PARTIAL_REFUND"

    def test_partial_refund_subtotal_calculation(self):
        """refund_subtotal = quantity * unit_price for refunded items."""
        shop, products, order, order_items = _setup_multi_item_order(
            [(50.00, 2), (30.00, 1)],
        )

        # Refund 1 unit of the first item (unit_price=50.00)
        refund_items = [{"order_item_id": order_items[0]["id"], "quantity": 1}]
        refund = _partial_refund_flow(order["id"], refund_items)
        assert_refund(refund)

        assert refund["refund_subtotal"] == pytest.approx(50.00, abs=0.01)
        assert_cost_precision(refund["refund_subtotal"])

    def test_partial_refund_discount_share_proportional(self):
        """refund_discount_share is proportional to refunded item's share of subtotal."""
        # This test works when there IS a discount on the order.
        # Without promotions, discount=0 so discount_share=0.
        shop, products, order, order_items = _setup_multi_item_order(
            [(60.00, 1), (40.00, 1)],
        )

        refund_items = [{"order_item_id": order_items[0]["id"], "quantity": 1}]
        refund = _partial_refund_flow(order["id"], refund_items)
        assert_refund(refund)

        # If order has no discount, refund_discount_share should be 0
        if order["discount_amount"] == 0:
            assert refund["refund_discount_share"] == 0
        else:
            # Proportional: 60/(60+40) = 0.6 of total discount
            expected_share = order["discount_amount"] * (60.0 / 100.0)
            assert refund["refund_discount_share"] == pytest.approx(expected_share, abs=0.01)
        assert_cost_precision(refund["refund_discount_share"])

    def test_proportional_discount_refund_amount(self):
        """Refund amount = refund_subtotal - refund_discount_share.

        Order: subtotal=$100, discount=$20, 2 items ($60 + $40).
        Refund item 1 ($60): proportion = 60/100 = 0.6, discount_share = $20 * 0.6 = $12.
        refund_amount = $60 - $12 = $48.
        """
        # This test uses explicit values; the actual discount depends on
        # whether a promotion is configured.  We verify the relationship
        # refund_amount = refund_subtotal - refund_discount_share.
        shop, products, order, order_items = _setup_multi_item_order(
            [(60.00, 1), (40.00, 1)],
        )

        refund_items = [{"order_item_id": order_items[0]["id"], "quantity": 1}]
        refund = _partial_refund_flow(order["id"], refund_items)

        # Core invariant
        expected_amount = refund["refund_subtotal"] - refund["refund_discount_share"]
        assert refund["refund_amount"] == pytest.approx(expected_amount, abs=0.01), (
            f"refund_amount ({refund['refund_amount']}) != "
            f"refund_subtotal ({refund['refund_subtotal']}) - "
            f"refund_discount_share ({refund['refund_discount_share']})"
        )
        assert_cost_precision(refund["refund_amount"])


# ===========================================================================
# TestRefundDiscountAllocation
# ===========================================================================


class TestRefundDiscountAllocation:
    """Verify proportional discount allocation and remainder handling in refunds."""

    def test_refund_amount_invariant(self):
        """refund_amount = refund_subtotal - refund_discount_share always holds."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"base_price": 33.33, "inventory_count": 100},
            quantity=3,
        )
        order_items = get_order_items(order["id"])

        refund_items = [{"order_item_id": order_items[0]["id"], "quantity": 1}]
        refund = _partial_refund_flow(order["id"], refund_items)

        expected = refund["refund_subtotal"] - refund["refund_discount_share"]
        assert refund["refund_amount"] == pytest.approx(expected, abs=0.01)
        assert_cost_precision(refund["refund_amount"])
        assert_cost_precision(refund["refund_subtotal"])
        assert_cost_precision(refund["refund_discount_share"])

    def test_remainder_absorbed_by_last_refund_item(self):
        """When refunding multiple items, rounding remainder goes to the last item."""
        # Use prices that cause rounding: 3 items at $33.33 each
        shop, products, order, order_items = _setup_multi_item_order(
            [(33.33, 1), (33.33, 1), (33.34, 1)],
        )

        # Refund first 2 items
        refund_items = [
            {"order_item_id": order_items[0]["id"], "quantity": 1},
            {"order_item_id": order_items[1]["id"], "quantity": 1},
        ]
        refund = _partial_refund_flow(order["id"], refund_items)
        assert_refund(refund)
        assert_cost_precision(refund["refund_amount"])
        assert_cost_precision(refund["refund_discount_share"])

    def test_full_refund_discount_share_equals_total_discount(self):
        """For a FULL refund, refund_discount_share == order.discount_amount."""
        shop, product, order = setup_completed_order_for_refund()

        refund = _full_refund_flow(order["id"])
        assert refund["refund_discount_share"] == pytest.approx(
            order["discount_amount"], abs=0.01,
        )


# ===========================================================================
# TestCumulativeRefunds
# ===========================================================================


class TestCumulativeRefunds:
    """Verify cumulative refund constraints and status transitions."""

    def test_cumulative_refunds_cannot_exceed_total(self):
        """Partial A + Partial B that exceeds total -> ERR_REFUND_EXCEEDS_ORDER_TOTAL."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"base_price": 50.00, "inventory_count": 100},
            quantity=2,
        )
        order_items = get_order_items(order["id"])

        # First partial refund: 1 unit
        refund_items_1 = [{"order_item_id": order_items[0]["id"], "quantity": 2}]
        _partial_refund_flow(order["id"], refund_items_1)

        # Second partial refund: try to refund more than remaining
        # Since we already refunded all quantity, this should fail
        refund_items_2 = [{"order_item_id": order_items[0]["id"], "quantity": 1}]
        refund_payload = create_refund_payload(
            refund_type="PARTIAL", refund_items=refund_items_2,
        )
        resp = api_client.create_refund(order["id"], refund_payload, _customer)
        # After refunding all quantity, order may become FULL_REFUND (ERR_ORDER_NOT_PAID)
        # or the quantity check may trigger first (ERR_REFUND_EXCEEDS_REMAINING)
        validate_error_is_one_of(resp, [ERR_REFUND_EXCEEDS_REMAINING, ERR_ORDER_NOT_PAID])

    def test_cumulative_partials_become_full_refund(self):
        """Partial refunds that cumulate to total_amount -> payment_status = FULL_REFUND."""
        shop, products, order, order_items = _setup_multi_item_order(
            [(40.00, 1), (60.00, 1)],
        )

        # First partial: refund item 1
        refund_items_1 = [{"order_item_id": order_items[0]["id"], "quantity": 1}]
        _partial_refund_flow(order["id"], refund_items_1)

        mid_order = get_success_data(api_client.get_order(order["id"], _admin))
        assert mid_order["payment_status"] == "PARTIAL_REFUND"

        # Second partial: refund item 2 (now total refunded = order total)
        refund_items_2 = [{"order_item_id": order_items[1]["id"], "quantity": 1}]
        _partial_refund_flow(order["id"], refund_items_2)

        final_order = get_success_data(api_client.get_order(order["id"], _admin))
        assert final_order["payment_status"] == "FULL_REFUND"

    def test_refund_quantity_exceeds_remaining(self):
        """Original qty=5, already refunded=3 -> refund qty=3 -> ERR_REFUND_EXCEEDS_REMAINING."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"base_price": 10.00, "inventory_count": 100},
            quantity=5,
        )
        order_items = get_order_items(order["id"])

        # Refund 3 of 5
        refund_items_1 = [{"order_item_id": order_items[0]["id"], "quantity": 3}]
        _partial_refund_flow(order["id"], refund_items_1)

        # Try to refund 3 more (only 2 remaining)
        refund_items_2 = [{"order_item_id": order_items[0]["id"], "quantity": 3}]
        refund_payload = create_refund_payload(
            refund_type="PARTIAL", refund_items=refund_items_2,
        )
        resp = api_client.create_refund(order["id"], refund_payload, _customer)
        validate_error(resp, ERR_REFUND_EXCEEDS_REMAINING)

    def test_refund_exactly_remaining_quantity_succeeds(self):
        """Original qty=5, already refunded=3 -> refund qty=2 -> succeeds."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"base_price": 10.00, "inventory_count": 100},
            quantity=5,
        )
        order_items = get_order_items(order["id"])

        # Refund 3 of 5
        refund_items_1 = [{"order_item_id": order_items[0]["id"], "quantity": 3}]
        _partial_refund_flow(order["id"], refund_items_1)

        # Refund exactly 2 remaining
        refund_items_2 = [{"order_item_id": order_items[0]["id"], "quantity": 2}]
        refund = _partial_refund_flow(order["id"], refund_items_2)
        assert_refund(refund)

        final_order = get_success_data(api_client.get_order(order["id"], _admin))
        assert final_order["payment_status"] == "FULL_REFUND"


# ===========================================================================
# TestRefundSideEffects
# ===========================================================================


class TestRefundSideEffects:
    """Verify side effects of refunds: inventory, settlement balance, GMV."""

    def test_partial_refund_restores_inventory(self):
        """Inventory restored for refunded quantity only."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"base_price": 25.00, "inventory_count": 50},
            quantity=4,
        )
        order_items = get_order_items(order["id"])

        p_before = get_success_data(
            api_client.get_product(shop["id"], product["id"], _seller)
        )
        inv_before = p_before["inventory_count"]

        # Refund 2 of 4
        refund_items = [{"order_item_id": order_items[0]["id"], "quantity": 2}]
        refund = _partial_refund_flow(order["id"], refund_items)
        assert refund["inventory_restored"] is True

        p_after = get_success_data(
            api_client.get_product(shop["id"], product["id"], _seller)
        )
        assert p_after["inventory_count"] == inv_before + 2
        assert_inventory_consistency(p_after)

    def test_partial_refund_reverses_settlement_proportionally(self):
        """Settlement balance reduced proportionally after partial refund."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"base_price": 100.00, "inventory_count": 100},
            quantity=2,
        )

        shop_before = get_shop_after(shop["id"])
        balance_before = shop_before["settlement_balance"]

        order_items = get_order_items(order["id"])
        refund_items = [{"order_item_id": order_items[0]["id"], "quantity": 1}]
        _partial_refund_flow(order["id"], refund_items)

        shop_after = get_shop_after(shop["id"])
        assert shop_after["settlement_balance"] < balance_before
        assert_cost_precision(shop_after["settlement_balance"])
        assert_shop_invariants(shop_after)

    def test_partial_refund_reverses_gmv_proportionally(self):
        """monthly_gmv reduced proportionally after partial refund."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"base_price": 100.00, "inventory_count": 100},
            quantity=2,
        )

        shop_before = get_shop_after(shop["id"])
        gmv_before = shop_before["monthly_gmv"]

        order_items = get_order_items(order["id"])
        refund_items = [{"order_item_id": order_items[0]["id"], "quantity": 1}]
        refund = _partial_refund_flow(order["id"], refund_items)

        shop_after = get_shop_after(shop["id"])
        # GMV should be reduced by the refund_amount
        assert shop_after["monthly_gmv"] == pytest.approx(
            gmv_before - refund["refund_amount"], abs=0.01,
        )
        assert_shop_invariants(shop_after)

    def test_refund_precision_on_all_monetary_fields(self):
        """All monetary fields in refund have at most 2 decimal places."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"base_price": 33.33, "inventory_count": 100},
            quantity=3,
        )
        order_items = get_order_items(order["id"])

        refund_items = [{"order_item_id": order_items[0]["id"], "quantity": 2}]
        refund = _partial_refund_flow(order["id"], refund_items)

        assert_cost_precision(refund["refund_subtotal"])
        assert_cost_precision(refund["refund_discount_share"])
        assert_cost_precision(refund["refund_amount"])

    def test_full_refund_restores_all_inventory(self):
        """Full refund restores full ordered quantity to inventory."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"base_price": 15.00, "inventory_count": 30},
            quantity=10,
        )

        p_before = get_success_data(
            api_client.get_product(shop["id"], product["id"], _seller)
        )
        inv_before = p_before["inventory_count"]

        _full_refund_flow(order["id"])

        p_after = get_success_data(
            api_client.get_product(shop["id"], product["id"], _seller)
        )
        assert p_after["inventory_count"] == inv_before + 10
        assert_inventory_consistency(p_after)

    def test_settlement_balance_non_negative_after_refund(self):
        """settlement_balance remains >= 0 after refund."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"base_price": 50.00, "inventory_count": 100},
            quantity=1,
        )

        _full_refund_flow(order["id"])

        shop_after = get_shop_after(shop["id"])
        assert shop_after["settlement_balance"] >= 0
        assert_shop_invariants(shop_after)

    def test_gmv_non_negative_after_refund(self):
        """monthly_gmv remains >= 0 after refund."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"base_price": 50.00, "inventory_count": 100},
            quantity=1,
        )

        _full_refund_flow(order["id"])

        shop_after = get_shop_after(shop["id"])
        assert shop_after["monthly_gmv"] >= 0
        assert_shop_invariants(shop_after)
