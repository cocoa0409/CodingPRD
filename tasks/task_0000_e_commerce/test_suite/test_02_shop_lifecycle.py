"""Shop state-machine lifecycle tests: transitions, cascades, preconditions, terminal states."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client,
    assert_shop, assert_product, assert_promotion, assert_shop_invariants,
    # factories
    create_shop_payload, create_product_payload, create_promotion_payload,
    create_order_payload,
    # fixtures
    create_and_approve_shop, create_and_list_product, create_and_activate_promotion,
    setup_shop_with_products, setup_basic_order_scenario,
    # errors
    ERR_SHOP_NOT_PENDING_REVIEW, ERR_SHOP_NOT_ACTIVE,
    ERR_SHOP_HAS_PENDING_ORDERS,
    # users
    SELLER_HEADERS, ADMIN_HEADERS, CUSTOMER_HEADERS,
)


class TestShopApproval:
    """PENDING_REVIEW -> ACTIVE transition."""

    def test_approve_pending_shop(self):
        payload = create_shop_payload()
        shop = get_success_data(api_client.create_shop(payload, SELLER_HEADERS))
        assert shop["status"] == "PENDING_REVIEW"

        resp = api_client.approve_shop(shop["id"], ADMIN_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVE"
        assert data["monthly_gmv"] == 0
        assert data["settlement_balance"] == 0
        assert_shop_invariants(data)

    def test_approve_non_pending_shop_fails(self):
        shop = create_and_approve_shop()
        resp = api_client.approve_shop(shop["id"], ADMIN_HEADERS)
        validate_error(resp, ERR_SHOP_NOT_PENDING_REVIEW, expected_status=409)

    def test_approve_twice_fails(self):
        payload = create_shop_payload()
        shop = get_success_data(api_client.create_shop(payload, SELLER_HEADERS))
        api_client.approve_shop(shop["id"], ADMIN_HEADERS)
        resp = api_client.approve_shop(shop["id"], ADMIN_HEADERS)
        validate_error(resp, ERR_SHOP_NOT_PENDING_REVIEW, expected_status=409)


class TestShopSuspension:
    """ACTIVE -> SUSPENDED transition with cascade effects."""

    def test_suspend_active_shop(self):
        shop = create_and_approve_shop()
        resp = api_client.suspend_shop(shop["id"], ADMIN_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "SUSPENDED"

    def test_suspend_cascades_products_to_delisted(self):
        shop = create_and_approve_shop()
        product = create_and_list_product(shop_id=shop["id"])
        assert product["status"] == "LISTED"

        api_client.suspend_shop(shop["id"], ADMIN_HEADERS)

        resp = api_client.get_product(shop["id"], product["id"], SELLER_HEADERS)
        updated = validate_success(resp, 200)
        assert updated["status"] == "DELISTED"

    def test_suspend_cascades_promotions_to_paused(self):
        shop = create_and_approve_shop()
        promo = create_and_activate_promotion(shop_id=shop["id"])
        assert promo["status"] == "ACTIVE"

        api_client.suspend_shop(shop["id"], ADMIN_HEADERS)

        resp = api_client.get_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        updated = validate_success(resp, 200)
        assert updated["status"] == "PAUSED"

    def test_suspend_non_active_shop_fails(self):
        payload = create_shop_payload()
        shop = get_success_data(api_client.create_shop(payload, SELLER_HEADERS))
        # Shop is PENDING_REVIEW, not ACTIVE
        resp = api_client.suspend_shop(shop["id"], ADMIN_HEADERS)
        validate_error(resp, ERR_SHOP_NOT_ACTIVE, expected_status=409)


class TestShopReinstatement:
    """SUSPENDED -> ACTIVE transition — products/promotions NOT auto-restored."""

    def test_reinstate_suspended_shop(self):
        shop = create_and_approve_shop()
        api_client.suspend_shop(shop["id"], ADMIN_HEADERS)
        resp = api_client.reinstate_shop(shop["id"], ADMIN_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVE"

    def test_reinstate_does_not_restore_products(self):
        shop = create_and_approve_shop()
        product = create_and_list_product(shop_id=shop["id"])
        api_client.suspend_shop(shop["id"], ADMIN_HEADERS)
        api_client.reinstate_shop(shop["id"], ADMIN_HEADERS)

        resp = api_client.get_product(shop["id"], product["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "DELISTED"  # NOT restored to LISTED

    def test_reinstate_does_not_restore_promotions(self):
        shop = create_and_approve_shop()
        promo = create_and_activate_promotion(shop_id=shop["id"])
        api_client.suspend_shop(shop["id"], ADMIN_HEADERS)
        api_client.reinstate_shop(shop["id"], ADMIN_HEADERS)

        resp = api_client.get_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "PAUSED"  # NOT restored to ACTIVE


class TestShopClosure:
    """ACTIVE/SUSPENDED -> CLOSED transition with preconditions and cascades."""

    def test_close_active_shop(self):
        shop = create_and_approve_shop()
        resp = api_client.close_shop(shop["id"], ADMIN_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "CLOSED"

    def test_close_suspended_shop(self):
        shop = create_and_approve_shop()
        api_client.suspend_shop(shop["id"], ADMIN_HEADERS)
        resp = api_client.close_shop(shop["id"], ADMIN_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "CLOSED"

    def test_close_cascades_products_to_archived(self):
        shop = create_and_approve_shop()
        product = create_and_list_product(shop_id=shop["id"])
        api_client.close_shop(shop["id"], ADMIN_HEADERS)

        resp = api_client.get_product(shop["id"], product["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "ARCHIVED"

    def test_close_cascades_promotions_to_cancelled(self):
        shop = create_and_approve_shop()
        promo = create_and_activate_promotion(shop_id=shop["id"])
        api_client.close_shop(shop["id"], ADMIN_HEADERS)

        resp = api_client.get_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

    def test_close_shop_with_pending_orders_fails(self):
        shop, product = setup_basic_order_scenario()
        order_payload = create_order_payload(
            shop_id=shop["id"],
            items=[{"product_id": product["id"], "quantity": 1}],
        )
        api_client.create_order(order_payload, CUSTOMER_HEADERS)
        resp = api_client.close_shop(shop["id"], ADMIN_HEADERS)
        validate_error(resp, ERR_SHOP_HAS_PENDING_ORDERS, expected_status=409)


class TestShopTerminalState:
    """CLOSED is terminal — no further transitions allowed."""

    def test_closed_shop_cannot_be_reinstated(self):
        shop = create_and_approve_shop()
        api_client.close_shop(shop["id"], ADMIN_HEADERS)
        resp = api_client.reinstate_shop(shop["id"], ADMIN_HEADERS)
        validate_error(resp, ERR_SHOP_NOT_ACTIVE, expected_status=409)

    def test_closed_shop_cannot_be_suspended(self):
        shop = create_and_approve_shop()
        api_client.close_shop(shop["id"], ADMIN_HEADERS)
        resp = api_client.suspend_shop(shop["id"], ADMIN_HEADERS)
        validate_error(resp, ERR_SHOP_NOT_ACTIVE, expected_status=409)

    def test_closed_shop_cannot_be_approved(self):
        shop = create_and_approve_shop()
        api_client.close_shop(shop["id"], ADMIN_HEADERS)
        resp = api_client.approve_shop(shop["id"], ADMIN_HEADERS)
        validate_error(resp, ERR_SHOP_NOT_PENDING_REVIEW, expected_status=409)
