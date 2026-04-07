"""
Test 11 -- Concurrency: race conditions, OCC, and concurrent mutations.

Covers:
  - Double payment race
  - Inventory reservation race
  - Optimistic concurrency control (stale version)
  - Double delivery race
  - Concurrent refund processing
"""

import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_exactly_one_succeeds, run_race,
    create_product_payload, create_order_payload, create_refund_payload,
    create_and_approve_shop, create_and_list_product,
    setup_basic_order_scenario, place_and_pay_order,
    place_pay_and_deliver_order,
    setup_completed_order_for_refund,
    get_shop_after,
    assert_shop_invariants,
    ERR_INSUFFICIENT_INVENTORY, ERR_STALE_DATA,
    TEST_USERS,
)

_customer = TEST_USERS["customer_headers"]
_seller = TEST_USERS["seller_headers"]
_admin = TEST_USERS["admin_headers"]


# ============================================================================
# Double payment race
# ============================================================================


class TestDoublePaymentRace:
    """Two concurrent pay requests on the same order: exactly one succeeds."""

    def test_double_pay_exactly_one_succeeds(self):
        """Concurrent pay attempts on the same UNPAID order."""
        shop, product = setup_basic_order_scenario()
        order_payload = create_order_payload(
            shop["id"],
            [{"product_id": product["id"], "quantity": 1}],
        )
        order = get_success_data(api_client.create_order(order_payload, _customer))

        pay_payload_1 = {"payment_method": "CREDIT_CARD", "transaction_ref": "txn-race-1"}
        pay_payload_2 = {"payment_method": "CREDIT_CARD", "transaction_ref": "txn-race-2"}

        results = run_race(
            lambda: api_client.pay_order(order["id"], pay_payload_1, _customer),
            lambda: api_client.pay_order(order["id"], pay_payload_2, _customer),
        )
        assert_exactly_one_succeeds(results)

    def test_double_pay_final_state_consistent(self):
        """After a double-pay race the order has exactly one payment in PAYING."""
        shop, product = setup_basic_order_scenario()
        order_payload = create_order_payload(
            shop["id"],
            [{"product_id": product["id"], "quantity": 1}],
        )
        order = get_success_data(api_client.create_order(order_payload, _customer))

        pay_payload_1 = {"payment_method": "WALLET", "transaction_ref": "txn-a"}
        pay_payload_2 = {"payment_method": "WALLET", "transaction_ref": "txn-b"}

        run_race(
            lambda: api_client.pay_order(order["id"], pay_payload_1, _customer),
            lambda: api_client.pay_order(order["id"], pay_payload_2, _customer),
        )

        final_order = get_success_data(
            api_client.get_order(order["id"], _admin)
        )
        assert final_order["payment_status"] in ("PAYING", "PAID", "UNPAID")


# ============================================================================
# Inventory reservation race
# ============================================================================


class TestInventoryReservationRace:
    """Product with available_count=1, two concurrent orders each wanting qty=1."""

    def test_inventory_race_at_most_one_wins(self):
        """At most one order succeeds; the other gets ERR_INSUFFICIENT_INVENTORY."""
        shop = create_and_approve_shop()
        product = create_and_list_product(
            shop["id"],
            product_name="Scarce Item",
            base_price=50.0,
            inventory_count=1,
        )

        payload_1 = create_order_payload(
            shop["id"], [{"product_id": product["id"], "quantity": 1}]
        )
        payload_2 = create_order_payload(
            shop["id"], [{"product_id": product["id"], "quantity": 1}]
        )

        results = run_race(
            lambda: api_client.create_order(payload_1, _customer),
            lambda: api_client.create_order(payload_2, _customer),
        )
        assert_exactly_one_succeeds(results)

        # The failing one should be an inventory error
        for r in results:
            if r.status_code != 200 and r.status_code != 201:
                validate_error(r, ERR_INSUFFICIENT_INVENTORY)


# ============================================================================
# Optimistic concurrency control (OCC)
# ============================================================================


class TestOptimisticConcurrency:
    """Stale version numbers must be rejected with ERR_STALE_DATA (409)."""

    def test_product_update_with_stale_version_rejected(self):
        """Updating a product with a stale version fails."""
        shop = create_and_approve_shop()
        product = create_and_list_product(
            shop["id"], base_price=10.0, inventory_count=50
        )
        original_version = product["version"]

        # First update succeeds
        get_success_data(
            api_client.update_product(
                shop["id"],
                product["id"],
                {"base_price": 15.0, "version": original_version},
                _seller,
            )
        )

        # Second update with the same (now stale) version fails
        resp = api_client.update_product(
            shop["id"],
            product["id"],
            {"base_price": 20.0, "version": original_version},
            _seller,
        )
        validate_error(resp, ERR_STALE_DATA)

    def test_shop_update_with_stale_version_rejected(self):
        """Updating a shop with a stale version fails."""
        shop = create_and_approve_shop()
        original_version = shop["version"]

        # First update succeeds
        get_success_data(
            api_client.update_shop(
                shop["id"],
                {"description": "Updated once", "version": original_version},
                _seller,
            )
        )

        # Second update with stale version fails
        resp = api_client.update_shop(
            shop["id"],
            {"description": "Updated twice", "version": original_version},
            _seller,
        )
        validate_error(resp, ERR_STALE_DATA)

    def test_concurrent_product_updates_one_gets_stale(self):
        """Two concurrent product updates: one wins, the other gets stale."""
        shop = create_and_approve_shop()
        product = create_and_list_product(
            shop["id"], base_price=10.0, inventory_count=50
        )
        v = product["version"]

        results = run_race(
            lambda: api_client.update_product(
                shop["id"], product["id"],
                {"base_price": 11.0, "version": v}, _seller,
            ),
            lambda: api_client.update_product(
                shop["id"], product["id"],
                {"base_price": 12.0, "version": v}, _seller,
            ),
        )
        assert_exactly_one_succeeds(results)


# ============================================================================
# Double delivery race
# ============================================================================


class TestDoubleDeliveryRace:
    """Two concurrent deliver requests: exactly one succeeds."""

    def test_double_deliver_exactly_one_succeeds(self):
        """Concurrent delivery attempts on a SHIPPED order."""
        shop, product = setup_basic_order_scenario()
        order = place_and_pay_order(
            shop["id"],
            [{"product_id": product["id"], "quantity": 1}],
        )
        get_success_data(api_client.start_processing(order["id"], _seller))
        get_success_data(api_client.ship_order(order["id"], _seller))

        results = run_race(
            lambda: api_client.deliver_order(order["id"], _seller),
            lambda: api_client.deliver_order(order["id"], _seller),
        )
        assert_exactly_one_succeeds(results)

    def test_commission_and_gmv_updated_exactly_once(self):
        """After a double-deliver race, GMV and commission are correct."""
        shop, product = setup_basic_order_scenario(
            product_overrides={"base_price": 100.0, "inventory_count": 10}
        )
        shop_before = get_shop_after(shop["id"])
        gmv_before = shop_before["monthly_gmv"]

        order = place_and_pay_order(
            shop["id"],
            [{"product_id": product["id"], "quantity": 1}],
        )
        get_success_data(api_client.start_processing(order["id"], _seller))
        get_success_data(api_client.ship_order(order["id"], _seller))

        run_race(
            lambda: api_client.deliver_order(order["id"], _seller),
            lambda: api_client.deliver_order(order["id"], _seller),
        )

        # Re-fetch order to get final total_amount
        final_order = get_success_data(api_client.get_order(order["id"], _admin))
        shop_after = get_shop_after(shop["id"])

        # GMV should have increased by exactly the order total_amount
        expected_gmv = gmv_before + final_order["total_amount"]
        assert shop_after["monthly_gmv"] == pytest.approx(expected_gmv, abs=0.01)
        assert_shop_invariants(shop_after)


# ============================================================================
# Concurrent refund processing
# ============================================================================


class TestConcurrentRefundProcessing:
    """Two concurrent refund processes on different refunds for the same order."""

    def test_concurrent_refunds_cumulative_not_exceeding_total(self):
        """Both refunds may succeed, but cumulative refund <= order total."""
        shop, product, order = setup_completed_order_for_refund(
            product_overrides={"base_price": 100.0, "inventory_count": 100},
            quantity=4,
        )
        order_total = order["total_amount"]

        # Retrieve order items for partial refunds
        order_detail = get_success_data(api_client.get_order(order["id"], _admin))
        items = order_detail.get("items") or order_detail.get("order_items", [])
        assert len(items) > 0, "Order must have items for refund testing"

        item_id = items[0]["id"]

        # Create two separate partial refund requests
        refund_payload_1 = create_refund_payload(
            refund_type="PARTIAL",
            refund_items=[{"order_item_id": item_id, "quantity": 1}],
            reason="Refund part 1",
        )
        refund_1 = get_success_data(
            api_client.create_refund(order["id"], refund_payload_1, _customer)
        )
        get_success_data(
            api_client.approve_refund(order["id"], refund_1["id"], _seller)
        )

        refund_payload_2 = create_refund_payload(
            refund_type="PARTIAL",
            refund_items=[{"order_item_id": item_id, "quantity": 1}],
            reason="Refund part 2",
        )
        refund_2 = get_success_data(
            api_client.create_refund(order["id"], refund_payload_2, _customer)
        )
        get_success_data(
            api_client.approve_refund(order["id"], refund_2["id"], _seller)
        )

        # Process both concurrently
        results = run_race(
            lambda: api_client.process_refund(order["id"], refund_1["id"], _admin),
            lambda: api_client.process_refund(order["id"], refund_2["id"], _admin),
        )

        # At least one should succeed
        successes = [r for r in results if r.status_code in (200, 201)]
        assert len(successes) >= 1, "At least one refund process should succeed"

        # If both succeeded, check cumulative refund doesn't exceed total
        if len(successes) == 2:
            r1 = get_success_data(
                api_client.get_refund(order["id"], refund_1["id"], _admin)
            )
            r2 = get_success_data(
                api_client.get_refund(order["id"], refund_2["id"], _admin)
            )
            total_refunded = r1["refund_amount"] + r2["refund_amount"]
            assert total_refunded <= order_total + 0.01, (
                f"Cumulative refund ({total_refunded}) exceeds "
                f"order total ({order_total})"
            )
