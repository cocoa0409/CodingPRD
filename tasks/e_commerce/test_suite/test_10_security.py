"""
Test 10 -- Security: SQL injection, auth headers, RBAC, ownership, mass assignment.

Covers:
  - SQL injection payloads across entity creation endpoints
  - Missing auth headers
  - Role-based access control enforcement
  - Cross-user ownership checks
  - Mass assignment / extra-field rejection
  - Cross-entity scoping (cross-shop orders)
"""

import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    build_user_headers,
    create_shop_payload, create_product_payload, create_order_payload,
    create_promotion_payload,
    create_and_approve_shop, create_and_list_product,
    setup_basic_order_scenario, place_and_pay_order,
    place_pay_and_deliver_order,
    ERR_AUTH_HEADER_MISSING, ERR_FORBIDDEN,
    ERR_NOT_SHOP_OWNER, ERR_NOT_ORDER_OWNER,
    ERR_INVALID_REQUEST, ERR_CROSS_SHOP_ORDER,
    TEST_USERS,
)

_customer = TEST_USERS["customer_headers"]
_seller = TEST_USERS["seller_headers"]
_admin = TEST_USERS["admin_headers"]
_seller2 = TEST_USERS["seller2_headers"]
_customer2 = TEST_USERS["customer2_headers"]

# ============================================================================
# SQL injection
# ============================================================================

SQL_PAYLOADS = [
    "'; DROP TABLE shops; --",
    "' OR '1'='1",
    "1; SELECT * FROM users --",
    "' UNION SELECT null,null,null --",
    "Robert'); DROP TABLE students;--",
]

SQL_ERROR_FRAGMENTS = [
    "syntax error",
    "SQL",
    "mysql",
    "postgresql",
    "sqlite",
    "ORA-",
    "SQLSTATE",
    "Traceback",
    "Internal Server Error",
]


class TestSQLInjection:
    """SQL injection payloads must not cause 500s or leak DB errors."""

    @pytest.mark.parametrize("payload_str", SQL_PAYLOADS)
    def test_shop_name_injection(self, payload_str):
        """SQL injection in shop_name field."""
        payload = create_shop_payload(shop_name=payload_str)
        resp = api_client.create_shop(payload, _seller)
        assert resp.status_code != 500, (
            f"Server returned 500 for SQL injection payload: {payload_str}"
        )
        body = resp.text.lower() if hasattr(resp, "text") else str(resp.content).lower()
        for frag in SQL_ERROR_FRAGMENTS:
            assert frag.lower() not in body, (
                f"SQL error fragment '{frag}' leaked in response"
            )

    @pytest.mark.parametrize("payload_str", SQL_PAYLOADS)
    def test_product_name_injection(self, payload_str):
        """SQL injection in product_name field."""
        shop = create_and_approve_shop()
        payload = create_product_payload(product_name=payload_str)
        resp = api_client.create_product(shop["id"], payload, _seller)
        assert resp.status_code != 500, (
            f"Server returned 500 for SQL injection payload: {payload_str}"
        )

    @pytest.mark.parametrize("payload_str", SQL_PAYLOADS)
    def test_promotion_name_injection(self, payload_str):
        """SQL injection in promo_name field."""
        shop = create_and_approve_shop()
        payload = create_promotion_payload(promo_name=payload_str)
        resp = api_client.create_promotion(shop["id"], payload, _seller)
        assert resp.status_code != 500

    @pytest.mark.parametrize("payload_str", SQL_PAYLOADS)
    def test_order_address_injection(self, payload_str):
        """SQL injection in shipping_address field."""
        shop, product = setup_basic_order_scenario()
        payload = create_order_payload(
            shop["id"],
            [{"product_id": product["id"], "quantity": 1}],
            shipping_address=payload_str,
        )
        resp = api_client.create_order(payload, _customer)
        assert resp.status_code != 500


# ============================================================================
# Auth headers
# ============================================================================


class TestAuthHeaders:
    """Missing auth headers must be rejected consistently."""

    def test_missing_user_id_header(self):
        """Request without X-User-ID returns ERR_AUTH_HEADER_MISSING."""
        headers = {"X-User-Role": "Seller"}
        resp = api_client.list_shops(headers)
        validate_error(resp, ERR_AUTH_HEADER_MISSING)

    def test_missing_user_role_header(self):
        """Request without X-User-Role returns ERR_AUTH_HEADER_MISSING."""
        headers = {"X-User-ID": "some-id"}
        resp = api_client.list_shops(headers)
        validate_error(resp, ERR_AUTH_HEADER_MISSING)

    def test_both_headers_missing(self):
        """Request without both auth headers returns ERR_AUTH_HEADER_MISSING."""
        resp = api_client.list_shops({})
        validate_error(resp, ERR_AUTH_HEADER_MISSING)

    def test_missing_headers_on_create_shop(self):
        """Create shop without auth headers fails."""
        payload = create_shop_payload()
        resp = api_client.create_shop(payload, {})
        validate_error(resp, ERR_AUTH_HEADER_MISSING)

    def test_missing_headers_on_create_order(self):
        """Create order without auth headers fails."""
        payload = create_order_payload("fake-shop", [])
        resp = api_client.create_order(payload, {})
        validate_error(resp, ERR_AUTH_HEADER_MISSING)


# ============================================================================
# RBAC enforcement
# ============================================================================


class TestRBAC:
    """Role-based access control is enforced on restricted endpoints."""

    def test_customer_cannot_create_shop(self):
        """Customers are forbidden from creating shops."""
        payload = create_shop_payload()
        resp = api_client.create_shop(payload, _customer)
        validate_error(resp, ERR_FORBIDDEN)

    def test_customer_cannot_approve_shop(self):
        """Customers cannot approve shops (admin-only)."""
        payload = create_shop_payload()
        shop = get_success_data(api_client.create_shop(payload, _seller))
        resp = api_client.approve_shop(shop["id"], _customer)
        validate_error(resp, ERR_FORBIDDEN)

    def test_seller_cannot_confirm_payment(self):
        """Sellers cannot confirm payment (admin-only)."""
        shop, product = setup_basic_order_scenario()
        items = [{"product_id": product["id"], "quantity": 1}]
        order_payload = create_order_payload(shop["id"], items)
        order = get_success_data(api_client.create_order(order_payload, _customer))
        pay_payload = {"payment_method": "CREDIT_CARD", "transaction_ref": "txn-test"}
        get_success_data(api_client.pay_order(order["id"], pay_payload, _customer))
        resp = api_client.confirm_payment(order["id"], _seller)
        validate_error(resp, ERR_FORBIDDEN)

    def test_seller_cannot_process_refund(self):
        """Sellers cannot process refunds (admin-only)."""
        shop, product = setup_basic_order_scenario()
        order = place_pay_and_deliver_order(
            shop["id"],
            [{"product_id": product["id"], "quantity": 2}],
        )
        from test_helpers import create_refund_payload
        refund_payload = create_refund_payload(refund_type="FULL")
        refund = get_success_data(
            api_client.create_refund(order["id"], refund_payload, _customer)
        )
        get_success_data(
            api_client.approve_refund(order["id"], refund["id"], _seller)
        )
        resp = api_client.process_refund(order["id"], refund["id"], _seller)
        validate_error(resp, ERR_FORBIDDEN)

    def test_admin_can_create_shop(self):
        """PlatformAdmin has hierarchical override -- can create shops."""
        payload = create_shop_payload()
        resp = api_client.create_shop(payload, _admin)
        shop = get_success_data(resp)
        assert shop["status"] == "PENDING_REVIEW"

    def test_admin_can_approve_shop(self):
        """PlatformAdmin can approve shops."""
        payload = create_shop_payload()
        shop = get_success_data(api_client.create_shop(payload, _seller))
        approved = get_success_data(api_client.approve_shop(shop["id"], _admin))
        assert approved["status"] == "ACTIVE"

    def test_customer_cannot_list_product(self):
        """Customers cannot transition products to LISTED (seller action)."""
        shop = create_and_approve_shop()
        payload = create_product_payload()
        product = get_success_data(
            api_client.create_product(shop["id"], payload, _seller)
        )
        resp = api_client.list_product(shop["id"], product["id"], _customer)
        validate_error(resp, ERR_FORBIDDEN)


# ============================================================================
# Ownership checks
# ============================================================================


class TestOwnership:
    """Cross-user ownership violations are rejected."""

    def test_seller_b_cannot_manage_seller_a_shop(self):
        """Seller 2 cannot update Seller 1's shop."""
        shop = create_and_approve_shop()
        resp = api_client.update_shop(
            shop["id"],
            {"shop_name": "Hijacked", "version": shop["version"]},
            _seller2,
        )
        validate_error(resp, ERR_NOT_SHOP_OWNER)

    def test_seller_b_cannot_create_product_in_seller_a_shop(self):
        """Seller 2 cannot add products to Seller 1's shop."""
        shop = create_and_approve_shop()
        payload = create_product_payload()
        resp = api_client.create_product(shop["id"], payload, _seller2)
        validate_error(resp, ERR_NOT_SHOP_OWNER)

    def test_customer_b_cannot_cancel_customer_a_order(self):
        """Customer 2 cannot cancel Customer 1's order."""
        shop, product = setup_basic_order_scenario()
        order_payload = create_order_payload(
            shop["id"],
            [{"product_id": product["id"], "quantity": 1}],
        )
        order = get_success_data(api_client.create_order(order_payload, _customer))
        resp = api_client.cancel_order(order["id"], _customer2)
        validate_error(resp, ERR_NOT_ORDER_OWNER)

    def test_seller_b_cannot_start_processing_seller_a_order(self):
        """Seller 2 cannot process orders belonging to Seller 1's shop."""
        shop, product = setup_basic_order_scenario()
        order = place_and_pay_order(
            shop["id"],
            [{"product_id": product["id"], "quantity": 1}],
        )
        resp = api_client.start_processing(order["id"], _seller2)
        validate_error(resp, ERR_NOT_SHOP_OWNER)


# ============================================================================
# Mass assignment
# ============================================================================


class TestMassAssignment:
    """Extra / privileged fields in creation payloads are silently ignored."""

    def test_extra_fields_ignored_on_shop_create(self):
        """Passing is_admin, status, id in shop creation is ignored."""
        payload = create_shop_payload(
            is_admin=True,
            status="ACTIVE",
            id="injected-uuid",
            monthly_gmv=999999,
            settlement_balance=999999,
        )
        shop = get_success_data(api_client.create_shop(payload, _seller))
        assert shop["status"] == "PENDING_REVIEW"
        assert shop["id"] != "injected-uuid"
        assert shop["monthly_gmv"] == 0 or shop["monthly_gmv"] == pytest.approx(0)
        assert shop["settlement_balance"] == 0 or shop["settlement_balance"] == pytest.approx(0)

    def test_extra_fields_ignored_on_product_create(self):
        """Passing reserved_count, available_count in product creation is ignored."""
        shop = create_and_approve_shop()
        payload = create_product_payload(
            reserved_count=50,
            available_count=9999,
            status="LISTED",
            id="injected-product-id",
        )
        product = get_success_data(
            api_client.create_product(shop["id"], payload, _seller)
        )
        assert product["status"] == "DRAFT"
        assert product["reserved_count"] == 0
        assert product["id"] != "injected-product-id"

    def test_extra_fields_ignored_on_order_create(self):
        """Passing order_status, commission_amount in order creation is ignored."""
        shop, product = setup_basic_order_scenario()
        payload = create_order_payload(
            shop["id"],
            [{"product_id": product["id"], "quantity": 1}],
            order_status="COMPLETED",
            commission_amount=999.99,
            total_amount=0.01,
        )
        order = get_success_data(api_client.create_order(payload, _customer))
        assert order["order_status"] == "CREATED"


# ============================================================================
# Cross-entity scoping
# ============================================================================


class TestCrossEntityScoping:
    """Products from one shop cannot be used in another shop's orders."""

    def test_cross_shop_order_rejected(self):
        """Ordering a product from shop A in an order targeting shop B fails."""
        shop_a = create_and_approve_shop(shop_name="Shop A")
        product_a = create_and_list_product(
            shop_a["id"], product_name="Product A", inventory_count=10
        )

        shop_b = create_and_approve_shop(shop_name="Shop B")

        payload = create_order_payload(
            shop_b["id"],
            [{"product_id": product_a["id"], "quantity": 1}],
        )
        resp = api_client.create_order(payload, _customer)
        validate_error(resp, ERR_CROSS_SHOP_ORDER)

    def test_same_shop_order_succeeds(self):
        """Ordering products from the correct shop succeeds."""
        shop = create_and_approve_shop()
        product = create_and_list_product(
            shop["id"], inventory_count=10
        )
        payload = create_order_payload(
            shop["id"],
            [{"product_id": product["id"], "quantity": 1}],
        )
        order = get_success_data(api_client.create_order(payload, _customer))
        assert order["shop_id"] == shop["id"]
