"""Tests for promotion management and discount calculations.

Covers: PRD Section 3.14 (Promotions), 3.5 (Promotion discount in pricing engine),
Table 3 (promotion_discount), Table 6 (promotion errors).
"""
import math
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_promotion, create_promotion_payload,
    create_active_promotion,
    setup_restaurant_with_menu_items, create_active_customer,
    create_order_payload,
)


_admin = TEST_USERS["admin_headers"]
_customer = TEST_USERS["customer_headers"]
_restaurant = TEST_USERS["restaurant_headers"]


class TestPromotionCreation:
    """PRD 3.14: Admin creates promotions."""

    def test_create_promotion_success(self):
        """Create an ACTIVE promotion with all fields."""
        payload = create_promotion_payload(
            discount_type="PERCENTAGE",
            discount_value=20,
            minimum_order_cents=2000,
            max_uses=50,
        )
        resp = api_client.create_promotion(payload, _admin)
        data = validate_success(resp, 201)
        assert_promotion(data)
        assert data["status"] == "ACTIVE"
        assert data["current_uses"] == 0
        assert data["discount_type"] == "PERCENTAGE"
        assert data["discount_value"] == 20

    def test_create_fixed_amount_promotion(self):
        """FIXED_AMOUNT discount type."""
        payload = create_promotion_payload(
            discount_type="FIXED_AMOUNT",
            discount_value=500,
        )
        resp = api_client.create_promotion(payload, _admin)
        data = validate_success(resp, 201)
        assert data["discount_type"] == "FIXED_AMOUNT"

    def test_create_free_delivery_promotion(self):
        """FREE_DELIVERY discount type."""
        payload = create_promotion_payload(discount_type="FREE_DELIVERY", discount_value=0)
        resp = api_client.create_promotion(payload, _admin)
        data = validate_success(resp, 201)
        assert data["discount_type"] == "FREE_DELIVERY"

    def test_duplicate_promotion_code_rejected(self):
        """ERR_DUPLICATE_PROMOTION_CODE when code already exists."""
        code = "UNIQUE_TEST_CODE_XYZ"
        get_success_data(api_client.create_promotion(
            create_promotion_payload(code=code), _admin
        ))
        resp = api_client.create_promotion(
            create_promotion_payload(code=code), _admin
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PROMOTION_CODE)

    def test_create_promotion_forbidden_for_customer(self):
        """Only platform_admin can create promotions."""
        resp = api_client.create_promotion(create_promotion_payload(), _customer)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestPromotionDisable:
    """PRD 3.14: Admin disables promotions."""

    def test_disable_active_promotion(self):
        """ACTIVE -> DISABLED."""
        promo = create_active_promotion()
        resp = api_client.disable_promotion(promo["id"], _admin)
        data = validate_success(resp)
        assert data["status"] == "DISABLED"

    def test_disable_already_disabled_promotion(self):
        """Cannot disable a non-ACTIVE promotion."""
        promo = create_active_promotion()
        get_success_data(api_client.disable_promotion(promo["id"], _admin))
        resp = api_client.disable_promotion(promo["id"], _admin)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_promotion_not_found(self):
        """ERR_PROMOTION_NOT_FOUND for non-existent promotion."""
        resp = api_client.get_promotion(NON_EXISTENT_UUID, _admin)
        validate_error(resp, ApiErrorId.ERR_PROMOTION_NOT_FOUND)


class TestPromotionDiscount:
    """PRD 3.5: Promotion discount calculations.

    Table 3 (promotion_discount):
    PERCENTAGE: floor(subtotal * discount_value / 100), capped at max_discount_cents
    FIXED_AMOUNT: discount_value
    FREE_DELIVERY: delivery_fee_cents
    All capped at subtotal_cents.
    """

    def test_percentage_discount(self):
        """PERCENTAGE discount = floor(subtotal * value / 100)."""
        promo = create_active_promotion(
            discount_type="PERCENTAGE",
            discount_value=10,
            minimum_order_cents=1000,
        )
        rest, items = setup_restaurant_with_menu_items(
            num_items=1, item_overrides=[{"base_price_cents": 5000}]
        )
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer(wallet_cents=100000)
        payload = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": items[0]["id"], "quantity": 1}],
            promotion_id=promo["id"],
        )
        order = get_success_data(api_client.create_order(payload, _customer))
        expected_discount = math.floor(5000 * 10 / 100)  # 500
        assert order["discount_cents"] == expected_discount, \
            f"Expected discount={expected_discount}, got {order['discount_cents']}"

    def test_percentage_discount_capped_by_max_discount(self):
        """PERCENTAGE with max_discount_cents cap."""
        promo = create_active_promotion(
            discount_type="PERCENTAGE",
            discount_value=50,
            minimum_order_cents=1000,
            max_discount_cents=1000,
        )
        rest, items = setup_restaurant_with_menu_items(
            num_items=1, item_overrides=[{"base_price_cents": 5000}]
        )
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer(wallet_cents=100000)
        payload = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": items[0]["id"], "quantity": 1}],
            promotion_id=promo["id"],
        )
        order = get_success_data(api_client.create_order(payload, _customer))
        # floor(5000 * 50 / 100) = 2500, but capped at 1000
        assert order["discount_cents"] == 1000, \
            f"Expected discount capped at 1000, got {order['discount_cents']}"

    def test_fixed_amount_discount(self):
        """FIXED_AMOUNT discount = discount_value."""
        promo = create_active_promotion(
            discount_type="FIXED_AMOUNT",
            discount_value=300,
            minimum_order_cents=1000,
        )
        rest, items = setup_restaurant_with_menu_items(
            num_items=1, item_overrides=[{"base_price_cents": 3000}]
        )
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer(wallet_cents=100000)
        payload = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": items[0]["id"], "quantity": 1}],
            promotion_id=promo["id"],
        )
        order = get_success_data(api_client.create_order(payload, _customer))
        assert order["discount_cents"] == 300

    def test_free_delivery_discount(self):
        """FREE_DELIVERY discount = delivery_fee_cents."""
        promo = create_active_promotion(
            discount_type="FREE_DELIVERY",
            discount_value=0,
            minimum_order_cents=1000,
        )
        rest, items = setup_restaurant_with_menu_items(
            num_items=1, item_overrides=[{"base_price_cents": 3000}]
        )
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer(wallet_cents=100000)
        payload = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": items[0]["id"], "quantity": 1}],
            promotion_id=promo["id"],
        )
        order = get_success_data(api_client.create_order(payload, _customer))
        assert order["discount_cents"] == order["delivery_fee_cents"], \
            "FREE_DELIVERY discount should equal delivery_fee_cents"

    def test_discount_cannot_exceed_subtotal(self):
        """discount_cents capped at subtotal_cents."""
        promo = create_active_promotion(
            discount_type="FIXED_AMOUNT",
            discount_value=99999,
            minimum_order_cents=100,
        )
        rest, items = setup_restaurant_with_menu_items(
            num_items=1, item_overrides=[{"base_price_cents": 500}]
        )
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer(wallet_cents=100000)
        payload = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": items[0]["id"], "quantity": 1}],
            promotion_id=promo["id"],
        )
        order = get_success_data(api_client.create_order(payload, _customer))
        assert order["discount_cents"] <= order["subtotal_cents"], \
            "Discount cannot exceed subtotal"

    def test_promotion_increments_current_uses(self):
        """Using a promotion increments current_uses by 1."""
        promo = create_active_promotion(
            discount_type="FIXED_AMOUNT",
            discount_value=100,
            minimum_order_cents=500,
            max_uses=10,
        )
        rest, items = setup_restaurant_with_menu_items(
            num_items=1, item_overrides=[{"base_price_cents": 2000}]
        )
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer(wallet_cents=100000)
        payload = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": items[0]["id"], "quantity": 1}],
            promotion_id=promo["id"],
        )
        get_success_data(api_client.create_order(payload, _customer))

        refreshed = get_success_data(api_client.get_promotion(promo["id"], _admin))
        assert refreshed["current_uses"] == 1


class TestPromotionValidation:
    """PRD 3.5: Promotion validation errors during order creation."""

    def test_promotion_not_found(self):
        """ERR_PROMOTION_NOT_FOUND for non-existent promotion_id."""
        rest, items = setup_restaurant_with_menu_items(
            num_items=1, item_overrides=[{"base_price_cents": 2000}]
        )
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer(wallet_cents=100000)
        payload = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": items[0]["id"], "quantity": 1}],
            promotion_id=NON_EXISTENT_UUID,
        )
        resp = api_client.create_order(payload, _customer)
        validate_error(resp, ApiErrorId.ERR_PROMOTION_NOT_FOUND)

    def test_disabled_promotion_not_valid(self):
        """ERR_PROMOTION_NOT_VALID when promotion is DISABLED."""
        promo = create_active_promotion(minimum_order_cents=100)
        get_success_data(api_client.disable_promotion(promo["id"], _admin))

        rest, items = setup_restaurant_with_menu_items(
            num_items=1, item_overrides=[{"base_price_cents": 2000}]
        )
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer(wallet_cents=100000)
        payload = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": items[0]["id"], "quantity": 1}],
            promotion_id=promo["id"],
        )
        resp = api_client.create_order(payload, _customer)
        validate_error(resp, ApiErrorId.ERR_PROMOTION_NOT_VALID)

    def test_below_minimum_order(self):
        """ERR_BELOW_MINIMUM_ORDER when subtotal < minimum_order_cents."""
        promo = create_active_promotion(minimum_order_cents=5000)
        rest, items = setup_restaurant_with_menu_items(
            num_items=1, item_overrides=[{"base_price_cents": 1000}]
        )
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        customer = create_active_customer(wallet_cents=100000)
        payload = create_order_payload(
            customer["id"], rest["id"],
            [{"menu_item_id": items[0]["id"], "quantity": 1}],
            promotion_id=promo["id"],
        )
        resp = api_client.create_order(payload, _customer)
        validate_error(resp, ApiErrorId.ERR_BELOW_MINIMUM_ORDER)
