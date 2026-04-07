"""Product and Promotion state-machine tests: transitions, preconditions, and error cases."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    assert_product, assert_promotion,
    # factories
    create_shop_payload, create_product_payload, create_promotion_payload,
    create_order_payload,
    # fixtures
    create_and_approve_shop, create_and_list_product, create_and_activate_promotion,
    setup_basic_order_scenario,
    # errors
    ERR_SHOP_NOT_ACTIVE, ERR_PRODUCT_NOT_DRAFT_OR_DELISTED,
    ERR_PRODUCT_NOT_LISTED, ERR_PRODUCT_NOT_LISTED_FOR_DELIST,
    ERR_PRODUCT_HAS_RESERVATIONS, ERR_PROMOTION_NOT_DRAFT_OR_PAUSED,
    ERR_PROMOTION_NOT_ACTIVE, ERR_DUPLICATE_PROMOTION_PRIORITY,
    ERR_PROMOTION_EXPIRED, ERR_INVALID_REQUEST,
)


# ===========================================================================
# Product State Machine
# ===========================================================================

class TestProductListing:
    """DRAFT -> LISTED transition and preconditions."""

    def test_list_draft_product(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_product_payload(shop_id=shop["id"])
        product = get_success_data(api.post("/products", json=payload, headers=seller_headers))
        assert product["status"] == "DRAFT"

        resp = api.post(f"/products/{product['id']}/list", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "LISTED"

    def test_list_requires_active_shop(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_product_payload(shop_id=shop["id"])
        product = get_success_data(api.post("/products", json=payload, headers=seller_headers))
        # Suspend shop so it is no longer ACTIVE
        api.post(f"/shops/{shop['id']}/suspend", headers=admin_headers)

        resp = api.post(f"/products/{product['id']}/list", headers=seller_headers)
        validate_error(resp, 409, ERR_SHOP_NOT_ACTIVE)

    def test_list_requires_positive_base_price(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_product_payload(shop_id=shop["id"], base_price=0)
        product = get_success_data(api.post("/products", json=payload, headers=seller_headers))

        resp = api.post(f"/products/{product['id']}/list", headers=seller_headers)
        validate_error(resp, 400, ERR_INVALID_REQUEST)

    def test_list_requires_non_negative_inventory(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_product_payload(shop_id=shop["id"], inventory_count=-1)
        resp = api.post("/products", json=payload, headers=seller_headers)
        # Should reject at creation or listing time
        validate_error(resp, 400, ERR_INVALID_REQUEST)


class TestProductDelist:
    """LISTED -> DELISTED transition."""

    def test_delist_listed_product(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        product = create_and_list_product(api, seller_headers, shop["id"])
        assert product["status"] == "LISTED"

        resp = api.post(f"/products/{product['id']}/delist", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "DELISTED"

    def test_delist_draft_product_fails(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_product_payload(shop_id=shop["id"])
        product = get_success_data(api.post("/products", json=payload, headers=seller_headers))
        assert product["status"] == "DRAFT"

        resp = api.post(f"/products/{product['id']}/delist", headers=seller_headers)
        validate_error(resp, 409, ERR_PRODUCT_NOT_LISTED_FOR_DELIST)


class TestProductRelist:
    """DELISTED -> LISTED transition."""

    def test_relist_delisted_product(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        product = create_and_list_product(api, seller_headers, shop["id"])
        api.post(f"/products/{product['id']}/delist", headers=seller_headers)

        resp = api.post(f"/products/{product['id']}/list", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "LISTED"

    def test_relist_requires_active_shop(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        product = create_and_list_product(api, seller_headers, shop["id"])
        api.post(f"/products/{product['id']}/delist", headers=seller_headers)
        api.post(f"/shops/{shop['id']}/suspend", headers=admin_headers)

        resp = api.post(f"/products/{product['id']}/list", headers=seller_headers)
        validate_error(resp, 409, ERR_SHOP_NOT_ACTIVE)


class TestProductArchive:
    """LISTED/DELISTED -> ARCHIVED transition and preconditions."""

    def test_archive_delisted_product(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        product = create_and_list_product(api, seller_headers, shop["id"])
        api.post(f"/products/{product['id']}/delist", headers=seller_headers)

        resp = api.post(f"/products/{product['id']}/archive", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "ARCHIVED"

    def test_archive_listed_product(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        product = create_and_list_product(api, seller_headers, shop["id"])

        resp = api.post(f"/products/{product['id']}/archive", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "ARCHIVED"

    def test_archive_with_reservations_fails(self, api, seller_headers, admin_headers, customer_headers):
        scenario = setup_basic_order_scenario(api, seller_headers, admin_headers)
        product = scenario["products"][0]
        # Create an order to generate reservations
        order_payload = create_order_payload(
            shop_id=scenario["shop"]["id"],
            items=[{"product_id": product["id"], "quantity": 1}],
        )
        api.post("/orders", json=order_payload, headers=customer_headers)

        resp = api.post(f"/products/{product['id']}/archive", headers=seller_headers)
        validate_error(resp, 409, ERR_PRODUCT_HAS_RESERVATIONS)

    def test_list_archived_product_fails(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        product = create_and_list_product(api, seller_headers, shop["id"])
        api.post(f"/products/{product['id']}/delist", headers=seller_headers)
        api.post(f"/products/{product['id']}/archive", headers=seller_headers)

        resp = api.post(f"/products/{product['id']}/list", headers=seller_headers)
        validate_error(resp, 409, ERR_PRODUCT_NOT_DRAFT_OR_DELISTED)


# ===========================================================================
# Promotion State Machine
# ===========================================================================

class TestPromotionActivation:
    """DRAFT -> ACTIVE transition and preconditions."""

    def test_activate_draft_promotion(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_promotion_payload(shop_id=shop["id"])
        promo = get_success_data(api.post("/promotions", json=payload, headers=seller_headers))
        assert promo["status"] == "DRAFT"

        resp = api.post(f"/promotions/{promo['id']}/activate", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVE"

    def test_activate_requires_active_shop(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_promotion_payload(shop_id=shop["id"])
        promo = get_success_data(api.post("/promotions", json=payload, headers=seller_headers))
        api.post(f"/shops/{shop['id']}/suspend", headers=admin_headers)

        resp = api.post(f"/promotions/{promo['id']}/activate", headers=seller_headers)
        validate_error(resp, 409, ERR_SHOP_NOT_ACTIVE)

    def test_activate_with_duplicate_priority_fails(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        # Create and activate first promotion with priority=1
        p1 = create_promotion_payload(shop_id=shop["id"], priority=1)
        promo1 = get_success_data(api.post("/promotions", json=p1, headers=seller_headers))
        api.post(f"/promotions/{promo1['id']}/activate", headers=seller_headers)

        # Create second promotion with same priority=1
        p2 = create_promotion_payload(shop_id=shop["id"], priority=1)
        promo2 = get_success_data(api.post("/promotions", json=p2, headers=seller_headers))
        resp = api.post(f"/promotions/{promo2['id']}/activate", headers=seller_headers)
        validate_error(resp, 409, ERR_DUPLICATE_PROMOTION_PRIORITY)

    def test_activate_expired_promotion_fails(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        # Create promotion with end_time in the past
        payload = create_promotion_payload(shop_id=shop["id"], expired=True)
        promo = get_success_data(api.post("/promotions", json=payload, headers=seller_headers))

        resp = api.post(f"/promotions/{promo['id']}/activate", headers=seller_headers)
        validate_error(resp, 409, ERR_PROMOTION_EXPIRED)


class TestPromotionPause:
    """ACTIVE -> PAUSED transition."""

    def test_pause_active_promotion(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        promo = create_and_activate_promotion(api, seller_headers, shop["id"])
        assert promo["status"] == "ACTIVE"

        resp = api.post(f"/promotions/{promo['id']}/pause", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "PAUSED"

    def test_pause_non_active_promotion_fails(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_promotion_payload(shop_id=shop["id"])
        promo = get_success_data(api.post("/promotions", json=payload, headers=seller_headers))
        # Promotion is DRAFT, not ACTIVE
        resp = api.post(f"/promotions/{promo['id']}/pause", headers=seller_headers)
        validate_error(resp, 409, ERR_PROMOTION_NOT_ACTIVE)


class TestPromotionReactivation:
    """PAUSED -> ACTIVE transition with same preconditions as initial activation."""

    def test_reactivate_paused_promotion(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        promo = create_and_activate_promotion(api, seller_headers, shop["id"])
        api.post(f"/promotions/{promo['id']}/pause", headers=seller_headers)

        resp = api.post(f"/promotions/{promo['id']}/activate", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVE"

    def test_reactivate_requires_active_shop(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        promo = create_and_activate_promotion(api, seller_headers, shop["id"])
        api.post(f"/promotions/{promo['id']}/pause", headers=seller_headers)
        api.post(f"/shops/{shop['id']}/suspend", headers=admin_headers)

        resp = api.post(f"/promotions/{promo['id']}/activate", headers=seller_headers)
        validate_error(resp, 409, ERR_SHOP_NOT_ACTIVE)

    def test_reactivate_with_duplicate_priority_fails(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        # Activate promo1 at priority 5
        p1 = create_promotion_payload(shop_id=shop["id"], priority=5)
        promo1 = get_success_data(api.post("/promotions", json=p1, headers=seller_headers))
        api.post(f"/promotions/{promo1['id']}/activate", headers=seller_headers)

        # Activate promo2 at priority 6, then pause it
        p2 = create_promotion_payload(shop_id=shop["id"], priority=6)
        promo2 = get_success_data(api.post("/promotions", json=p2, headers=seller_headers))
        api.post(f"/promotions/{promo2['id']}/activate", headers=seller_headers)
        api.post(f"/promotions/{promo2['id']}/pause", headers=seller_headers)

        # Change promo2's priority to 5 (if update is supported) or create scenario
        # where conflict arises — simplest: pause promo1, activate new promo at 5, then
        # try to reactivate promo1 which also has priority 5
        api.post(f"/promotions/{promo1['id']}/pause", headers=seller_headers)

        p3 = create_promotion_payload(shop_id=shop["id"], priority=5)
        promo3 = get_success_data(api.post("/promotions", json=p3, headers=seller_headers))
        api.post(f"/promotions/{promo3['id']}/activate", headers=seller_headers)

        # Now try to reactivate promo1 which also has priority 5
        resp = api.post(f"/promotions/{promo1['id']}/activate", headers=seller_headers)
        validate_error(resp, 409, ERR_DUPLICATE_PROMOTION_PRIORITY)


class TestPromotionCancellation:
    """DRAFT/ACTIVE/PAUSED -> CANCELLED transition."""

    def test_cancel_draft_promotion(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_promotion_payload(shop_id=shop["id"])
        promo = get_success_data(api.post("/promotions", json=payload, headers=seller_headers))

        resp = api.post(f"/promotions/{promo['id']}/cancel", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

    def test_cancel_active_promotion(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        promo = create_and_activate_promotion(api, seller_headers, shop["id"])

        resp = api.post(f"/promotions/{promo['id']}/cancel", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

    def test_cancel_paused_promotion(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        promo = create_and_activate_promotion(api, seller_headers, shop["id"])
        api.post(f"/promotions/{promo['id']}/pause", headers=seller_headers)

        resp = api.post(f"/promotions/{promo['id']}/cancel", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

    def test_cancelled_promotion_cannot_be_activated(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_promotion_payload(shop_id=shop["id"])
        promo = get_success_data(api.post("/promotions", json=payload, headers=seller_headers))
        api.post(f"/promotions/{promo['id']}/cancel", headers=seller_headers)

        resp = api.post(f"/promotions/{promo['id']}/activate", headers=seller_headers)
        validate_error(resp, 409, ERR_PROMOTION_NOT_DRAFT_OR_PAUSED)
