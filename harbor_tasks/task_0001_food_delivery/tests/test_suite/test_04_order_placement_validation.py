"""Order placement validation (PRD §3.4, §2.6).

Covers:
- Empty items array → ERR_ORDER_INVALID
- Quantity < 1 → ERR_ORDER_INVALID
- Subtotal < 100 cents → ERR_ORDER_INVALID
- Non-ACTIVE restaurant → ERR_RESTAURANT_UNAVAILABLE
- Unlisted MenuItem → ERR_RESTAURANT_UNAVAILABLE
- Cross-restaurant MenuItem reference → ERR_RESTAURANT_UNAVAILABLE
- Non-existent ids in body → ERR_NOT_FOUND
- Provisional fields computed correctly at placement
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    build_order_item,
    create_active_restaurant,
    create_customer,
    create_customer_payload,
    create_listed_menu_item,
    create_order_payload,
    create_restaurant_payload,
    get_success_data,
    make_customer_headers,
    make_restaurant_headers,
    place_order,
    setup_customer_restaurant_menu,
    setup_restaurant_with_menu,
    validate_error,
    validate_success,
)


class TestOrderInvalid:
    def test_empty_items_array_rejected(self, api):
        """PRD §3.4: "items must be non-empty. The order fails placement with
        ERR_ORDER_INVALID when items is empty, any quantity is below 1, or the
        resulting subtotal would be below 100 cents (the minimum order size)."

        Claim: items=[] → ERR_ORDER_INVALID.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        payload = create_order_payload(customer["id"], restaurant["id"], items=[])
        headers = make_customer_headers(customer["id"])
        res = api.create_order(payload, headers)
        validate_error(res, "ERR_ORDER_INVALID")

    def test_quantity_below_one_rejected(self, api):
        """PRD §3.4: "items must be non-empty. The order fails placement with
        ERR_ORDER_INVALID when items is empty, any quantity is below 1, or the
        resulting subtotal would be below 100 cents (the minimum order size)."

        Claim: quantity=0 → ERR_ORDER_INVALID.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        payload = create_order_payload(
            customer["id"], restaurant["id"],
            items=[build_order_item(menu_item["id"], unit_price_cents=1000, quantity=0)],
        )
        headers = make_customer_headers(customer["id"])
        res = api.create_order(payload, headers)
        validate_error(res, "ERR_ORDER_INVALID")

    def test_subtotal_below_minimum_rejected(self, api):
        """PRD §3.4: "items must be non-empty. The order fails placement with
        ERR_ORDER_INVALID when items is empty, any quantity is below 1, or the
        resulting subtotal would be below 100 cents (the minimum order size)."

        Claim: subtotal=50 cents (below 100) → ERR_ORDER_INVALID.
        """
        restaurant, menu_items = setup_restaurant_with_menu(
            menu_items=[{"price_cents": 50, "name": "Cheap"}]
        )
        menu_item = menu_items[0]
        customer = create_customer()
        payload = create_order_payload(
            customer["id"], restaurant["id"],
            items=[build_order_item(menu_item["id"], unit_price_cents=50, quantity=1)],
        )
        headers = make_customer_headers(customer["id"])
        res = api.create_order(payload, headers)
        validate_error(res, "ERR_ORDER_INVALID")


class TestRestaurantUnavailable:
    def test_inactive_restaurant_rejected(self, api, admin_headers):
        """PRD §3.4: "The target Restaurant must be ACTIVE and every MenuItem referenced
        must carry is_listed true and match the Order.restaurant_id — otherwise placement
        is rejected with ERR_RESTAURANT_UNAVAILABLE."

        Claim: placing an order against a SUSPENDED restaurant (non-ACTIVE) →
        ERR_RESTAURANT_UNAVAILABLE.

        Setup: create an ACTIVE restaurant + a listed MenuItem, then suspend the
        restaurant. A fresh placement attempt targeting the now-SUSPENDED restaurant
        with its own listed MenuItem should surface ERR_RESTAURANT_UNAVAILABLE on the
        restaurant-status check (not on cross-restaurant mismatch).
        """
        restaurant = create_active_restaurant()
        item = create_listed_menu_item(restaurant, price_cents=1000)
        api.suspend_restaurant(restaurant["id"], admin_headers)

        customer = create_customer()
        payload = create_order_payload(
            customer["id"],
            restaurant["id"],
            items=[build_order_item(item["id"], unit_price_cents=item["price_cents"])],
        )
        headers = make_customer_headers(customer["id"])
        res = api.create_order(payload, headers)
        validate_error(res, "ERR_RESTAURANT_UNAVAILABLE")

    def test_unlisted_menu_item_rejected(self, api):
        """PRD §3.4: "every MenuItem referenced must carry is_listed true … otherwise
        placement is rejected with ERR_RESTAURANT_UNAVAILABLE."

        Claim: ordering an unlisted menu item → ERR_RESTAURANT_UNAVAILABLE.
        """
        restaurant = create_active_restaurant()
        # Create an unlisted item directly.
        headers = make_restaurant_headers(restaurant["id"])
        from test_helpers import create_menu_item_payload
        unlisted = get_success_data(
            api.create_menu_item(
                restaurant["id"],
                create_menu_item_payload(is_listed=False, price_cents=1000),
                headers,
            )
        )
        customer = create_customer()
        payload = create_order_payload(
            customer["id"], restaurant["id"],
            items=[build_order_item(unlisted["id"], unit_price_cents=1000)],
        )
        c_headers = make_customer_headers(customer["id"])
        res = api.create_order(payload, c_headers)
        validate_error(res, "ERR_RESTAURANT_UNAVAILABLE")

    def test_cross_restaurant_menu_item_rejected(self, api):
        """PRD §3.4: "every MenuItem referenced must … match the Order.restaurant_id —
        otherwise placement is rejected with ERR_RESTAURANT_UNAVAILABLE."

        Claim: ordering from restaurant A with a menu item belonging to restaurant B →
        ERR_RESTAURANT_UNAVAILABLE.
        """
        restaurant_a, item_a = setup_customer_restaurant_menu()[0:2]
        restaurant_b = create_active_restaurant()
        item_b = create_listed_menu_item(restaurant_b)

        customer = create_customer()
        payload = create_order_payload(
            customer["id"], restaurant_a["id"],
            items=[build_order_item(item_b["id"], unit_price_cents=item_b["price_cents"])],
        )
        headers = make_customer_headers(customer["id"])
        res = api.create_order(payload, headers)
        validate_error(res, "ERR_RESTAURANT_UNAVAILABLE")


class TestOrderPlacementComputed:
    def test_subtotal_computed_from_items(self, api):
        """PRD §3.4: "subtotal_cents is the sum across items of unit_price_cents
        multiplied by quantity."

        Claim: two items @1000 * quantities (2, 3) → subtotal_cents == 5000.
        """
        restaurant, items = setup_restaurant_with_menu(
            menu_items=[
                {"price_cents": 1000, "name": "A"},
                {"price_cents": 1000, "name": "B"},
            ]
        )
        customer = create_customer()
        payload = create_order_payload(
            customer["id"], restaurant["id"],
            items=[
                build_order_item(items[0]["id"], unit_price_cents=1000, quantity=2),
                build_order_item(items[1]["id"], unit_price_cents=1000, quantity=3),
            ],
        )
        headers = make_customer_headers(customer["id"])
        data = get_success_data(api.create_order(payload, headers))
        assert data["subtotal_cents"] == 5000

    def test_placement_authorizes_payment(self, api):
        """PRD §3.4: "payment_status starts at UNPAID and immediately moves to AUTHORIZED
        as a placement-time side effect."

        Claim: fresh order's payment_status == AUTHORIZED.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        order = place_order(customer, restaurant, menu_item, quantity=1)
        assert order["payment_status"] == "AUTHORIZED"

    def test_finals_are_null_at_placement(self, api):
        """PRD §3.4: "final_delivery_fee_cents, final_commission_cents,
        actual_delivery_time, and minutes_late all start as null and are populated only
        when the order reaches DELIVERED."

        Claim: fresh order has final_delivery_fee_cents, final_commission_cents,
        actual_delivery_time, minutes_late all null.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        order = place_order(customer, restaurant, menu_item, quantity=1)
        assert order["final_delivery_fee_cents"] is None
        assert order["final_commission_cents"] is None
        assert order["actual_delivery_time"] is None
        assert order["minutes_late"] is None


class TestOrderBodyFkExistence:
    def test_nonexistent_customer_id_rejected(self, api):
        """PRD §2.6 priority 4: "Existence of every foreign-key id in request body resolves
        (customer_id, restaurant_id, menu_item_ids in Order.items, rider_id)."

        Claim: order with non-existent customer_id → ERR_NOT_FOUND.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        payload = create_order_payload(
            NON_EXISTENT_UUID, restaurant["id"],
            items=[build_order_item(menu_item["id"], unit_price_cents=menu_item["price_cents"])],
        )
        # Role is Customer but the identity check at priority 5 would also fail; the
        # priority 4 existence-of-FK check runs first per PRD §2.6.
        headers = make_customer_headers(NON_EXISTENT_UUID)
        res = api.create_order(payload, headers)
        validate_error(res, "ERR_NOT_FOUND")
