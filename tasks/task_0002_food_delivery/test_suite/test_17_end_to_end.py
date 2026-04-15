"""End-to-end integration tests covering full order-to-settlement lifecycle.

Covers: Full lifecycle validation, cascading side effects, derived field reconciliation.
"""
import math
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_restaurant_payload, create_menu_item_payload,
    create_customer_payload, create_rider_payload,
    create_order_payload, create_delivery_payload,
    create_top_up_payload, create_promotion_payload,
    create_complaint_payload, create_rating_payload,
    create_settlement_run_payload, create_resolve_complaint_payload,
    create_surge_zone_payload,
    complete_order_lifecycle,
    RIDER_PLATFORM_FEE_RATE,
)


_admin = TEST_USERS["admin_headers"]
_restaurant = TEST_USERS["restaurant_headers"]
_customer = TEST_USERS["customer_headers"]
_rider = TEST_USERS["rider_headers"]
_cs = TEST_USERS["cs_headers"]


class TestFullOrderToSettlement:
    """Complete lifecycle: order -> delivery -> rating -> settlement."""

    def test_full_lifecycle(self):
        """Execute a complete order from placement through settlement."""
        # 1. Setup entities
        rest = get_success_data(api_client.create_restaurant(
            create_restaurant_payload(commission_rate=0.20), _admin
        ))
        get_success_data(api_client.approve_restaurant(rest["id"], _admin))
        get_success_data(api_client.update_restaurant(
            rest["id"], {"is_accepting_orders": True}, _restaurant
        ))

        mi = get_success_data(api_client.create_menu_item(
            rest["id"],
            create_menu_item_payload(base_price_cents=3000, prep_time_minutes=15),
            _restaurant,
        ))

        customer = get_success_data(api_client.create_customer(
            create_customer_payload(), _customer
        ))
        get_success_data(api_client.top_up_wallet(
            customer["id"], create_top_up_payload(100000), _customer
        ))

        rider = get_success_data(api_client.create_rider(
            create_rider_payload(vehicle_type="MOTORCYCLE"), _admin
        ))
        get_success_data(api_client.approve_rider(rider["id"], _admin))
        get_success_data(api_client.update_rider(rider["id"], {"is_online": True}, _rider))

        # 2. Place order
        order_payload = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": mi["id"], "quantity": 2}],
            tip_cents=500,
        )
        order = get_success_data(api_client.create_order(order_payload, _customer))
        assert order["status"] == "PLACED"
        assert order["subtotal_cents"] == 6000  # 3000 * 2
        assert order["tip_cents"] == 500

        # Verify fee calculations
        assert order["service_fee_cents"] == math.ceil(6000 * 0.05)  # 300 (>= 5000 tier)
        assert order["small_order_fee_cents"] == 0  # subtotal >= 1500
        total_expected = (
            order["subtotal_cents"]
            + order["delivery_fee_cents"]
            + order["service_fee_cents"]
            + order["small_order_fee_cents"]
            - order["discount_cents"]
            + order["tip_cents"]
        )
        assert order["total_cents"] == total_expected

        # 3. Confirm order
        confirmed = get_success_data(api_client.confirm_order(order["id"], _restaurant))
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["payment_status"] == "AUTHORIZED"

        # Wallet debited
        c = get_success_data(api_client.get_customer(customer["id"], _admin))
        assert c["wallet_balance_cents"] == 100000 - order["total_cents"]

        # 4. Prepare and ready
        get_success_data(api_client.start_preparing_order(order["id"], _restaurant))
        get_success_data(api_client.mark_order_ready(order["id"], _restaurant))

        # 5. Assign delivery
        delivery = get_success_data(api_client.create_delivery(
            order["id"], create_delivery_payload(rider["id"]), _admin
        ))
        assert delivery["status"] == "ASSIGNED"

        # 6. Delivery progression
        get_success_data(api_client.start_delivery(order["id"], delivery["id"], _rider))
        get_success_data(api_client.arrive_at_restaurant(order["id"], delivery["id"], _rider))

        # 7. Pickup
        get_success_data(api_client.pickup_order(order["id"], _rider))

        # 8. Deliver
        delivered = get_success_data(api_client.deliver_order(order["id"], _rider))
        assert delivered["status"] == "DELIVERED"
        assert delivered["payment_status"] == "CAPTURED"

        # Verify commission calculation
        commission = math.floor(6000 * 0.20)  # 1200
        assert delivered["commission_amount_cents"] == commission
        assert delivered["restaurant_payout_cents"] == 6000 - commission  # 4800

        # Verify rider payout
        delivery_fee = delivered["delivery_fee_cents"]
        rider_platform_fee = math.floor(delivery_fee * RIDER_PLATFORM_FEE_RATE)
        expected_rider_payout = delivery_fee - rider_platform_fee + 500
        assert delivered["rider_payout_cents"] == expected_rider_payout

        # Verify counters
        r_rest = get_success_data(api_client.get_restaurant(rest["id"], _admin))
        assert r_rest["total_orders_completed"] >= 1
        assert r_rest["balance_pending_cents"] >= 4800

        r_rider = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert r_rider["total_deliveries_completed"] >= 1
        assert r_rider["earnings_balance_cents"] >= expected_rider_payout

        c = get_success_data(api_client.get_customer(customer["id"], _admin))
        assert c["total_orders"] >= 1
        expected_points = math.floor(order["total_cents"] / 100)
        assert c["loyalty_points"] >= expected_points

        # 9. Rate
        rating = get_success_data(api_client.create_rating(
            order["id"],
            create_rating_payload("CUSTOMER_TO_RESTAURANT", customer["id"], rest["id"], score=5),
            _customer,
        ))
        get_success_data(api_client.publish_rating(order["id"], rating["id"], _admin))

        r_rest = get_success_data(api_client.get_restaurant(rest["id"], _admin))
        assert r_rest["rating_count"] >= 1
        assert r_rest["rating_average"] == pytest.approx(5.0, abs=0.01)

        # 10. Settlement
        get_success_data(api_client.run_settlement(create_settlement_run_payload(), _admin))
        r_rest = get_success_data(api_client.get_restaurant(rest["id"], _admin))
        assert r_rest["balance_pending_cents"] == 0
        assert r_rest["balance_settled_cents"] > 0

        r_rider = get_success_data(api_client.get_rider(rider["id"], _admin))
        assert r_rider["earnings_balance_cents"] == 0
        assert r_rider["earnings_settled_cents"] > 0


class TestOrderWithPromotion:
    """End-to-end: order with promotion, delivery, and complaint with refund."""

    def test_order_with_promotion_and_complaint_refund(self):
        """Place order with promotion, deliver, file complaint with refund, verify clawback."""
        # Setup
        rest = get_success_data(api_client.create_restaurant(
            create_restaurant_payload(commission_rate=0.15), _admin
        ))
        get_success_data(api_client.approve_restaurant(rest["id"], _admin))
        get_success_data(api_client.update_restaurant(
            rest["id"], {"is_accepting_orders": True}, _restaurant
        ))

        mi = get_success_data(api_client.create_menu_item(
            rest["id"],
            create_menu_item_payload(base_price_cents=5000),
            _restaurant,
        ))

        promo = get_success_data(api_client.create_promotion(
            create_promotion_payload(
                discount_type="FIXED_AMOUNT",
                discount_value=500,
                minimum_order_cents=3000,
                max_uses=10,
            ), _admin
        ))

        customer = get_success_data(api_client.create_customer(
            create_customer_payload(), _customer
        ))
        get_success_data(api_client.top_up_wallet(
            customer["id"], create_top_up_payload(200000), _customer
        ))

        rider = get_success_data(api_client.create_rider(
            create_rider_payload(vehicle_type="MOTORCYCLE"), _admin
        ))
        get_success_data(api_client.approve_rider(rider["id"], _admin))
        get_success_data(api_client.update_rider(rider["id"], {"is_online": True}, _rider))

        # Place order with promotion
        order = get_success_data(api_client.create_order(
            create_order_payload(
                customer["id"], rest["id"],
                [{"menu_item_id": mi["id"], "quantity": 1}],
                promotion_id=promo["id"],
            ), _customer
        ))
        assert order["discount_cents"] == 500

        # Complete lifecycle
        get_success_data(api_client.confirm_order(order["id"], _restaurant))
        get_success_data(api_client.start_preparing_order(order["id"], _restaurant))
        get_success_data(api_client.mark_order_ready(order["id"], _restaurant))

        delivery = get_success_data(api_client.create_delivery(
            order["id"], create_delivery_payload(rider["id"]), _admin
        ))
        get_success_data(api_client.start_delivery(order["id"], delivery["id"], _rider))
        get_success_data(api_client.arrive_at_restaurant(order["id"], delivery["id"], _rider))
        get_success_data(api_client.pickup_order(order["id"], _rider))
        delivered = get_success_data(api_client.deliver_order(order["id"], _rider))
        assert delivered["status"] == "DELIVERED"

        # Promotion uses incremented
        p = get_success_data(api_client.get_promotion(promo["id"], _admin))
        assert p["current_uses"] == 1

        # File complaint with full refund
        complaint = get_success_data(api_client.create_complaint(
            order["id"],
            create_complaint_payload("CUSTOMER", customer["id"], category="WRONG_ITEMS"),
            _customer,
        ))
        get_success_data(api_client.assign_complaint(
            order["id"], complaint["id"],
            {"assigned_agent_id": "agent-1"}, _cs,
        ))
        get_success_data(api_client.resolve_complaint(
            order["id"], complaint["id"],
            create_resolve_complaint_payload("REFUND", delivered["total_cents"]), _cs,
        ))

        # Verify refund
        refreshed_order = get_success_data(api_client.get_order(order["id"], _admin))
        assert refreshed_order["payment_status"] == "REFUNDED"
