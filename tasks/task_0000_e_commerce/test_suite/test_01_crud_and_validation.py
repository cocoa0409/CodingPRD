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
    create_payment_payload,
    # fixtures
    create_and_approve_shop, create_and_list_product, setup_basic_order_scenario,
    setup_completed_order_for_refund, place_pay_and_deliver_order,
    create_paid_order, get_order_items,
    # typed client
    api_client,
    # errors
    ERR_SHOP_NOT_FOUND, ERR_PRODUCT_NOT_FOUND, ERR_PROMOTION_NOT_FOUND,
    ERR_ORDER_NOT_FOUND, ERR_REFUND_NOT_FOUND, ERR_SETTLEMENT_NOT_FOUND,
    ERR_ORDER_ITEM_NOT_FOUND, ERR_REFUND_NOT_REQUESTED, ERR_REFUND_NOT_APPROVED,
    ERR_INVALID_REQUEST, ERR_AUTH_HEADER_MISSING,
)


# ---------------------------------------------------------------------------
# Shop CRUD
# ---------------------------------------------------------------------------
class TestShopCrud:
    """CRUD operations for the Shop entity."""

    def test_create_shop_valid(self, api, seller_headers):
        payload = create_shop_payload()
        resp = api.create_shop(payload, seller_headers)
        data = validate_success(resp, 201)
        assert_shop(data)
        assert data["status"] == "PENDING_REVIEW"
        assert data["shop_name"] == payload["shop_name"]

    def test_get_shop_by_id(self, api, seller_headers):
        payload = create_shop_payload()
        created = get_success_data(api.create_shop(payload, seller_headers))
        resp = api.get_shop(created["id"], seller_headers)
        data = validate_success(resp, 200)
        assert data["id"] == created["id"]
        assert data["shop_name"] == created["shop_name"]

    def test_list_shops_pagination(self, api, seller_headers):
        # Ensure at least one shop exists
        api.create_shop(create_shop_payload(), seller_headers)
        resp = api.list_shops(seller_headers, params={"limit": 1})
        items, meta = validate_paginated(resp)
        assert meta["limit"] == 1

    def test_get_shop_not_found(self, api, seller_headers):
        resp = api.get_shop(NON_EXISTENT_UUID, seller_headers)
        validate_error(resp, ERR_SHOP_NOT_FOUND)

    @pytest.mark.parametrize("missing_field", ["shop_name", "owner_id"])
    def test_create_shop_missing_required(self, api, seller_headers, missing_field):
        payload = create_shop_payload()
        if missing_field == "owner_id":
            # The route auto-fills owner_id from the authenticated user header,
            # so we must also strip the header to trigger validation.
            # Build headers without X-User-ID to trigger missing owner_id.
            no_user_headers = {k: v for k, v in seller_headers.items() if k != "X-User-ID"}
            del payload[missing_field]
            resp = api.create_shop(payload, no_user_headers)
            # Missing auth header returns ERR_AUTH_HEADER_MISSING, which is fine
            # since it proves owner_id can't be omitted.
            validate_error(resp, ERR_AUTH_HEADER_MISSING)
        else:
            del payload[missing_field]
            resp = api.create_shop(payload, seller_headers)
            validate_error(resp, ERR_INVALID_REQUEST)

    def test_create_shop_default_discount_strategy(self, api, seller_headers):
        payload = create_shop_payload()
        # Do not provide discount_strategy; should default to PERCENTAGE_FIRST
        payload.pop("discount_strategy", None)
        resp = api.create_shop(payload, seller_headers)
        data = validate_success(resp, 201)
        assert data.get("discount_strategy") == "PERCENTAGE_FIRST"


# ---------------------------------------------------------------------------
# Product CRUD
# ---------------------------------------------------------------------------
class TestProductCrud:
    """CRUD operations for the Product entity."""

    def test_create_product_valid(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop()
        payload = create_product_payload()
        resp = api.create_product(shop["id"], payload, seller_headers)
        data = validate_success(resp, 201)
        assert_product(data)
        assert data["status"] == "DRAFT"
        assert data["product_name"] == payload["product_name"]

    def test_get_product_by_id(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop()
        payload = create_product_payload()
        created = get_success_data(api.create_product(shop["id"], payload, seller_headers))
        resp = api.get_product(shop["id"], created["id"], seller_headers)
        data = validate_success(resp, 200)
        assert data["id"] == created["id"]

    def test_list_products_pagination(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop()
        api.create_product(shop["id"], create_product_payload(), seller_headers)
        resp = api.list_products(shop["id"], seller_headers, params={"limit": 1})
        items, meta = validate_paginated(resp)
        assert meta["limit"] == 1

    def test_get_product_not_found(self, api, seller_headers):
        # Need a valid shop_id for the nested path
        shop = create_and_approve_shop()
        resp = api.get_product(shop["id"], NON_EXISTENT_UUID, seller_headers)
        validate_error(resp, ERR_PRODUCT_NOT_FOUND)

    @pytest.mark.parametrize("missing_field", ["product_name", "base_price", "inventory_count"])
    def test_create_product_missing_required(self, api, seller_headers, admin_headers, missing_field):
        shop = create_and_approve_shop()
        payload = create_product_payload()
        del payload[missing_field]
        resp = api.create_product(shop["id"], payload, seller_headers)
        validate_error(resp, ERR_INVALID_REQUEST)

    def test_computed_fields_ignored_on_create(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop()
        payload = create_product_payload()
        payload["reserved_count"] = 999
        payload["available_count"] = 888
        resp = api.create_product(shop["id"], payload, seller_headers)
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
        shop = create_and_approve_shop()
        payload = create_promotion_payload()
        resp = api.create_promotion(shop["id"], payload, seller_headers)
        data = validate_success(resp, 201)
        assert_promotion(data)
        assert data["status"] == "DRAFT"

    def test_get_promotion_by_id(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop()
        payload = create_promotion_payload()
        created = get_success_data(api.create_promotion(shop["id"], payload, seller_headers))
        resp = api.get_promotion(shop["id"], created["id"], seller_headers)
        data = validate_success(resp, 200)
        assert data["id"] == created["id"]

    def test_list_promotions_pagination(self, api, seller_headers, admin_headers):
        shop = create_and_approve_shop()
        api.create_promotion(shop["id"], create_promotion_payload(), seller_headers)
        resp = api.list_promotions(shop["id"], seller_headers, params={"limit": 1})
        items, meta = validate_paginated(resp)
        assert meta["limit"] == 1

    def test_get_promotion_not_found(self, api, seller_headers):
        shop = create_and_approve_shop()
        resp = api.get_promotion(shop["id"], NON_EXISTENT_UUID, seller_headers)
        validate_error(resp, ERR_PROMOTION_NOT_FOUND)

    @pytest.mark.parametrize("missing_field", [
        "promo_name", "promo_type", "promo_value", "start_time", "end_time", "priority",
    ])
    def test_create_promotion_missing_required(self, api, seller_headers, admin_headers, missing_field):
        shop = create_and_approve_shop()
        payload = create_promotion_payload()
        del payload[missing_field]
        resp = api.create_promotion(shop["id"], payload, seller_headers)
        validate_error(resp, ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Order CRUD (with items)
# ---------------------------------------------------------------------------
class TestOrderCrud:
    """CRUD operations for the Order entity (includes order items)."""

    def test_create_order_valid(self, api, seller_headers, admin_headers, customer_headers):
        shop, product = setup_basic_order_scenario()
        payload = create_order_payload(
            shop_id=shop["id"],
            items=[{"product_id": product["id"], "quantity": 1}],
        )
        resp = api.create_order(payload, customer_headers)
        data = validate_success(resp, 201)
        assert_order(data)
        assert data["payment_status"] == "UNPAID"
        assert len(data["items"]) >= 1
        assert_order_item(data["items"][0])

    def test_get_order_by_id(self, api, seller_headers, admin_headers, customer_headers):
        shop, product = setup_basic_order_scenario()
        payload = create_order_payload(
            shop_id=shop["id"],
            items=[{"product_id": product["id"], "quantity": 1}],
        )
        created = get_success_data(api.create_order(payload, customer_headers))
        resp = api.get_order(created["id"], customer_headers)
        data = validate_success(resp, 200)
        assert data["id"] == created["id"]

    def test_list_orders_pagination(self, api, seller_headers, admin_headers, customer_headers):
        shop, product = setup_basic_order_scenario()
        payload = create_order_payload(
            shop_id=shop["id"],
            items=[{"product_id": product["id"], "quantity": 1}],
        )
        api.create_order(payload, customer_headers)
        resp = api.list_orders(customer_headers, params={"limit": 1})
        items, meta = validate_paginated(resp)
        assert meta["limit"] == 1

    @pytest.mark.parametrize("missing_field", ["shop_id", "items"])
    def test_create_order_missing_required(self, api, customer_headers, missing_field):
        payload = create_order_payload(
            shop_id=NON_EXISTENT_UUID,
            items=[{"product_id": NON_EXISTENT_UUID, "quantity": 1}],
        )
        del payload[missing_field]
        resp = api.create_order(payload, customer_headers)
        validate_error(resp, ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Refund CRUD
# ---------------------------------------------------------------------------
class TestRefundCrud:
    """CRUD operations for the Refund entity."""

    def test_create_refund_valid(self, api, seller_headers, admin_headers, customer_headers):
        shop, product, order = setup_completed_order_for_refund()
        # Request refund (order is already paid & delivered)
        payload = create_refund_payload(refund_type="FULL")
        resp = api.create_refund(order["id"], payload, customer_headers)
        data = validate_success(resp, 201)
        assert_refund(data)
        assert data["status"] == "REQUESTED"

    def test_get_refund_not_found(self, api, customer_headers):
        # Need a valid order to hit the nested refund path
        shop, product = setup_basic_order_scenario()
        paid_order, _ = create_paid_order(shop["id"], product["id"])
        resp = api.get_refund(paid_order["id"], NON_EXISTENT_UUID, customer_headers)
        validate_error(resp, ERR_REFUND_NOT_FOUND)


# ---------------------------------------------------------------------------
# Settlement CRUD
# ---------------------------------------------------------------------------
class TestSettlementCrud:
    """CRUD operations for the Settlement entity."""

    def test_create_settlement_valid(self, api, seller_headers):
        shop = create_and_approve_shop()
        payload = create_settlement_payload()
        resp = api.create_settlement(shop["id"], payload, seller_headers)
        data = validate_success(resp, 201)
        assert_settlement(data)
        assert data["status"] == "DRAFT"

    def test_get_settlement_not_found(self, api, seller_headers):
        shop = create_and_approve_shop()
        resp = api.get_settlement(shop["id"], NON_EXISTENT_UUID, seller_headers)
        validate_error(resp, ERR_SETTLEMENT_NOT_FOUND)

    def test_list_settlements_pagination(self, api, seller_headers):
        shop = create_and_approve_shop()
        api.create_settlement(shop["id"], create_settlement_payload(), seller_headers)
        resp = api.list_settlements(shop["id"], seller_headers, params={"limit": 1})
        items, meta = validate_paginated(resp)
        assert meta["limit"] == 1


# ---------------------------------------------------------------------------
# Missing error coverage -- ensuring every scaffold error code has a trigger
# ---------------------------------------------------------------------------
class TestMissingErrorCoverage:
    """Tests for error codes not covered by other files."""

    def test_order_not_found(self, api, customer_headers):
        """Table 6: ERR_ORDER_NOT_FOUND on non-existent order."""
        resp = api.get_order(NON_EXISTENT_UUID, customer_headers)
        validate_error(resp, ERR_ORDER_NOT_FOUND)

    def test_refund_not_found(self, api, customer_headers):
        """Table 6: ERR_REFUND_NOT_FOUND on non-existent refund."""
        shop, product = setup_basic_order_scenario()
        order, _ = create_paid_order(shop["id"], product["id"])
        resp = api.get_refund(order["id"], NON_EXISTENT_UUID, customer_headers)
        validate_error(resp, ERR_REFUND_NOT_FOUND)

    def test_settlement_not_found(self, api, seller_headers):
        """Table 6: ERR_SETTLEMENT_NOT_FOUND on non-existent settlement."""
        shop = create_and_approve_shop()
        resp = api.get_settlement(shop["id"], NON_EXISTENT_UUID, seller_headers)
        validate_error(resp, ERR_SETTLEMENT_NOT_FOUND)

    def test_order_item_not_found_in_refund(self, api, customer_headers):
        """Table 6: ERR_ORDER_ITEM_NOT_FOUND when refund references non-existent item."""
        shop, product, order = setup_completed_order_for_refund()
        refund_payload = create_refund_payload(
            refund_type="PARTIAL",
            refund_items=[{"order_item_id": NON_EXISTENT_UUID, "quantity": 1}],
        )
        resp = api.create_refund(order["id"], refund_payload, customer_headers)
        validate_error(resp, ERR_ORDER_ITEM_NOT_FOUND)

    def test_refund_not_requested_for_approve(self, api, seller_headers, customer_headers):
        """Table 6: ERR_REFUND_NOT_REQUESTED when approving non-REQUESTED refund."""
        shop, product, order = setup_completed_order_for_refund()
        # Create refund as customer, then approve as seller
        refund_payload = create_refund_payload(refund_type="FULL")
        refund = get_success_data(
            api.create_refund(order["id"], refund_payload, customer_headers)
        )
        get_success_data(
            api.approve_refund(order["id"], refund["id"], seller_headers)
        )
        # Try to approve again (now in APPROVED, not REQUESTED)
        resp = api.approve_refund(order["id"], refund["id"], seller_headers)
        validate_error(resp, ERR_REFUND_NOT_REQUESTED, expected_status=409)

    def test_refund_not_approved_for_process(self, api, customer_headers, admin_headers):
        """Table 6: ERR_REFUND_NOT_APPROVED when processing non-APPROVED refund."""
        shop, product, order = setup_completed_order_for_refund()
        refund_payload = create_refund_payload(refund_type="FULL")
        # Customer creates the refund (per PRD §3.6)
        refund = get_success_data(
            api.create_refund(order["id"], refund_payload, customer_headers)
        )
        # Admin tries to process without seller approving (still REQUESTED)
        resp = api.process_refund(order["id"], refund["id"], admin_headers)
        validate_error(resp, ERR_REFUND_NOT_APPROVED, expected_status=409)
