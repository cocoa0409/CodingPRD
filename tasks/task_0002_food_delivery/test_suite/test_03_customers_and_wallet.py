"""Tests for customer registration, wallet management, and loyalty points.

Covers: PRD Section 3.3 (Customer Registration and Wallet Management),
Section 2.9 (Loyalty Points and Customer Wallet), Table 6 (errors).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_customer, create_customer_payload, create_top_up_payload,
    create_active_customer,
)


_admin = TEST_USERS["admin_headers"]
_customer = TEST_USERS["customer_headers"]


class TestCustomerRegistration:
    """PRD 3.3: Customer registers with name and phone."""

    def test_create_customer_success(self):
        """Create customer with required fields. Status=ACTIVE, wallet=0, points=0."""
        payload = create_customer_payload()
        resp = api_client.create_customer(payload, _customer)
        data = validate_success(resp, 201)
        assert_customer(data)
        assert data["status"] == "ACTIVE"
        assert data["wallet_balance_cents"] == 0
        assert data["loyalty_points"] == 0
        assert data["total_orders"] == 0

    def test_create_customer_with_default_address(self):
        """Optional default_address, default_latitude, default_longitude are accepted."""
        payload = create_customer_payload(
            default_address="789 Home St",
            default_latitude=40.73,
            default_longitude=-73.99,
        )
        resp = api_client.create_customer(payload, _customer)
        data = validate_success(resp, 201)
        assert data.get("default_address") == "789 Home St"

    def test_duplicate_phone_rejected(self):
        """Duplicate phone number triggers ERR_DUPLICATE_PHONE (PRD 3.3)."""
        phone = "+15559999999"
        get_success_data(api_client.create_customer(
            create_customer_payload(phone=phone), _customer
        ))
        resp = api_client.create_customer(
            create_customer_payload(phone=phone), _customer
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PHONE)


class TestCustomerRetrieval:
    """PRD Section 4: Get customer details."""

    def test_get_customer_by_id(self):
        """Retrieve a customer by ID."""
        c = create_active_customer(wallet_cents=0)
        resp = api_client.get_customer(c["id"], _customer)
        data = validate_success(resp)
        assert_customer(data)
        assert data["id"] == c["id"]

    def test_get_customer_not_found(self):
        """Non-existent customer returns ERR_CUSTOMER_NOT_FOUND."""
        resp = api_client.get_customer(NON_EXISTENT_UUID, _admin)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)

    def test_get_customer_by_customer_service(self):
        """customer_service role can view customer details."""
        c = create_active_customer(wallet_cents=0)
        resp = api_client.get_customer(c["id"], TEST_USERS["cs_headers"])
        validate_success(resp)


class TestWalletTopUp:
    """PRD 3.3 + 2.9: Wallet top-up creates WalletTransaction."""

    def test_top_up_wallet_success(self):
        """Top-up increases wallet_balance_cents and returns updated customer."""
        c = create_active_customer(wallet_cents=0)
        resp = api_client.top_up_wallet(c["id"], create_top_up_payload(5000), _customer)
        data = validate_success(resp)
        assert data["wallet_balance_cents"] == 5000

    def test_top_up_wallet_cumulative(self):
        """Multiple top-ups accumulate correctly."""
        c = create_active_customer(wallet_cents=0)
        get_success_data(api_client.top_up_wallet(c["id"], create_top_up_payload(3000), _customer))
        resp = api_client.top_up_wallet(c["id"], create_top_up_payload(2000), _customer)
        data = validate_success(resp)
        assert data["wallet_balance_cents"] == 5000

    def test_top_up_customer_not_found(self):
        """Top-up on non-existent customer returns ERR_CUSTOMER_NOT_FOUND."""
        resp = api_client.top_up_wallet(NON_EXISTENT_UUID, create_top_up_payload(1000), _customer)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_NOT_FOUND)

    def test_top_up_forbidden_for_rider(self):
        """Only customer role can top up wallet."""
        c = create_active_customer(wallet_cents=0)
        resp = api_client.top_up_wallet(c["id"], create_top_up_payload(1000), TEST_USERS["rider_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
