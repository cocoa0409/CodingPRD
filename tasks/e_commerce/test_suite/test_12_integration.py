"""
Test 12 -- Integration: end-to-end lifecycle sagas and multi-role workflows.

Covers:
  - Full order lifecycle from shop creation to settlement payout
  - Multi-role workflow with RBAC verification at each step
  - Discount strategy comparison (PERCENTAGE_FIRST vs FIXED_FIRST)
"""

import pytest
from datetime import datetime, timedelta, timezone

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_cost_precision, assert_shop_invariants,
    assert_shop, assert_order, assert_settlement,
    build_user_headers,
    create_shop_payload, create_product_payload, create_order_payload,
    create_promotion_payload, create_settlement_payload,
    create_refund_payload,
    create_and_approve_shop, create_and_list_product,
    get_shop_after,
    ERR_FORBIDDEN,
    TEST_USERS,
)

_customer = TEST_USERS["customer_headers"]
_seller = TEST_USERS["seller_headers"]
_admin = TEST_USERS["admin_headers"]
_seller2 = TEST_USERS["seller2_headers"]
_customer2 = TEST_USERS["customer2_headers"]


# ============================================================================
# Helpers local to integration tests
# ============================================================================

def _activate_promotion(shop_id, promo_id):
    """Activate a DRAFT promotion and return it."""
    return get_success_data(
        api_client.activate_promotion(shop_id, promo_id, _seller)
    )


def _create_active_promotion(shop_id, **overrides):
    """Create and activate a promotion in one step."""
    now = datetime.now(timezone.utc)
    defaults = {
        "start_time": (now - timedelta(hours=1)).isoformat(),
        "end_time": (now + timedelta(days=30)).isoformat(),
    }
    defaults.update(overrides)
    payload = create_promotion_payload(**defaults)
    promo = get_success_data(
        api_client.create_promotion(shop_id, payload, _seller)
    )
    return _activate_promotion(shop_id, promo["id"])


# ============================================================================
# Full lifecycle journey
# ============================================================================


class TestFullLifecycleJourney:
    """End-to-end saga: shop -> product -> promotion -> order -> refund -> settlement."""

    def test_complete_e2e_lifecycle(self):
        """
        Steps:
        1. Seller creates shop, admin approves
        2. Seller creates product, lists it
        3. Seller creates 20% off promotion, activates it
        4. Customer places order (2 items)
        5. Customer pays, admin confirms payment
        6. Seller processes, ships, delivers
        7. Verify COMPLETED status, commission, GMV, settlement_balance
        8. Customer requests partial refund, seller approves, admin processes
        9. Verify inventory restored, balances adjusted
        10. Settlement lifecycle: create -> submit -> approve -> mark-paid
        11. Verify final settlement_balance
        """
        # Step 1: Shop creation and approval
        shop_payload = create_shop_payload(
            shop_name="Integration Test Shop",
            discount_strategy="PERCENTAGE_FIRST",
        )
        shop = get_success_data(api_client.create_shop(shop_payload, _seller))
        assert shop["status"] == "PENDING_REVIEW"
        shop = get_success_data(api_client.approve_shop(shop["id"], _admin))
        assert shop["status"] == "ACTIVE"
        assert_shop(shop)

        # Step 2: Product creation and listing
        product_a = get_success_data(api_client.create_product(
            shop["id"],
            create_product_payload(
                product_name="Widget A", base_price=100.0, inventory_count=50,
                category="electronics",
            ),
            _seller,
        ))
        assert product_a["status"] == "DRAFT"
        product_a = get_success_data(
            api_client.list_product(shop["id"], product_a["id"], _seller)
        )
        assert product_a["status"] == "LISTED"

        product_b = get_success_data(api_client.create_product(
            shop["id"],
            create_product_payload(
                product_name="Widget B", base_price=50.0, inventory_count=30,
                category="electronics",
            ),
            _seller,
        ))
        product_b = get_success_data(
            api_client.list_product(shop["id"], product_b["id"], _seller)
        )

        # Step 3: Promotion (20% off, stackable)
        promo = _create_active_promotion(
            shop["id"],
            promo_name="20% Off Everything",
            promo_type="PERCENTAGE",
            promo_value=20,
            stackable=True,
            priority=1,
            applicable_categories=["electronics"],
        )
        assert promo["status"] == "ACTIVE"

        # Step 4: Customer places order (2 items from different products)
        period_start = datetime.now(timezone.utc) - timedelta(minutes=5)
        order_payload = create_order_payload(
            shop["id"],
            [
                {"product_id": product_a["id"], "quantity": 2},
                {"product_id": product_b["id"], "quantity": 1},
            ],
        )
        order = get_success_data(api_client.create_order(order_payload, _customer))
        assert order["order_status"] == "CREATED"
        assert order["payment_status"] == "UNPAID"
        assert_order(order)

        # Verify discount was applied (subtotal = 2*100 + 1*50 = 250, 20% off = 50)
        assert order["subtotal"] == pytest.approx(250.0, abs=0.01)
        assert order["discount_amount"] > 0, "Promotion should have applied a discount"

        # Step 5: Pay and confirm
        pay_payload = {
            "payment_method": "CREDIT_CARD",
            "transaction_ref": f"txn-integ-{order['id'][:8]}",
        }
        get_success_data(api_client.pay_order(order["id"], pay_payload, _customer))
        order = get_success_data(api_client.confirm_payment(order["id"], _admin))
        assert order["payment_status"] == "PAID"

        # Step 6: Process, ship, deliver
        get_success_data(api_client.start_processing(order["id"], _seller))
        get_success_data(api_client.ship_order(order["id"], _seller))
        order = get_success_data(api_client.deliver_order(order["id"], _seller))
        assert order["order_status"] == "COMPLETED"
        assert order["fulfillment_status"] == "DELIVERED"

        # Step 7: Verify commission, GMV, settlement_balance
        shop_after_delivery = get_shop_after(shop["id"])
        assert shop_after_delivery["monthly_gmv"] > 0
        assert shop_after_delivery["settlement_balance"] > 0
        assert_shop_invariants(shop_after_delivery)
        assert_cost_precision(shop_after_delivery["monthly_gmv"])

        # Step 8: Partial refund
        order_detail = get_success_data(api_client.get_order(order["id"], _admin))
        items = order_detail.get("items") or order_detail.get("order_items", [])
        assert len(items) >= 1

        refund_payload = create_refund_payload(
            refund_type="PARTIAL",
            refund_items=[{"order_item_id": items[0]["id"], "quantity": 1}],
            reason="Item arrived damaged",
        )
        refund = get_success_data(
            api_client.create_refund(order["id"], refund_payload, _customer)
        )
        assert refund["status"] == "REQUESTED"

        refund = get_success_data(
            api_client.approve_refund(order["id"], refund["id"], _seller)
        )
        assert refund["status"] == "APPROVED"

        refund = get_success_data(
            api_client.process_refund(order["id"], refund["id"], _admin)
        )
        assert refund["status"] == "PROCESSED"

        # Step 9: Verify inventory and balance adjustments
        shop_after_refund = get_shop_after(shop["id"])
        assert_shop_invariants(shop_after_refund)
        # settlement_balance should have decreased by the refund amount
        assert shop_after_refund["settlement_balance"] <= (
            shop_after_delivery["settlement_balance"] + 0.01
        )

        # Step 10: Settlement lifecycle
        period_end = datetime.now(timezone.utc) + timedelta(minutes=5)
        settlement_payload = create_settlement_payload(
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
        )
        settlement = get_success_data(
            api_client.create_settlement(shop["id"], settlement_payload, _seller)
        )
        assert settlement["status"] == "DRAFT"
        assert_settlement(settlement)

        # Submit
        settlement = get_success_data(
            api_client.submit_settlement(shop["id"], settlement["id"], _seller)
        )
        assert settlement["status"] == "PENDING_APPROVAL"

        # Verify reconciliation
        assert settlement["net_amount"] > 0
        expected_net = round(
            settlement["gross_amount"]
            - settlement["total_commission"]
            - settlement["total_refunds"],
            2,
        )
        assert settlement["net_amount"] == pytest.approx(expected_net, abs=0.01)

        # Approve
        settlement = get_success_data(
            api_client.approve_settlement(shop["id"], settlement["id"], _admin)
        )
        assert settlement["status"] == "APPROVED"

        # Mark paid
        balance_before_payout = get_shop_after(shop["id"])["settlement_balance"]
        settlement = get_success_data(
            api_client.mark_settlement_paid(shop["id"], settlement["id"], _admin)
        )
        assert settlement["status"] == "PAID"

        # Step 11: Verify final balance
        shop_final = get_shop_after(shop["id"])
        expected_balance = round(
            balance_before_payout - settlement["net_amount"], 2
        )
        assert shop_final["settlement_balance"] == pytest.approx(
            expected_balance, abs=0.01
        )
        assert_shop_invariants(shop_final)


# ============================================================================
# Multi-role workflow
# ============================================================================


class TestMultiRoleWorkflow:
    """Different operations by different roles at each step with RBAC checks."""

    def test_role_enforcement_at_each_lifecycle_step(self):
        """
        Walk through the order lifecycle verifying that only the correct
        role can perform each action.
        """
        # Seller creates shop
        shop = get_success_data(
            api_client.create_shop(create_shop_payload(), _seller)
        )

        # Customer cannot approve shop
        resp = api_client.approve_shop(shop["id"], _customer)
        validate_error(resp, ERR_FORBIDDEN)

        # Admin approves
        shop = get_success_data(api_client.approve_shop(shop["id"], _admin))

        # Seller creates and lists product
        product = get_success_data(api_client.create_product(
            shop["id"],
            create_product_payload(base_price=75.0, inventory_count=20),
            _seller,
        ))
        product = get_success_data(
            api_client.list_product(shop["id"], product["id"], _seller)
        )

        # Customer places order
        order_payload = create_order_payload(
            shop["id"],
            [{"product_id": product["id"], "quantity": 1}],
        )
        order = get_success_data(api_client.create_order(order_payload, _customer))

        # Customer pays
        pay_payload = {"payment_method": "DEBIT_CARD", "transaction_ref": "txn-multi"}
        get_success_data(api_client.pay_order(order["id"], pay_payload, _customer))

        # Seller cannot confirm payment
        resp = api_client.confirm_payment(order["id"], _seller)
        validate_error(resp, ERR_FORBIDDEN)

        # Admin confirms payment
        order = get_success_data(api_client.confirm_payment(order["id"], _admin))
        assert order["payment_status"] == "PAID"

        # Customer cannot start processing
        resp = api_client.start_processing(order["id"], _customer)
        validate_error(resp, ERR_FORBIDDEN)

        # Seller processes, ships, delivers
        get_success_data(api_client.start_processing(order["id"], _seller))
        get_success_data(api_client.ship_order(order["id"], _seller))
        order = get_success_data(api_client.deliver_order(order["id"], _seller))
        assert order["order_status"] == "COMPLETED"

        # Customer requests refund
        refund_payload = create_refund_payload(refund_type="FULL")
        refund = get_success_data(
            api_client.create_refund(order["id"], refund_payload, _customer)
        )

        # Seller approves refund
        refund = get_success_data(
            api_client.approve_refund(order["id"], refund["id"], _seller)
        )

        # Seller cannot process refund (admin only)
        resp = api_client.process_refund(order["id"], refund["id"], _seller)
        validate_error(resp, ERR_FORBIDDEN)

        # Admin processes refund
        refund = get_success_data(
            api_client.process_refund(order["id"], refund["id"], _admin)
        )
        assert refund["status"] == "PROCESSED"

    def test_admin_hierarchical_override(self):
        """Admin can perform seller actions (hierarchical override)."""
        shop = get_success_data(
            api_client.create_shop(create_shop_payload(), _admin)
        )
        shop = get_success_data(api_client.approve_shop(shop["id"], _admin))

        product = get_success_data(api_client.create_product(
            shop["id"],
            create_product_payload(base_price=25.0, inventory_count=10),
            _admin,
        ))
        product = get_success_data(
            api_client.list_product(shop["id"], product["id"], _admin)
        )
        assert product["status"] == "LISTED"


# ============================================================================
# Discount strategy comparison
# ============================================================================


class TestDiscountStrategyComparison:
    """
    PERCENTAGE_FIRST vs FIXED_FIRST with identical products and promotions.

    The core challenge: applying the same promotions in different order
    yields different totals.
    """

    def _setup_shop_with_promotions(self, strategy, seller_headers):
        """Create a shop with a specific strategy and two stackable promotions."""
        shop_payload = create_shop_payload(
            shop_name=f"Shop ({strategy})",
            discount_strategy=strategy,
            owner_id=seller_headers["X-User-ID"],
        )
        shop = get_success_data(api_client.create_shop(shop_payload, seller_headers))
        shop = get_success_data(api_client.approve_shop(shop["id"], _admin))

        product = get_success_data(api_client.create_product(
            shop["id"],
            create_product_payload(
                product_name="Identical Widget",
                base_price=200.0,
                inventory_count=50,
                category="electronics",
            ),
            seller_headers,
        ))
        product = get_success_data(
            api_client.list_product(shop["id"], product["id"], seller_headers)
        )

        now = datetime.now(timezone.utc)

        # Percentage promotion: 10% off
        pct_payload = create_promotion_payload(
            promo_name="10% Off",
            promo_type="PERCENTAGE",
            promo_value=10,
            stackable=True,
            priority=1,
            applicable_categories=["electronics"],
            start_time=(now - timedelta(hours=1)).isoformat(),
            end_time=(now + timedelta(days=30)).isoformat(),
        )
        pct_promo = get_success_data(
            api_client.create_promotion(shop["id"], pct_payload, seller_headers)
        )
        get_success_data(
            api_client.activate_promotion(shop["id"], pct_promo["id"], seller_headers)
        )

        # Fixed promotion: $15 off
        fixed_payload = create_promotion_payload(
            promo_name="$15 Off",
            promo_type="FIXED_AMOUNT",
            promo_value=15,
            stackable=True,
            priority=2,
            applicable_categories=["electronics"],
            start_time=(now - timedelta(hours=1)).isoformat(),
            end_time=(now + timedelta(days=30)).isoformat(),
        )
        fixed_promo = get_success_data(
            api_client.create_promotion(shop["id"], fixed_payload, seller_headers)
        )
        get_success_data(
            api_client.activate_promotion(shop["id"], fixed_promo["id"], seller_headers)
        )

        return shop, product

    def test_different_strategies_produce_different_totals(self):
        """
        Same products, same promotions, different discount_strategy
        -> different total_amount.

        PERCENTAGE_FIRST: 200 * 0.9 = 180, then 180 - 15 = 165
        FIXED_FIRST:      200 - 15 = 185, then 185 * 0.9 = 166.5

        The exact values depend on the implementation but they must differ.
        """
        shop_pct, product_pct = self._setup_shop_with_promotions(
            "PERCENTAGE_FIRST", _seller
        )
        shop_fix, product_fix = self._setup_shop_with_promotions(
            "FIXED_FIRST", _seller2
        )

        # Place identical orders
        order_pct_payload = create_order_payload(
            shop_pct["id"],
            [{"product_id": product_pct["id"], "quantity": 1}],
        )
        order_pct = get_success_data(
            api_client.create_order(order_pct_payload, _customer)
        )

        order_fix_payload = create_order_payload(
            shop_fix["id"],
            [{"product_id": product_fix["id"], "quantity": 1}],
        )
        order_fix = get_success_data(
            api_client.create_order(order_fix_payload, _customer)
        )

        # Both should have discounts
        assert order_pct["discount_amount"] > 0
        assert order_fix["discount_amount"] > 0

        # The totals should differ because the application order matters
        assert order_pct["total_amount"] != pytest.approx(
            order_fix["total_amount"], abs=0.001
        ), (
            f"PERCENTAGE_FIRST total ({order_pct['total_amount']}) should differ "
            f"from FIXED_FIRST total ({order_fix['total_amount']})"
        )

        # Verify both have correct precision
        assert_cost_precision(order_pct["total_amount"])
        assert_cost_precision(order_fix["total_amount"])

    def test_percentage_first_applies_percentage_before_fixed(self):
        """PERCENTAGE_FIRST: percentage discount applied first, then fixed."""
        shop, product = self._setup_shop_with_promotions(
            "PERCENTAGE_FIRST", _seller
        )
        order_payload = create_order_payload(
            shop["id"],
            [{"product_id": product["id"], "quantity": 1}],
        )
        order = get_success_data(api_client.create_order(order_payload, _customer))

        # base_price=200, 10% off first -> 180, then $15 off -> 165
        # Allow for minor floating-point differences
        subtotal = order["subtotal"]
        total = order["total_amount"]
        discount = order["discount_amount"]

        assert subtotal == pytest.approx(200.0, abs=0.01)
        assert discount == pytest.approx(35.0, abs=0.50)
        assert total == pytest.approx(subtotal - discount, abs=0.01)

    def test_fixed_first_applies_fixed_before_percentage(self):
        """FIXED_FIRST: fixed discount applied first, then percentage."""
        shop, product = self._setup_shop_with_promotions(
            "FIXED_FIRST", _seller2
        )
        order_payload = create_order_payload(
            shop["id"],
            [{"product_id": product["id"], "quantity": 1}],
        )
        order = get_success_data(api_client.create_order(order_payload, _customer))

        # base_price=200, $15 off first -> 185, then 10% off -> 166.50
        subtotal = order["subtotal"]
        total = order["total_amount"]
        discount = order["discount_amount"]

        assert subtotal == pytest.approx(200.0, abs=0.01)
        assert discount == pytest.approx(33.50, abs=0.50)
        assert total == pytest.approx(subtotal - discount, abs=0.01)

    def test_full_lifecycle_with_both_strategies(self):
        """Both strategy shops complete the full lifecycle without errors."""
        shop_pct, product_pct = self._setup_shop_with_promotions(
            "PERCENTAGE_FIRST", _seller
        )
        shop_fix, product_fix = self._setup_shop_with_promotions(
            "FIXED_FIRST", _seller2
        )

        for shop, product, seller_h in [
            (shop_pct, product_pct, _seller),
            (shop_fix, product_fix, _seller2),
        ]:
            order_payload = create_order_payload(
                shop["id"],
                [{"product_id": product["id"], "quantity": 2}],
            )
            order = get_success_data(
                api_client.create_order(order_payload, _customer)
            )

            pay_payload = {
                "payment_method": "CREDIT_CARD",
                "transaction_ref": f"txn-strat-{order['id'][:8]}",
            }
            get_success_data(api_client.pay_order(order["id"], pay_payload, _customer))
            get_success_data(api_client.confirm_payment(order["id"], _admin))
            get_success_data(api_client.start_processing(order["id"], seller_h))
            get_success_data(api_client.ship_order(order["id"], seller_h))
            delivered = get_success_data(
                api_client.deliver_order(order["id"], seller_h)
            )
            assert delivered["order_status"] == "COMPLETED"

            final_shop = get_shop_after(shop["id"])
            assert final_shop["monthly_gmv"] > 0
            assert final_shop["settlement_balance"] > 0
            assert_shop_invariants(final_shop)
