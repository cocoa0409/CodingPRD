"""Product and Promotion state-machine tests: transitions, preconditions, and error cases."""
import pytest
from datetime import datetime, timedelta, timezone
from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client,
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
    # users
    SELLER_HEADERS, ADMIN_HEADERS, CUSTOMER_HEADERS,
)


# ===========================================================================
# Product State Machine
# ===========================================================================

class TestProductListing:
    """DRAFT -> LISTED transition and preconditions."""

    def test_list_draft_product(self):
        shop = create_and_approve_shop()
        payload = create_product_payload()
        product = get_success_data(
            api_client.create_product(shop["id"], payload, SELLER_HEADERS)
        )
        assert product["status"] == "DRAFT"

        resp = api_client.list_product(shop["id"], product["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "LISTED"

    def test_list_requires_active_shop(self):
        shop = create_and_approve_shop()
        payload = create_product_payload()
        product = get_success_data(
            api_client.create_product(shop["id"], payload, SELLER_HEADERS)
        )
        # Suspend shop so it is no longer ACTIVE
        api_client.suspend_shop(shop["id"], ADMIN_HEADERS)

        resp = api_client.list_product(shop["id"], product["id"], SELLER_HEADERS)
        validate_error(resp, ERR_SHOP_NOT_ACTIVE, expected_status=409)

    def test_list_requires_positive_base_price(self):
        shop = create_and_approve_shop()
        payload = create_product_payload(base_price=0)
        product = get_success_data(
            api_client.create_product(shop["id"], payload, SELLER_HEADERS)
        )

        resp = api_client.list_product(shop["id"], product["id"], SELLER_HEADERS)
        validate_error(resp, ERR_INVALID_REQUEST, expected_status=400)

    def test_list_requires_non_negative_inventory(self):
        shop = create_and_approve_shop()
        payload = create_product_payload(inventory_count=-1)
        resp = api_client.create_product(shop["id"], payload, SELLER_HEADERS)
        # Should reject at creation or listing time
        validate_error(resp, ERR_INVALID_REQUEST, expected_status=400)


class TestProductDelist:
    """LISTED -> DELISTED transition."""

    def test_delist_listed_product(self):
        shop = create_and_approve_shop()
        product = create_and_list_product(shop_id=shop["id"])
        assert product["status"] == "LISTED"

        resp = api_client.delist_product(shop["id"], product["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "DELISTED"

    def test_delist_draft_product_fails(self):
        shop = create_and_approve_shop()
        payload = create_product_payload()
        product = get_success_data(
            api_client.create_product(shop["id"], payload, SELLER_HEADERS)
        )
        assert product["status"] == "DRAFT"

        resp = api_client.delist_product(shop["id"], product["id"], SELLER_HEADERS)
        validate_error(resp, ERR_PRODUCT_NOT_LISTED_FOR_DELIST, expected_status=409)


class TestProductRelist:
    """DELISTED -> LISTED transition."""

    def test_relist_delisted_product(self):
        shop = create_and_approve_shop()
        product = create_and_list_product(shop_id=shop["id"])
        api_client.delist_product(shop["id"], product["id"], SELLER_HEADERS)

        resp = api_client.list_product(shop["id"], product["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "LISTED"

    def test_relist_requires_active_shop(self):
        shop = create_and_approve_shop()
        product = create_and_list_product(shop_id=shop["id"])
        api_client.delist_product(shop["id"], product["id"], SELLER_HEADERS)
        api_client.suspend_shop(shop["id"], ADMIN_HEADERS)

        resp = api_client.list_product(shop["id"], product["id"], SELLER_HEADERS)
        validate_error(resp, ERR_SHOP_NOT_ACTIVE, expected_status=409)


class TestProductArchive:
    """LISTED/DELISTED -> ARCHIVED transition and preconditions."""

    def test_archive_delisted_product(self):
        shop = create_and_approve_shop()
        product = create_and_list_product(shop_id=shop["id"])
        api_client.delist_product(shop["id"], product["id"], SELLER_HEADERS)

        resp = api_client.archive_product(shop["id"], product["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "ARCHIVED"

    def test_archive_listed_product(self):
        shop = create_and_approve_shop()
        product = create_and_list_product(shop_id=shop["id"])

        resp = api_client.archive_product(shop["id"], product["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "ARCHIVED"

    def test_archive_with_reservations_fails(self):
        shop, product = setup_basic_order_scenario()
        # Create an order to generate reservations
        order_payload = create_order_payload(
            shop_id=shop["id"],
            items=[{"product_id": product["id"], "quantity": 1}],
        )
        api_client.create_order(order_payload, CUSTOMER_HEADERS)

        resp = api_client.archive_product(shop["id"], product["id"], SELLER_HEADERS)
        validate_error(resp, ERR_PRODUCT_HAS_RESERVATIONS, expected_status=409)

    def test_list_archived_product_fails(self):
        shop = create_and_approve_shop()
        product = create_and_list_product(shop_id=shop["id"])
        api_client.delist_product(shop["id"], product["id"], SELLER_HEADERS)
        api_client.archive_product(shop["id"], product["id"], SELLER_HEADERS)

        resp = api_client.list_product(shop["id"], product["id"], SELLER_HEADERS)
        validate_error(resp, ERR_PRODUCT_NOT_DRAFT_OR_DELISTED, expected_status=409)


# ===========================================================================
# Promotion State Machine
# ===========================================================================

class TestPromotionActivation:
    """DRAFT -> ACTIVE transition and preconditions."""

    def test_activate_draft_promotion(self):
        shop = create_and_approve_shop()
        payload = create_promotion_payload()
        promo = get_success_data(
            api_client.create_promotion(shop["id"], payload, SELLER_HEADERS)
        )
        assert promo["status"] == "DRAFT"

        resp = api_client.activate_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVE"

    def test_activate_requires_active_shop(self):
        shop = create_and_approve_shop()
        payload = create_promotion_payload()
        promo = get_success_data(
            api_client.create_promotion(shop["id"], payload, SELLER_HEADERS)
        )
        api_client.suspend_shop(shop["id"], ADMIN_HEADERS)

        resp = api_client.activate_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        validate_error(resp, ERR_SHOP_NOT_ACTIVE, expected_status=409)

    def test_activate_with_duplicate_priority_fails(self):
        shop = create_and_approve_shop()
        # Create and activate first promotion with priority=1
        p1 = create_promotion_payload(priority=1)
        promo1 = get_success_data(
            api_client.create_promotion(shop["id"], p1, SELLER_HEADERS)
        )
        api_client.activate_promotion(shop["id"], promo1["id"], SELLER_HEADERS)

        # Create second promotion with same priority=1
        p2 = create_promotion_payload(priority=1, promo_name="Test Promotion 2")
        promo2 = get_success_data(
            api_client.create_promotion(shop["id"], p2, SELLER_HEADERS)
        )
        resp = api_client.activate_promotion(shop["id"], promo2["id"], SELLER_HEADERS)
        validate_error(resp, ERR_DUPLICATE_PROMOTION_PRIORITY, expected_status=409)

    def test_activate_expired_promotion_fails(self):
        shop = create_and_approve_shop()
        # Create promotion with end_time in the past
        now = datetime.now(timezone.utc)
        payload = create_promotion_payload(
            start_time=(now - timedelta(days=10)).isoformat(),
            end_time=(now - timedelta(days=1)).isoformat(),
        )
        promo = get_success_data(
            api_client.create_promotion(shop["id"], payload, SELLER_HEADERS)
        )

        resp = api_client.activate_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        validate_error(resp, ERR_PROMOTION_EXPIRED, expected_status=409)


class TestPromotionPause:
    """ACTIVE -> PAUSED transition."""

    def test_pause_active_promotion(self):
        shop = create_and_approve_shop()
        promo = create_and_activate_promotion(shop_id=shop["id"])
        assert promo["status"] == "ACTIVE"

        resp = api_client.pause_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "PAUSED"

    def test_pause_non_active_promotion_fails(self):
        shop = create_and_approve_shop()
        payload = create_promotion_payload()
        promo = get_success_data(
            api_client.create_promotion(shop["id"], payload, SELLER_HEADERS)
        )
        # Promotion is DRAFT, not ACTIVE
        resp = api_client.pause_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        validate_error(resp, ERR_PROMOTION_NOT_ACTIVE, expected_status=409)


class TestPromotionReactivation:
    """PAUSED -> ACTIVE transition with same preconditions as initial activation."""

    def test_reactivate_paused_promotion(self):
        shop = create_and_approve_shop()
        promo = create_and_activate_promotion(shop_id=shop["id"])
        api_client.pause_promotion(shop["id"], promo["id"], SELLER_HEADERS)

        resp = api_client.activate_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVE"

    def test_reactivate_requires_active_shop(self):
        shop = create_and_approve_shop()
        promo = create_and_activate_promotion(shop_id=shop["id"])
        api_client.pause_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        api_client.suspend_shop(shop["id"], ADMIN_HEADERS)

        resp = api_client.activate_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        validate_error(resp, ERR_SHOP_NOT_ACTIVE, expected_status=409)

    def test_reactivate_with_duplicate_priority_fails(self):
        shop = create_and_approve_shop()
        # Activate promo1 at priority 5
        p1 = create_promotion_payload(priority=5)
        promo1 = get_success_data(
            api_client.create_promotion(shop["id"], p1, SELLER_HEADERS)
        )
        api_client.activate_promotion(shop["id"], promo1["id"], SELLER_HEADERS)

        # Activate promo2 at priority 6, then pause it
        p2 = create_promotion_payload(priority=6, promo_name="Test Promotion 2")
        promo2 = get_success_data(
            api_client.create_promotion(shop["id"], p2, SELLER_HEADERS)
        )
        api_client.activate_promotion(shop["id"], promo2["id"], SELLER_HEADERS)
        api_client.pause_promotion(shop["id"], promo2["id"], SELLER_HEADERS)

        # Pause promo1, then activate a new promo3 at priority 5
        api_client.pause_promotion(shop["id"], promo1["id"], SELLER_HEADERS)

        p3 = create_promotion_payload(priority=5, promo_name="Test Promotion 3")
        promo3 = get_success_data(
            api_client.create_promotion(shop["id"], p3, SELLER_HEADERS)
        )
        api_client.activate_promotion(shop["id"], promo3["id"], SELLER_HEADERS)

        # Now try to reactivate promo1 which also has priority 5
        resp = api_client.activate_promotion(shop["id"], promo1["id"], SELLER_HEADERS)
        validate_error(resp, ERR_DUPLICATE_PROMOTION_PRIORITY, expected_status=409)


class TestPromotionCancellation:
    """DRAFT/ACTIVE/PAUSED -> CANCELLED transition."""

    def test_cancel_draft_promotion(self):
        shop = create_and_approve_shop()
        payload = create_promotion_payload()
        promo = get_success_data(
            api_client.create_promotion(shop["id"], payload, SELLER_HEADERS)
        )

        resp = api_client.cancel_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

    def test_cancel_active_promotion(self):
        shop = create_and_approve_shop()
        promo = create_and_activate_promotion(shop_id=shop["id"])

        resp = api_client.cancel_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

    def test_cancel_paused_promotion(self):
        shop = create_and_approve_shop()
        promo = create_and_activate_promotion(shop_id=shop["id"])
        api_client.pause_promotion(shop["id"], promo["id"], SELLER_HEADERS)

        resp = api_client.cancel_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        data = validate_success(resp, 200)
        assert data["status"] == "CANCELLED"

    def test_cancelled_promotion_cannot_be_activated(self):
        shop = create_and_approve_shop()
        payload = create_promotion_payload()
        promo = get_success_data(
            api_client.create_promotion(shop["id"], payload, SELLER_HEADERS)
        )
        api_client.cancel_promotion(shop["id"], promo["id"], SELLER_HEADERS)

        resp = api_client.activate_promotion(shop["id"], promo["id"], SELLER_HEADERS)
        validate_error(resp, ERR_PROMOTION_NOT_DRAFT_OR_PAUSED, expected_status=409)
