"""Tests for authentication, authorization, and RBAC enforcement.

Covers: PRD Section 2.1 (User and Role-Based Access Control),
Table 7 (RBAC Permission Matrix), Table 6 (ERR_UNAUTHORIZED, ERR_FORBIDDEN).
"""
import pytest
from test_helpers import (
    api_client, validate_error, validate_success, get_success_data,
    ApiErrorId, TEST_USERS, build_user_headers,
    create_restaurant_payload, create_and_approve_restaurant,
    create_rider_payload, create_customer_payload,
    create_promotion_payload, create_surge_zone_payload,
)


_admin = TEST_USERS["admin_headers"]
_restaurant = TEST_USERS["restaurant_headers"]
_customer = TEST_USERS["customer_headers"]
_rider = TEST_USERS["rider_headers"]
_cs = TEST_USERS["cs_headers"]


class TestMissingHeaders:
    """PRD 2.1: Missing or invalid headers produce ERR_UNAUTHORIZED."""

    def test_missing_both_headers(self):
        """No headers at all -> ERR_UNAUTHORIZED."""
        resp = api_client.list_restaurants({})
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_missing_role_header(self):
        """X-User-ID present but no X-User-Role -> ERR_UNAUTHORIZED."""
        resp = api_client.list_restaurants({"X-User-ID": "test-user"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_missing_user_id_header(self):
        """X-User-Role present but no X-User-ID -> ERR_UNAUTHORIZED."""
        resp = api_client.list_restaurants({"X-User-Role": "platform_admin"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_invalid_role(self):
        """Unrecognized role -> ERR_UNAUTHORIZED."""
        headers = build_user_headers("test-user", "invalid_role")
        resp = api_client.list_restaurants(headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)


class TestRBACExclusiveOperations:
    """PRD 2.1 + Table 7: Each role's exclusive operations enforce ERR_FORBIDDEN for wrong roles."""

    # --- Restaurant creation: only platform_admin ---
    @pytest.mark.parametrize("headers_key", ["restaurant_headers", "customer_headers", "rider_headers", "cs_headers"])
    def test_create_restaurant_forbidden(self, headers_key):
        """Only platform_admin can register restaurants."""
        resp = api_client.create_restaurant(create_restaurant_payload(), TEST_USERS[headers_key])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    # --- Rider creation: only platform_admin ---
    @pytest.mark.parametrize("headers_key", ["restaurant_headers", "customer_headers", "rider_headers", "cs_headers"])
    def test_create_rider_forbidden(self, headers_key):
        """Only platform_admin can register riders."""
        resp = api_client.create_rider(create_rider_payload(), TEST_USERS[headers_key])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    # --- Promotion creation: only platform_admin ---
    @pytest.mark.parametrize("headers_key", ["restaurant_headers", "customer_headers", "rider_headers", "cs_headers"])
    def test_create_promotion_forbidden(self, headers_key):
        """Only platform_admin can create promotions."""
        resp = api_client.create_promotion(create_promotion_payload(), TEST_USERS[headers_key])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    # --- Surge zone creation: only platform_admin ---
    def test_create_surge_zone_forbidden_for_non_admin(self):
        """Only platform_admin can create surge zones."""
        resp = api_client.create_surge_zone(create_surge_zone_payload(), _customer)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    # --- Order placement: only customer ---
    def test_place_order_forbidden_for_admin(self):
        """platform_admin cannot place orders."""
        rest = create_and_approve_restaurant()
        resp = api_client.create_order({"restaurant_id": rest["id"]}, _admin)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_place_order_forbidden_for_rider(self):
        """rider cannot place orders."""
        rest = create_and_approve_restaurant()
        resp = api_client.create_order({"restaurant_id": rest["id"]}, _rider)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    # --- Wallet top-up: only customer ---
    def test_wallet_topup_forbidden_for_admin(self):
        """platform_admin cannot top up customer wallet."""
        customer = get_success_data(api_client.create_customer(create_customer_payload(), _customer))
        resp = api_client.top_up_wallet(customer["id"], {"amount_cents": 1000}, _admin)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    # --- Complaint escalation: only customer_service ---
    def test_escalate_complaint_forbidden_for_admin(self):
        """platform_admin cannot escalate complaints (only customer_service can)."""
        # We don't need a real complaint — just check the RBAC at endpoint level
        from test_helpers import NON_EXISTENT_UUID, complete_order_lifecycle, create_complaint_payload
        rest, mi, customer, rider, order, delivery = complete_order_lifecycle()
        complaint = get_success_data(api_client.create_complaint(
            order["id"],
            create_complaint_payload("CUSTOMER", customer["id"]),
            _customer,
        ))
        get_success_data(api_client.assign_complaint(
            order["id"], complaint["id"],
            {"assigned_agent_id": "agent-1"}, _cs,
        ))
        resp = api_client.escalate_complaint(order["id"], complaint["id"], _admin)
        # PRD says only customer_service can escalate
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    # --- Restaurant lifecycle: only platform_admin ---
    def test_approve_restaurant_forbidden_for_restaurant(self):
        """restaurant role cannot approve restaurants."""
        rest = get_success_data(api_client.create_restaurant(create_restaurant_payload(), _admin))
        resp = api_client.approve_restaurant(rest["id"], _restaurant)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    # --- Rating publish/hide: only platform_admin ---
    def test_publish_rating_forbidden_for_customer(self):
        """Only platform_admin can publish ratings."""
        from test_helpers import setup_delivered_order_for_rating, create_rating_payload
        rest, customer, rider, order, delivery = setup_delivered_order_for_rating()
        rating = get_success_data(api_client.create_rating(
            order["id"],
            create_rating_payload("CUSTOMER_TO_RESTAURANT", customer["id"], rest["id"], score=4),
            _customer,
        ))
        resp = api_client.publish_rating(order["id"], rating["id"], _customer)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
