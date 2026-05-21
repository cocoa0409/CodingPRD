"""Auth and RBAC tests (PRD §2.1, §2.6).

Covers:
- Missing / malformed auth headers → ERR_AUTH_REQUIRED
- Role not permitted for endpoint → ERR_FORBIDDEN
- Identity mismatch on entity-backed roles → ERR_FORBIDDEN
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_active_restaurant,
    create_available_rider,
    create_customer,
    create_listed_menu_item,
    create_rider_payload,
    create_restaurant_payload,
    make_customer_headers,
    make_restaurant_headers,
    make_rider_headers,
    place_order,
    setup_customer_restaurant_menu,
    validate_error,
)


class TestAuthHeaders:
    """PRD §2.1: Every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers(self, api):
        """PRD §2.1: "A request missing either header, or carrying an X-User-Role outside
        this set, is rejected with ERR_AUTH_REQUIRED."

        Claim: empty headers → ERR_AUTH_REQUIRED.
        """
        res = api.create_restaurant(create_restaurant_payload(), headers={})
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_id_header(self, api):
        """PRD §2.1: "A request missing either header, or carrying an X-User-Role outside
        this set, is rejected with ERR_AUTH_REQUIRED."

        Claim: only X-User-Role present → ERR_AUTH_REQUIRED.
        """
        res = api.create_restaurant(
            create_restaurant_payload(),
            headers={"X-User-Role": "PlatformAdmin", "Content-Type": "application/json"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_role_header(self, api):
        """PRD §2.1: "A request missing either header, or carrying an X-User-Role outside
        this set, is rejected with ERR_AUTH_REQUIRED."

        Claim: only X-User-ID present → ERR_AUTH_REQUIRED.
        """
        res = api.create_restaurant(
            create_restaurant_payload(),
            headers={"X-User-ID": "some-id", "Content-Type": "application/json"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    @pytest.mark.parametrize("bad_role", ["Admin", "admin", "PLATFORMADMIN", "Owner", ""])
    def test_unknown_role_rejected(self, api, bad_role):
        """PRD §2.1: "A request missing either header, or carrying an X-User-Role outside
        this set, is rejected with ERR_AUTH_REQUIRED."

        Claim: unknown role string → ERR_AUTH_REQUIRED.
        """
        res = api.create_restaurant(
            create_restaurant_payload(),
            headers=build_user_headers("test-id", bad_role),
        )
        validate_error(res, "ERR_AUTH_REQUIRED")


class TestRbacMatrix:
    """PRD §2.1: "A request whose role is recognized but not permitted for the called
    endpoint is rejected with ERR_FORBIDDEN." (See endpoint matrix in PRD §4.)"""

    def test_customer_cannot_register_restaurant(self, api):
        """PRD §4: POST /api/restaurants is authorized only for PlatformAdmin.

        Claim: Customer role attempting restaurant registration → ERR_FORBIDDEN.
        """
        headers = build_user_headers("some-customer-id", "Customer")
        res = api.create_restaurant(create_restaurant_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_rider_cannot_approve_restaurant(self, api, admin_headers):
        """PRD §4: POST /api/restaurants/{id}/approve is authorized only for PlatformAdmin.

        Claim: Rider role attempting restaurant approval → ERR_FORBIDDEN.
        """
        restaurant = create_active_restaurant()
        headers = build_user_headers("some-rider-id", "Rider")
        # use a new restaurant in PENDING_APPROVAL to exercise approve, but RBAC is priority 2
        # (before state-machine), so the forbidden error wins regardless of state.
        res = api.approve_restaurant(restaurant["id"], headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_restaurant_cannot_approve_return(self, api):
        """PRD §4: POST /api/returns/{id}/approve is authorized only for CustomerService.

        Claim: Restaurant role attempting return approval → ERR_FORBIDDEN.
        """
        restaurant = create_active_restaurant()
        headers = make_restaurant_headers(restaurant["id"])
        res = api.approve_return(NON_EXISTENT_UUID, {"approved_refund_cents": 1}, headers)
        validate_error(res, "ERR_FORBIDDEN")

    def test_customer_cannot_place_order_as_another_customer(self, api):
        """PRD §2.1: "ownership checks on any resource that references a Customer compare
        the resource's foreign-key field (such as Order.customer_id or WorkOrder.opened_by_id
        where the opener was a customer) to X-User-ID."

        Claim: Customer placing an order whose customer_id is someone else → ERR_FORBIDDEN.
        """
        restaurant, menu_item, customer_a = setup_customer_restaurant_menu()
        customer_b = create_customer()
        # Build a payload that claims customer_id == customer_a, but carry headers for customer_b.
        from test_helpers import build_order_item, create_order_payload
        payload = create_order_payload(
            customer_id=customer_a["id"],
            restaurant_id=restaurant["id"],
            items=[build_order_item(menu_item["id"], unit_price_cents=menu_item["price_cents"])],
        )
        headers = make_customer_headers(customer_b["id"])
        res = api.create_order(payload, headers)
        validate_error(res, "ERR_FORBIDDEN")


class TestIdentityMismatch:
    """PRD §2.1: "Identity mismatch — a caller whose role is correct but whose X-User-ID
    does not match the resource the operation targets … is rejected with ERR_FORBIDDEN."
    """

    def test_customer_reading_another_customer_profile(self, api):
        """PRD §2.1: "for instance, a Customer reading another customer's profile … is
        rejected with ERR_FORBIDDEN."

        Claim: Customer GETting another customer's record → ERR_FORBIDDEN.
        """
        alice = create_customer()
        bob = create_customer()
        headers_alice = make_customer_headers(alice["id"])
        res = api.get_customer(bob["id"], headers_alice)
        validate_error(res, "ERR_FORBIDDEN")

    def test_rider_go_online_on_someone_else_record(self, api):
        """PRD §2.1: "or a Rider calling the go-online capability on someone else's rider
        record — is rejected with ERR_FORBIDDEN."

        Claim: Rider go-online on another rider's id → ERR_FORBIDDEN.
        """
        rider_a = create_available_rider()
        # A different rider attempts to drive rider_a online.
        from test_helpers import api_client as _api, TEST_USERS as _TU
        from test_helpers.factories import create_rider_payload as _rp
        from test_helpers import get_success_data as _gsd
        rider_b = _gsd(_api.create_rider(_rp(), _TU["admin_headers"]))
        headers_b = make_rider_headers(rider_b["id"])
        res = api.rider_go_online(rider_a["id"], headers_b)
        validate_error(res, "ERR_FORBIDDEN")

    def test_restaurant_accepting_another_restaurants_order(self, api):
        """PRD §3.5: "Acceptance is only legal while the restaurant's own status is ACTIVE
        and the order is still in PLACED; the restaurant identity is enforced by the
        X-User-ID match against Order.restaurant_id."

        Claim: Restaurant B calling /accept on Restaurant A's order → ERR_FORBIDDEN.
        """
        restaurant_a, menu_item, customer = setup_customer_restaurant_menu()
        restaurant_b = create_active_restaurant()
        order = place_order(customer, restaurant_a, menu_item)
        headers_b = make_restaurant_headers(restaurant_b["id"])
        res = api.accept_order(order["id"], headers_b)
        validate_error(res, "ERR_FORBIDDEN")
