"""CRUD tests for all entities: create, get, list, 404, validation, defaults, computed fields."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    # entity assertions
    assert_shop, assert_product, assert_promotion, assert_order, assert_order_item,
    assert_refund, assert_settlement,
    # factories
    create_shop_payload, create_product_payload, create_promotion_payload,
    create_order_payload, create_refund_payload, create_settlement_payload,
    # fixtures
    create_and_approve_shop, create_and_list_product, setup_basic_order_scenario,
    # errors
    ERR_SHOP_NOT_FOUND, ERR_PRODUCT_NOT_FOUND, ERR_PROMOTION_NOT_FOUND,
    ERR_INVALID_REQUEST,
)


# ---------------------------------------------------------------------------
# Shop CRUD
# ---------------------------------------------------------------------------
class TestShopCrud:
    """CRUD operations for the Shop entity."""

    def test_create_shop_valid(self, api, seller_headers):
        payload = create_shop_payload()
        resp = api.post("/shops", json=payload, headers=seller_headers)
        data = validate_success(resp, 201)
        assert_shop(data, expected_status="PENDING_REVIEW")
        assert data["name"] == payload["name"]

    def test_get_shop_by_id(self, api, seller_headers):
        payload = create_shop_payload()
        created = get_success_data(api.post("/shops", json=payload, headers=seller_headers))
        resp = api.get(f"/shops/{created['id']}", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["id"] == created["id"]
        assert data["name"] == created["name"]

    def test_list_shops_pagination(self, api, seller_headers):
        # Ensure at least one shop exists
        api.post("/shops", json=create_shop_payload(), headers=seller_headers)
        resp = api.get("/shops", params={"limit": 1}, headers=seller_headers)
        validate_paginated(resp, expected_limit=1)

    def test_get_shop_not_found(self, api, seller_headers):
        resp = api.get(f"/shops/{NON_EXISTENT_UUID}", headers=seller_headers)
        validate_error(resp, 404, ERR_SHOP_NOT_FOUND)

    @pytest.mark.parametrize("missing_field", ["name", "description"])
    def test_create_shop_missing_required(self, api, seller_headers, missing_field):
        payload = create_shop_payload()
        del payload[missing_field]
        resp = api.post("/shops", json=payload, headers=seller_headers)
        validate_error(resp, 400, ERR_INVALID_REQUEST)

    def test_create_shop_default_discount_strategy(self, api, seller_headers):
        payload = create_shop_payload()
        # Do not provide discount_strategy; should default to PERCENTAGE_FIRST
        payload.pop("discount_strategy", None)
        resp = api.post("/shops", json=payload, headers=seller_headers)
        data = validate_success(resp, 201)
        assert data.get("discount_strategy") == "PERCENTAGE_FIRST"


# ---------------------------------------------------------------------------
# Product CRUD
# ---------------------------------------------------------------------------
class TestProductCrud:
    """CRUD operations for the Product entity."""

    def test_create_product_valid(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_product_payload(shop_id=shop["id"])
        resp = api.post("/products", json=payload, headers=seller_headers)
        data = validate_success(resp, 201)
        assert_product(data, expected_status="DRAFT")
        assert data["name"] == payload["name"]

    def test_get_product_by_id(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_product_payload(shop_id=shop["id"])
        created = get_success_data(api.post("/products", json=payload, headers=seller_headers))
        resp = api.get(f"/products/{created['id']}", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["id"] == created["id"]

    def test_list_products_pagination(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        api.post("/products", json=create_product_payload(shop_id=shop["id"]), headers=seller_headers)
        resp = api.get("/products", params={"limit": 1, "shop_id": shop["id"]}, headers=seller_headers)
        validate_paginated(resp, expected_limit=1)

    def test_get_product_not_found(self, api, seller_headers):
        resp = api.get(f"/products/{NON_EXISTENT_UUID}", headers=seller_headers)
        validate_error(resp, 404, ERR_PRODUCT_NOT_FOUND)

    @pytest.mark.parametrize("missing_field", ["name", "base_price", "inventory_count"])
    def test_create_product_missing_required(self, api, seller_headers, admin_headers, missing_field):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_product_payload(shop_id=shop["id"])
        del payload[missing_field]
        resp = api.post("/products", json=payload, headers=seller_headers)
        validate_error(resp, 400, ERR_INVALID_REQUEST)

    def test_computed_fields_ignored_on_create(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_product_payload(shop_id=shop["id"])
        payload["reserved_count"] = 999
        payload["available_count"] = 888
        resp = api.post("/products", json=payload, headers=seller_headers)
        data = validate_success(resp, 201)
        # Server must compute these, not accept client values
        assert data["reserved_count"] == 0
        assert data["available_count"] == data["inventory_count"]


# ---------------------------------------------------------------------------
# Promotion CRUD
# ---------------------------------------------------------------------------
class TestPromotionCrud:
    """CRUD operations for the Promotion entity."""

    def test_create_promotion_valid(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_promotion_payload(shop_id=shop["id"])
        resp = api.post("/promotions", json=payload, headers=seller_headers)
        data = validate_success(resp, 201)
        assert_promotion(data, expected_status="DRAFT")

    def test_get_promotion_by_id(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_promotion_payload(shop_id=shop["id"])
        created = get_success_data(api.post("/promotions", json=payload, headers=seller_headers))
        resp = api.get(f"/promotions/{created['id']}", headers=seller_headers)
        data = validate_success(resp, 200)
        assert data["id"] == created["id"]

    def test_list_promotions_pagination(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        api.post("/promotions", json=create_promotion_payload(shop_id=shop["id"]), headers=seller_headers)
        resp = api.get("/promotions", params={"limit": 1, "shop_id": shop["id"]}, headers=seller_headers)
        validate_paginated(resp, expected_limit=1)

    def test_get_promotion_not_found(self, api, seller_headers):
        resp = api.get(f"/promotions/{NON_EXISTENT_UUID}", headers=seller_headers)
        validate_error(resp, 404, ERR_PROMOTION_NOT_FOUND)

    @pytest.mark.parametrize("missing_field", ["name", "discount_type", "discount_value", "start_time", "end_time", "priority"])
    def test_create_promotion_missing_required(self, api, seller_headers, admin_headers, missing_field):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_promotion_payload(shop_id=shop["id"])
        del payload[missing_field]
        resp = api.post("/promotions", json=payload, headers=seller_headers)
        validate_error(resp, 400, ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Order CRUD (with items)
# ---------------------------------------------------------------------------
class TestOrderCrud:
    """CRUD operations for the Order entity (includes order items)."""

    def test_create_order_valid(self, api, seller_headers, admin_headers, customer_headers):
        scenario = setup_basic_order_scenario(api, seller_headers, admin_headers)
        payload = create_order_payload(
            shop_id=scenario["shop"]["id"],
            items=[{"product_id": scenario["products"][0]["id"], "quantity": 1}],
        )
        resp = api.post("/orders", json=payload, headers=customer_headers)
        data = validate_success(resp, 201)
        assert_order(data, expected_status="PENDING_PAYMENT")
        assert len(data["items"]) >= 1
        assert_order_item(data["items"][0])

    def test_get_order_by_id(self, api, seller_headers, admin_headers, customer_headers):
        scenario = setup_basic_order_scenario(api, seller_headers, admin_headers)
        payload = create_order_payload(
            shop_id=scenario["shop"]["id"],
            items=[{"product_id": scenario["products"][0]["id"], "quantity": 1}],
        )
        created = get_success_data(api.post("/orders", json=payload, headers=customer_headers))
        resp = api.get(f"/orders/{created['id']}", headers=customer_headers)
        data = validate_success(resp, 200)
        assert data["id"] == created["id"]

    def test_list_orders_pagination(self, api, seller_headers, admin_headers, customer_headers):
        scenario = setup_basic_order_scenario(api, seller_headers, admin_headers)
        payload = create_order_payload(
            shop_id=scenario["shop"]["id"],
            items=[{"product_id": scenario["products"][0]["id"], "quantity": 1}],
        )
        api.post("/orders", json=payload, headers=customer_headers)
        resp = api.get("/orders", params={"limit": 1}, headers=customer_headers)
        validate_paginated(resp, expected_limit=1)

    @pytest.mark.parametrize("missing_field", ["shop_id", "items"])
    def test_create_order_missing_required(self, api, customer_headers, missing_field):
        payload = create_order_payload(
            shop_id=NON_EXISTENT_UUID,
            items=[{"product_id": NON_EXISTENT_UUID, "quantity": 1}],
        )
        del payload[missing_field]
        resp = api.post("/orders", json=payload, headers=customer_headers)
        validate_error(resp, 400, ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Refund CRUD
# ---------------------------------------------------------------------------
class TestRefundCrud:
    """CRUD operations for the Refund entity."""

    def test_create_refund_valid(self, api, seller_headers, admin_headers, customer_headers):
        scenario = setup_basic_order_scenario(api, seller_headers, admin_headers)
        order_payload = create_order_payload(
            shop_id=scenario["shop"]["id"],
            items=[{"product_id": scenario["products"][0]["id"], "quantity": 1}],
        )
        order = get_success_data(api.post("/orders", json=order_payload, headers=customer_headers))
        # Pay the order first
        pay_resp = api.post(f"/orders/{order['id']}/pay", json=create_payment_payload(), headers=customer_headers)
        validate_success(pay_resp, 200)
        # Request refund
        payload = create_refund_payload(order_id=order["id"])
        resp = api.post("/refunds", json=payload, headers=customer_headers)
        data = validate_success(resp, 201)
        assert_refund(data, expected_status="REQUESTED")

    def test_get_refund_not_found(self, api, customer_headers):
        resp = api.get(f"/refunds/{NON_EXISTENT_UUID}", headers=customer_headers)
        validate_error(resp, 404)


# ---------------------------------------------------------------------------
# Settlement CRUD
# ---------------------------------------------------------------------------
class TestSettlementCrud:
    """CRUD operations for the Settlement entity."""

    def test_create_settlement_valid(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        payload = create_settlement_payload(shop_id=shop["id"])
        resp = api.post("/settlements", json=payload, headers=admin_headers)
        data = validate_success(resp, 201)
        assert_settlement(data, expected_status="PENDING")

    def test_get_settlement_not_found(self, api, admin_headers):
        resp = api.get(f"/settlements/{NON_EXISTENT_UUID}", headers=admin_headers)
        validate_error(resp, 404)

    def test_list_settlements_pagination(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop(api, seller_headers, admin_headers)
        api.post("/settlements", json=create_settlement_payload(shop_id=shop["id"]), headers=admin_headers)
        resp = api.get("/settlements", params={"limit": 1, "shop_id": shop["id"]}, headers=admin_headers)
        validate_paginated(resp, expected_limit=1)


# ---------------------------------------------------------------------------
# Missing error coverage — ensuring every scaffold error code has a trigger
# ---------------------------------------------------------------------------

class TestMissingErrorCoverage:
    """Tests for error codes not covered by other files."""

    def test_order_not_found(self, api, customer_headers):
        """Table 6: ERR_ORDER_NOT_FOUND on non-existent order."""
        from test_helpers import api_client, ERR_ORDER_NOT_FOUND
        res = api_client.get_order(NON_EXISTENT_UUID, customer_headers)
        validate_error(res, ERR_ORDER_NOT_FOUND, expected_status=404)

    def test_refund_not_found(self, api, customer_headers):
        """Table 6: ERR_REFUND_NOT_FOUND on non-existent refund."""
        from test_helpers import api_client, create_paid_order, ERR_REFUND_NOT_FOUND
        shop, product = setup_basic_order_scenario()
        order, _ = create_paid_order(shop["id"], product["id"])
        res = api_client.get_refund(order["id"], NON_EXISTENT_UUID, customer_headers)
        validate_error(res, ERR_REFUND_NOT_FOUND, expected_status=404)

    def test_settlement_not_found(self, api, seller_headers):
        """Table 6: ERR_SETTLEMENT_NOT_FOUND on non-existent settlement."""
        from test_helpers import api_client, ERR_SETTLEMENT_NOT_FOUND
        shop = create_and_approve_shop()
        res = api_client.get_settlement(shop["id"], NON_EXISTENT_UUID, seller_headers)
        validate_error(res, ERR_SETTLEMENT_NOT_FOUND, expected_status=404)

    def test_order_item_not_found_in_refund(self, api, customer_headers):
        """Table 6: ERR_ORDER_ITEM_NOT_FOUND when refund references non-existent item."""
        from test_helpers import (
            api_client, create_paid_order, place_pay_and_deliver_order,
            create_refund_payload, ERR_ORDER_ITEM_NOT_FOUND,
        )
        shop, product = setup_basic_order_scenario()
        order = place_pay_and_deliver_order(
            shop["id"], [{"product_id": product["id"], "quantity": 1}]
        )
        refund_payload = create_refund_payload(
            refund_type="PARTIAL",
            refund_items=[{"order_item_id": NON_EXISTENT_UUID, "quantity": 1}],
        )
        res = api_client.create_refund(order["id"], refund_payload, customer_headers)
        validate_error(res, ERR_ORDER_ITEM_NOT_FOUND, expected_status=404)

    def test_refund_not_requested_for_approve(self, api, seller_headers):
        """Table 6: ERR_REFUND_NOT_REQUESTED when approving non-REQUESTED refund."""
        from test_helpers import (
            api_client, setup_completed_order_for_refund,
            create_refund_payload, ERR_REFUND_NOT_REQUESTED,
        )
        shop, product, order = setup_completed_order_for_refund()
        # Create and approve a refund first
        refund_payload = create_refund_payload(refund_type="FULL")
        res = api_client.create_refund(order["id"], refund_payload, seller_headers)
        refund = get_success_data(res)
        api_client.approve_refund(order["id"], refund["id"], seller_headers)
        # Try to approve again (now in APPROVED, not REQUESTED)
        res2 = api_client.approve_refund(order["id"], refund["id"], seller_headers)
        validate_error(res2, ERR_REFUND_NOT_REQUESTED, expected_status=409)

    def test_refund_not_approved_for_process(self, api, admin_headers):
        """Table 6: ERR_REFUND_NOT_APPROVED when processing non-APPROVED refund."""
        from test_helpers import (
            api_client, setup_completed_order_for_refund,
            create_refund_payload, ERR_REFUND_NOT_APPROVED,
        )
        shop, product, order = setup_completed_order_for_refund()
        refund_payload = create_refund_payload(refund_type="FULL")
        res = api_client.create_refund(order["id"], refund_payload, admin_headers)
        refund = get_success_data(res)
        # Try to process without approving (still REQUESTED)
        res2 = api_client.process_refund(order["id"], refund["id"], admin_headers)
        validate_error(res2, ERR_REFUND_NOT_APPROVED, expected_status=409)
