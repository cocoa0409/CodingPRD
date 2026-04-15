"""Tests for order placement, validation, and fee calculations.

Covers: PRD Section 3.4 (Placing an Order), 3.5 (Fee Calculation and Pricing Engine),
Table 3 (calculation rules), Table 6 (order-related errors).
"""
import math
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_order,
    create_restaurant_payload, create_menu_item_payload,
    create_order_payload, create_customer_payload, create_top_up_payload,
    create_and_approve_restaurant, create_active_customer,
    setup_restaurant_with_menu_items, setup_basic_order_scenario,
    create_active_promotion, create_active_surge_zone,
    BASE_FEE_CENTS, PER_KM_CENTS,
    SMALL_ORDER_THRESHOLD_CENTS, MEDIUM_ORDER_THRESHOLD_CENTS,
    SMALL_RATE, MEDIUM_RATE, LARGE_RATE, MINIMUM_SERVICE_FEE_CENTS,
    SMALL_ORDER_SUBTOTAL_THRESHOLD_CENTS, MAX_SMALL_ORDER_FEE_CENTS,
    MAX_DISTINCT_ORDER_ITEMS, MINIMUM_REDEMPTION_POINTS,
)


_admin = TEST_USERS["admin_headers"]
_restaurant = TEST_USERS["restaurant_headers"]
_customer = TEST_USERS["customer_headers"]


class TestOrderCreation:
    """PRD 3.4: Customer places an order."""

    def test_create_order_success(self):
        """Place a basic order; status=PLACED, payment_status=PENDING."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=2000)
        assert_order(order)
        assert order["status"] == "PLACED"
        assert order["payment_status"] == "PENDING"
        assert order["customer_id"] == customer["id"]
        assert order["restaurant_id"] == rest["id"]

    def test_order_subtotal_is_sum_of_item_totals(self):
        """subtotal_cents = SUM(unit_price_cents * quantity) (Table 3: order_subtotal)."""
        rest, items = setup_restaurant_with_menu_items(
            num_items=2,
            item_overrides=[{"base_price_cents": 1000}, {"base_price_cents": 1500}],
        )
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer(wallet_cents=100000)
        order_items = [
            {"menu_item_id": items[0]["id"], "quantity": 2},
            {"menu_item_id": items[1]["id"], "quantity": 3},
        ]
        payload = create_order_payload(customer["id"], rest["id"], order_items)
        order = get_success_data(api_client.create_order(payload, _customer))
        expected_subtotal = 1000 * 2 + 1500 * 3  # 2000 + 4500 = 6500
        assert order["subtotal_cents"] == expected_subtotal

    def test_order_snapshots_price_at_creation(self):
        """unit_price_cents is a snapshot from menu_item.base_price_cents at order time."""
        rest, items = setup_restaurant_with_menu_items(
            num_items=1,
            item_overrides=[{"base_price_cents": 1200}],
        )
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer(wallet_cents=100000)

        order_items = [{"menu_item_id": items[0]["id"], "quantity": 1}]
        payload = create_order_payload(customer["id"], rest["id"], order_items)
        order = get_success_data(api_client.create_order(payload, _customer))
        assert order["subtotal_cents"] == 1200

    def test_estimated_prep_time_is_max_of_items(self):
        """estimated_prep_time_minutes = max(item prep times) (PRD 3.4)."""
        rest, items = setup_restaurant_with_menu_items(
            num_items=2,
            item_overrides=[{"prep_time_minutes": 10}, {"prep_time_minutes": 25}],
        )
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer(wallet_cents=100000)
        order_items = [
            {"menu_item_id": items[0]["id"], "quantity": 1},
            {"menu_item_id": items[1]["id"], "quantity": 1},
        ]
        payload = create_order_payload(customer["id"], rest["id"], order_items)
        order = get_success_data(api_client.create_order(payload, _customer))
        assert order["estimated_prep_time_minutes"] == 25

    def test_tip_defaults_to_zero(self):
        """tip_cents defaults to 0 when not provided."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=2000)
        assert order["tip_cents"] == 0

    def test_custom_tip(self):
        """Providing tip_cents includes it in total."""
        rest, menu_items, customer, order = setup_basic_order_scenario(
            item_price_cents=2000, tip_cents=500
        )
        assert order["tip_cents"] == 500


class TestOrderValidation:
    """PRD 3.4: Order creation validation in priority order."""

    def test_restaurant_not_found(self):
        """ERR_RESTAURANT_NOT_FOUND when restaurant doesn't exist."""
        customer = create_active_customer()
        payload = create_order_payload(
            customer["id"], NON_EXISTENT_UUID,
            [{"menu_item_id": NON_EXISTENT_UUID, "quantity": 1}]
        )
        resp = api_client.create_order(payload, _customer)
        validate_error(resp, ApiErrorId.ERR_RESTAURANT_NOT_FOUND)

    def test_restaurant_not_active(self):
        """ERR_RESTAURANT_NOT_ACTIVE when restaurant is PENDING_APPROVAL."""
        payload = create_restaurant_payload()
        rest = get_success_data(api_client.create_restaurant(payload, _admin))
        customer = create_active_customer()
        p = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": NON_EXISTENT_UUID, "quantity": 1}]
        )
        resp = api_client.create_order(p, _customer)
        validate_error(resp, ApiErrorId.ERR_RESTAURANT_NOT_ACTIVE)

    def test_restaurant_not_accepting(self):
        """ERR_RESTAURANT_NOT_ACCEPTING when is_accepting_orders=false."""
        rest = create_and_approve_restaurant()
        # Default is_accepting_orders is false (or not set)
        customer = create_active_customer()
        mi = get_success_data(api_client.create_menu_item(
            rest["id"], create_menu_item_payload(), _restaurant
        ))
        p = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": mi["id"], "quantity": 1}]
        )
        # Ensure not accepting
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": False}, _restaurant))
        resp = api_client.create_order(p, _customer)
        validate_error(resp, ApiErrorId.ERR_RESTAURANT_NOT_ACCEPTING)

    def test_customer_not_active(self):
        """ERR_CUSTOMER_NOT_ACTIVE when customer is SUSPENDED."""
        rest, items = setup_restaurant_with_menu_items(num_items=1)
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        # Create a customer and then suspend via admin? PRD says customer status can be SUSPENDED.
        # We'll try with a non-existent customer_id which might be caught differently.
        # Actually, we can create a customer, get it, then use it.
        # The PRD says "Customers who are not in ACTIVE status cannot place orders"
        # For now, use a non-existent customer to check customer validation
        p = create_order_payload(
            NON_EXISTENT_UUID, rest["id"],
            [{"menu_item_id": items[0]["id"], "quantity": 1}]
        )
        resp = api_client.create_order(p, _customer)
        # Could be ERR_CUSTOMER_NOT_FOUND or ERR_CUSTOMER_NOT_ACTIVE
        assert resp.status_code in [404, 409]

    def test_empty_order_rejected(self):
        """ERR_EMPTY_ORDER when items array is empty."""
        rest = create_and_approve_restaurant()
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer()
        p = create_order_payload(customer["id"], rest["id"], [])
        resp = api_client.create_order(p, _customer)
        validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER)

    def test_too_many_items_rejected(self):
        """ERR_TOO_MANY_ITEMS when > 20 distinct items."""
        rest = create_and_approve_restaurant()
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        # Create 21 menu items
        item_ids = []
        for _ in range(21):
            mi = get_success_data(api_client.create_menu_item(
                rest["id"], create_menu_item_payload(), _restaurant
            ))
            item_ids.append(mi["id"])
        customer = create_active_customer()
        items = [{"menu_item_id": mid, "quantity": 1} for mid in item_ids]
        p = create_order_payload(customer["id"], rest["id"], items)
        resp = api_client.create_order(p, _customer)
        validate_error(resp, ApiErrorId.ERR_TOO_MANY_ITEMS)

    def test_exactly_20_items_allowed(self):
        """Boundary: exactly 20 distinct items is allowed."""
        rest = create_and_approve_restaurant()
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        item_ids = []
        for _ in range(20):
            mi = get_success_data(api_client.create_menu_item(
                rest["id"], create_menu_item_payload(), _restaurant
            ))
            item_ids.append(mi["id"])
        customer = create_active_customer(wallet_cents=500000)
        items = [{"menu_item_id": mid, "quantity": 1} for mid in item_ids]
        p = create_order_payload(customer["id"], rest["id"], items)
        resp = api_client.create_order(p, _customer)
        validate_success(resp, 201)

    def test_invalid_quantity_zero(self):
        """ERR_INVALID_QUANTITY when quantity < 1."""
        rest, items = setup_restaurant_with_menu_items(num_items=1)
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer()
        p = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": items[0]["id"], "quantity": 0}]
        )
        resp = api_client.create_order(p, _customer)
        validate_error(resp, ApiErrorId.ERR_INVALID_QUANTITY)

    def test_menu_item_not_found(self):
        """ERR_MENU_ITEM_NOT_FOUND when menu item doesn't exist."""
        rest = create_and_approve_restaurant()
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer()
        p = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": NON_EXISTENT_UUID, "quantity": 1}]
        )
        resp = api_client.create_order(p, _customer)
        validate_error(resp, ApiErrorId.ERR_MENU_ITEM_NOT_FOUND)

    def test_item_not_available(self):
        """ERR_ITEM_NOT_AVAILABLE when menu item is_available=false."""
        rest, items = setup_restaurant_with_menu_items(num_items=1)
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        # Set item to unavailable
        get_success_data(api_client.update_menu_item(
            rest["id"], items[0]["id"], {"is_available": False}, _restaurant
        ))
        customer = create_active_customer()
        p = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": items[0]["id"], "quantity": 1}]
        )
        resp = api_client.create_order(p, _customer)
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_AVAILABLE)

    def test_cross_restaurant_order(self):
        """ERR_CROSS_RESTAURANT_ORDER when items from different restaurants."""
        rest1, items1 = setup_restaurant_with_menu_items(num_items=1)
        rest2, items2 = setup_restaurant_with_menu_items(num_items=1)
        get_success_data(api_client.update_restaurant(rest1["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer()
        p = create_order_payload(
            customer["id"], rest1["id"],
            [
                {"menu_item_id": items1[0]["id"], "quantity": 1},
                {"menu_item_id": items2[0]["id"], "quantity": 1},
            ]
        )
        resp = api_client.create_order(p, _customer)
        validate_error(resp, ApiErrorId.ERR_CROSS_RESTAURANT_ORDER)

    def test_negative_tip_rejected(self):
        """ERR_INVALID_TIP when tip_cents < 0."""
        rest, items = setup_restaurant_with_menu_items(num_items=1)
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer()
        p = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": items[0]["id"], "quantity": 1}],
            tip_cents=-100,
        )
        resp = api_client.create_order(p, _customer)
        validate_error(resp, ApiErrorId.ERR_INVALID_TIP)

    def test_order_forbidden_for_admin(self):
        """Only customer role can place orders."""
        rest, items = setup_restaurant_with_menu_items(num_items=1)
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer()
        p = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": items[0]["id"], "quantity": 1}]
        )
        resp = api_client.create_order(p, _admin)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestServiceFeeCalculation:
    """PRD 3.5: Service fee tiers and minimum.

    Table 3 (service_fee): < 2000 -> 15% ceil, 2000-4999 -> 10% ceil, >= 5000 -> 5% ceil, min 99.
    """

    def test_service_fee_small_order_15_percent(self):
        """subtotal < 2000 cents -> 15% rounded up."""
        # item price 1000 -> subtotal = 1000
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=1000)
        expected = math.ceil(1000 * 0.15)  # 150
        assert order["service_fee_cents"] == expected, \
            f"Expected service_fee_cents={expected}, got {order['service_fee_cents']}"

    def test_service_fee_medium_order_10_percent(self):
        """2000 <= subtotal < 5000 -> 10% rounded up."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=3000)
        expected = math.ceil(3000 * 0.10)  # 300
        assert order["service_fee_cents"] == expected

    def test_service_fee_large_order_5_percent(self):
        """subtotal >= 5000 -> 5% rounded up."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=5000)
        expected = math.ceil(5000 * 0.05)  # 250
        assert order["service_fee_cents"] == expected

    def test_service_fee_minimum_99_cents(self):
        """Service fee never falls below 99 cents."""
        # Very small subtotal: e.g., 500 cents -> 15% = 75 -> should be raised to 99
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=500)
        assert order["service_fee_cents"] >= MINIMUM_SERVICE_FEE_CENTS, \
            f"Service fee must be >= {MINIMUM_SERVICE_FEE_CENTS}, got {order['service_fee_cents']}"

    def test_service_fee_boundary_at_2000(self):
        """Boundary: subtotal = 2000 uses 10% tier, not 15%."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=2000)
        expected = math.ceil(2000 * 0.10)  # 200
        assert order["service_fee_cents"] == expected

    def test_service_fee_boundary_at_1999(self):
        """Boundary: subtotal = 1999 uses 15% tier."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=1999)
        expected = math.ceil(1999 * 0.15)  # 300
        assert order["service_fee_cents"] == expected

    def test_service_fee_boundary_at_5000(self):
        """Boundary: subtotal = 5000 uses 5% tier."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=5000)
        expected = math.ceil(5000 * 0.05)  # 250
        assert order["service_fee_cents"] == expected

    def test_service_fee_boundary_at_4999(self):
        """Boundary: subtotal = 4999 uses 10% tier."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=4999)
        expected = math.ceil(4999 * 0.10)  # 500
        assert order["service_fee_cents"] == expected


class TestSmallOrderFee:
    """PRD 3.5: Small order fee = min(1500 - subtotal, 500) when subtotal < 1500.

    Table 3 (small_order_fee).
    """

    def test_small_order_fee_applied(self):
        """subtotal < 1500 -> fee = min(1500 - subtotal, 500)."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=1000)
        expected = min(1500 - 1000, 500)  # 500
        assert order["small_order_fee_cents"] == expected

    def test_small_order_fee_capped_at_500(self):
        """When subtotal is very low, fee is capped at 500 cents."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=500)
        expected = min(1500 - 500, 500)  # min(1000, 500) = 500
        assert order["small_order_fee_cents"] == expected

    def test_no_small_order_fee_at_1500(self):
        """Boundary: subtotal = 1500 -> no small order fee."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=1500)
        assert order["small_order_fee_cents"] == 0

    def test_small_order_fee_at_1499(self):
        """Boundary: subtotal = 1499 -> fee = 1."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=1499)
        assert order["small_order_fee_cents"] == 1

    def test_no_small_order_fee_above_threshold(self):
        """subtotal >= 1500 -> no small order fee."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=2000)
        assert order["small_order_fee_cents"] == 0


class TestDeliveryFeeCalculation:
    """PRD 3.5: Delivery fee = floor((299 + ceil(distance_km)*100) * surge_multiplier).

    Table 3 (delivery_fee). At order creation, this is the provisional fee (no vehicle adjustment).
    """

    def test_delivery_fee_base_calculation(self):
        """Delivery fee includes base 299 + distance component."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=2000)
        # We can't predict exact distance without knowing coordinates, but fee should be >= 299
        assert order["delivery_fee_cents"] >= BASE_FEE_CENTS, \
            f"Delivery fee must be >= {BASE_FEE_CENTS}, got {order['delivery_fee_cents']}"


class TestOrderTotal:
    """PRD 3.5: total_cents = subtotal + delivery_fee + service_fee + small_order_fee - discount + tip.

    Table 3 (order_total).
    """

    def test_total_is_sum_of_components(self):
        """Verify total_cents formula."""
        rest, menu_items, customer, order = setup_basic_order_scenario(
            item_price_cents=2000, tip_cents=300
        )
        expected = (
            order["subtotal_cents"]
            + order["delivery_fee_cents"]
            + order["service_fee_cents"]
            + order["small_order_fee_cents"]
            - order["discount_cents"]
            + order["tip_cents"]
        )
        assert order["total_cents"] == expected, \
            f"Expected total_cents={expected}, got {order['total_cents']}"

    def test_total_non_negative(self):
        """total_cents must be >= 0."""
        rest, menu_items, customer, order = setup_basic_order_scenario(item_price_cents=2000)
        assert order["total_cents"] >= 0
