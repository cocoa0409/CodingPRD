"""Shop state-machine lifecycle tests: transitions, cascades, preconditions, terminal states."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
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
)


class TestShopApproval:
    """PENDING_REVIEW -> ACTIVE transition."""

    def test_approve_pending_shop(self, api, seller_headers, admin_headers):
        payload = create_shop_payload()
        shop = get_success_data(api.post("/shops", json=payload, headers=seller_headers))
        assert shop["status"] == "PENDING_REVIEW"

        resp = api.post(f"/shops/{shop['id']}/approve", headers=admin_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVE"
        assert data["monthly_gmv"] == 0
        assert data["settlement_balance"] == 0
        assert_shop_invariants(data)

    def test_approve_non_pending_shop_fails(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        resp = api.post(f"/shops/{shop['id']}/approve", headers=admin_headers)
        validate_error(resp, 409, ERR_SHOP_NOT_PENDING_REVIEW)

    def test_approve_twice_fails(self, api, seller_headers, admin_headers):
        payload = create_shop_payload()
        shop = get_success_data(api.post("/shops", json=payload, headers=seller_headers))
        api.post(f"/shops/{shop['id']}/approve", headers=admin_headers)
        resp = api.post(f"/shops/{shop['id']}/approve", headers=admin_headers)
        validate_error(resp, 409, ERR_SHOP_NOT_PENDING_REVIEW)


class TestShopSuspension:
    """ACTIVE -> SUSPENDED transition with cascade effects."""

    def test_suspend_active_shop(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        resp = api.post(f"/shops/{shop['id']}/suspend", headers=admin_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "SUSPENDED"

    def test_suspend_cascades_products_to_delisted(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        product = create_and_list_product(api, seller_headers, shop["id"])
        assert product["status"] == "LISTED"

        api.post(f"/shops/{shop['id']}/suspend", headers=admin_headers)

        resp = api.get(f"/products/{product['id']}", headers=seller_headers)
        updated = validate_success(resp, 200)
        assert updated["status"] == "DELISTED"

    def test_suspend_cascades_promotions_to_paused(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        promo = create_and_activate_promotion(api, seller_headers, shop["id"])
        assert promo["status"] == "ACTIVE"

        api.post(f"/shops/{shop['id']}/suspend", headers=admin_headers)

        resp = api.get(f"/promotions/{promo['id']}", headers=seller_headers)
        updated = validate_success(resp, 200)
        assert updated["status"] == "PAUSED"

    def test_suspend_non_active_shop_fails(self, api, seller_headers, admin_headers):
        payload = create_shop_payload()
        shop = get_success_data(api.post("/shops", json=payload, headers=seller_headers))
        # Shop is PENDING_REVIEW, not ACTIVE
        resp = api.post(f"/shops/{shop['id']}/suspend", headers=admin_headers)
        validate_error(resp, 409, ERR_SHOP_NOT_ACTIVE)


class TestShopReinstatement:
    """SUSPENDED -> ACTIVE transition — products/promotions NOT auto-restored."""

    def test_reinstate_suspended_shop(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        api.post(f"/shops/{shop['id']}/suspend", headers=admin_headers)
        resp = api.post(f"/shops/{shop['id']}/reinstate", headers=admin_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVE"

    def test_reinstate_does_not_restore_products(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        product = create_and_list_product(api, seller_headers, shop["id"])
        api.post(f"/shops/{shop['id']}/suspend", headers=admin_headers)
        api.post(f"/shops/{shop['id']}/reinstate", headers=admin_headers)

        resp = api.get(f"/products/{product['id']}", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "DELISTED"  # NOT restored to LISTED

    def test_reinstate_does_not_restore_promotions(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        promo = create_and_activate_promotion(api, seller_headers, shop["id"])
        api.post(f"/shops/{shop['id']}/suspend", headers=admin_headers)
        api.post(f"/shops/{shop['id']}/reinstate", headers=admin_headers)

        resp = api.get(f"/promotions/{promo['id']}", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "PAUSED"  # NOT restored to ACTIVE


class TestShopClosure:
    """ACTIVE/SUSPENDED -> CLOSED transition with preconditions and cascades."""

    def test_close_active_shop(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        resp = api.post(f"/shops/{shop['id']}/close", headers=admin_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "CLOSED"

    def test_close_suspended_shop(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        api.post(f"/shops/{shop['id']}/suspend", headers=admin_headers)
        resp = api.post(f"/shops/{shop['id']}/close", headers=admin_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "CLOSED"

    def test_close_cascades_products_to_archived(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        product = create_and_list_product(api, seller_headers, shop["id"])
        api.post(f"/shops/{shop['id']}/close", headers=admin_headers)

        resp = api.get(f"/products/{product['id']}", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "ARCHIVED"

    def test_close_cascades_promotions_to_cancelled(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        promo = create_and_activate_promotion(api, seller_headers, shop["id"])
        api.post(f"/shops/{shop['id']}/close", headers=admin_headers)

        resp = api.get(f"/promotions/{promo['id']}", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

    def test_close_shop_with_pending_orders_fails(self, api, seller_headers, admin_headers, customer_headers):
        scenario = setup_basic_order_scenario(api, seller_headers, admin_headers)
        order_payload = create_order_payload(
            shop_id=scenario["shop"]["id"],
            items=[{"product_id": scenario["products"][0]["id"], "quantity": 1}],
        )
        api.post("/orders", json=order_payload, headers=customer_headers)
        resp = api.post(f"/shops/{scenario['shop']['id']}/close", headers=admin_headers)
        validate_error(resp, 409, ERR_SHOP_HAS_PENDING_ORDERS)


class TestShopTerminalState:
    """CLOSED is terminal — no further transitions allowed."""

    def test_closed_shop_cannot_be_reinstated(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        api.post(f"/shops/{shop['id']}/close", headers=admin_headers)
        resp = api.post(f"/shops/{shop['id']}/reinstate", headers=admin_headers)
        validate_error(resp, 409)

    def test_closed_shop_cannot_be_suspended(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        api.post(f"/shops/{shop['id']}/close", headers=admin_headers)
        resp = api.post(f"/shops/{shop['id']}/suspend", headers=admin_headers)
        validate_error(resp, 409)

    def test_closed_shop_cannot_be_approved(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        api.post(f"/shops/{shop['id']}/close", headers=admin_headers)
        resp = api.post(f"/shops/{shop['id']}/approve", headers=admin_headers)
        validate_error(resp, 409)
