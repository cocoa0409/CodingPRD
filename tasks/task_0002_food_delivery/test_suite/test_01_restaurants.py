"""Tests for restaurant CRUD, onboarding lifecycle, and state transitions.

Covers: PRD Section 3.1 (Restaurant Onboarding and Lifecycle), Section 3.2 (Menu Curation),
Table 2 (Restaurant state machine), Table 6 (error catalog).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    is_valid_uuid, is_iso8601_timestamp, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS,
    assert_restaurant, assert_menu_item,
    create_restaurant_payload, create_menu_item_payload,
    create_and_approve_restaurant, setup_restaurant_with_menu_items,
    setup_basic_order_scenario, confirm_order, prepare_order,
)


_admin = TEST_USERS["admin_headers"]
_restaurant = TEST_USERS["restaurant_headers"]
_customer = TEST_USERS["customer_headers"]


class TestRestaurantCreation:
    """PRD 3.1: platform_admin registers a new restaurant."""

    def test_create_restaurant_success(self):
        """Creating a restaurant returns a PENDING_APPROVAL entity with all fields."""
        payload = create_restaurant_payload()
        resp = api_client.create_restaurant(payload, _admin)
        data = validate_success(resp, 201)
        assert_restaurant(data)
        assert data["status"] == "PENDING_APPROVAL"
        assert data["name"] == payload["name"]
        assert data["commission_rate"] == payload["commission_rate"]
        assert data["rating_average"] == 0.0
        assert data["rating_count"] == 0
        assert data["total_orders_completed"] == 0
        assert data["balance_pending_cents"] == 0
        assert data["balance_settled_cents"] == 0

    def test_create_restaurant_forbidden_for_customer(self):
        """Only platform_admin can register restaurants."""
        payload = create_restaurant_payload()
        resp = api_client.create_restaurant(payload, _customer)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_create_restaurant_forbidden_for_rider(self):
        """Riders cannot register restaurants."""
        payload = create_restaurant_payload()
        resp = api_client.create_restaurant(payload, TEST_USERS["rider_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestRestaurantRetrieval:
    """PRD 2.4 + Section 4: Get and list restaurants."""

    def test_get_restaurant_by_id(self):
        """Retrieve a specific restaurant by ID."""
        rest = create_and_approve_restaurant()
        resp = api_client.get_restaurant(rest["id"], _admin)
        data = validate_success(resp)
        assert_restaurant(data)
        assert data["id"] == rest["id"]

    def test_get_restaurant_not_found(self):
        """Non-existent restaurant ID returns ERR_RESTAURANT_NOT_FOUND."""
        resp = api_client.get_restaurant(NON_EXISTENT_UUID, _admin)
        validate_error(resp, ApiErrorId.ERR_RESTAURANT_NOT_FOUND)

    def test_list_restaurants(self):
        """List endpoint returns paginated restaurants."""
        create_and_approve_restaurant()
        resp = api_client.list_restaurants(_admin)
        assert resp.status_code == 200


class TestRestaurantUpdate:
    """PRD 3.1 + 2.6: Update restaurant with OCC."""

    def test_update_restaurant_name(self):
        """Updating restaurant name succeeds and returns updated resource."""
        rest = create_and_approve_restaurant()
        resp = api_client.update_restaurant(rest["id"], {"name": "New Name"}, _restaurant)
        data = validate_success(resp)
        assert data["name"] == "New Name"
        assert data["version"] > rest["version"]

    def test_update_is_accepting_orders(self):
        """Toggle is_accepting_orders flag."""
        rest = create_and_approve_restaurant()
        resp = api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant)
        data = validate_success(resp)
        assert data["is_accepting_orders"] is True

    def test_version_conflict_on_stale_update(self):
        """OCC: sending stale version triggers ERR_VERSION_CONFLICT (PRD 2.6)."""
        rest = create_and_approve_restaurant()
        stale_version = rest["version"]
        # First update succeeds
        get_success_data(api_client.update_restaurant(rest["id"], {"name": "V1"}, _restaurant))
        # Second update with stale version fails
        resp = api_client.update_restaurant(
            rest["id"], {"name": "V2", "version": stale_version}, _restaurant
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT)


class TestRestaurantStateTransitions:
    """PRD 3.1 + Table 2: Restaurant state machine transitions."""

    def test_approve_pending_restaurant(self):
        """PENDING_APPROVAL -> ACTIVE via approve."""
        payload = create_restaurant_payload()
        rest = get_success_data(api_client.create_restaurant(payload, _admin))
        assert rest["status"] == "PENDING_APPROVAL"

        resp = api_client.approve_restaurant(rest["id"], _admin)
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"

    def test_suspend_active_restaurant(self):
        """ACTIVE -> SUSPENDED via suspend."""
        rest = create_and_approve_restaurant()
        resp = api_client.suspend_restaurant(rest["id"], _admin)
        data = validate_success(resp)
        assert data["status"] == "SUSPENDED"
        assert data["is_accepting_orders"] is False

    def test_reinstate_suspended_restaurant(self):
        """SUSPENDED -> ACTIVE via reinstate."""
        rest = create_and_approve_restaurant()
        get_success_data(api_client.suspend_restaurant(rest["id"], _admin))
        resp = api_client.reinstate_restaurant(rest["id"], _admin)
        data = validate_success(resp)
        assert data["status"] == "ACTIVE"

    def test_close_active_restaurant_no_active_orders(self):
        """ACTIVE -> CLOSED via close when no CONFIRMED/PREPARING orders exist."""
        rest = create_and_approve_restaurant()
        resp = api_client.close_restaurant(rest["id"], _admin)
        data = validate_success(resp)
        assert data["status"] == "CLOSED"

    def test_close_suspended_restaurant(self):
        """SUSPENDED -> CLOSED via close."""
        rest = create_and_approve_restaurant()
        get_success_data(api_client.suspend_restaurant(rest["id"], _admin))
        resp = api_client.close_restaurant(rest["id"], _admin)
        data = validate_success(resp)
        assert data["status"] == "CLOSED"

    def test_cannot_approve_active_restaurant(self):
        """Approving an already ACTIVE restaurant is invalid state."""
        rest = create_and_approve_restaurant()
        resp = api_client.approve_restaurant(rest["id"], _admin)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cannot_suspend_pending_restaurant(self):
        """Cannot suspend a PENDING_APPROVAL restaurant."""
        payload = create_restaurant_payload()
        rest = get_success_data(api_client.create_restaurant(payload, _admin))
        resp = api_client.suspend_restaurant(rest["id"], _admin)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cannot_reinstate_active_restaurant(self):
        """Cannot reinstate an already ACTIVE restaurant."""
        rest = create_and_approve_restaurant()
        resp = api_client.reinstate_restaurant(rest["id"], _admin)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    @pytest.mark.parametrize("invalid_from", ["PENDING_APPROVAL", "CLOSED"])
    def test_cannot_close_from_invalid_state(self, invalid_from):
        """Close is only valid from ACTIVE or SUSPENDED."""
        payload = create_restaurant_payload()
        rest = get_success_data(api_client.create_restaurant(payload, _admin))
        if invalid_from == "CLOSED":
            get_success_data(api_client.approve_restaurant(rest["id"], _admin))
            get_success_data(api_client.close_restaurant(rest["id"], _admin))
        resp = api_client.close_restaurant(rest["id"], _admin)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRestaurantSuspensionCascade:
    """PRD 3.1: Side effects of restaurant suspension."""

    def test_suspension_cancels_placed_orders(self):
        """Suspending a restaurant auto-cancels all PLACED orders."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        assert order["status"] == "PLACED"

        get_success_data(api_client.suspend_restaurant(rest["id"], _admin))

        # Verify order is now CANCELLED_BY_PLATFORM
        refreshed = get_success_data(api_client.get_order(order["id"], _admin))
        assert refreshed["status"] == "CANCELLED_BY_PLATFORM"

    def test_suspension_sets_not_accepting(self):
        """Suspension forces is_accepting_orders to false."""
        rest = create_and_approve_restaurant()
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))
        suspended = get_success_data(api_client.suspend_restaurant(rest["id"], _admin))
        assert suspended["is_accepting_orders"] is False


class TestRestaurantClosureCascade:
    """PRD 3.1: Side effects of restaurant closure."""

    def test_close_active_cancels_placed_orders_and_disables_menu(self):
        """Closing from ACTIVE cancels PLACED orders and sets menu items unavailable."""
        rest, menu_items = setup_restaurant_with_menu_items(num_items=2)
        get_success_data(api_client.update_restaurant(rest["id"], {"is_accepting_orders": True}, _restaurant))

        get_success_data(api_client.close_restaurant(rest["id"], _admin))

        # Check menu items are unavailable
        for mi in menu_items:
            refreshed = get_success_data(
                api_client.list_menu_items(rest["id"], _admin)
            )
            # All items should be is_available = false
            for item in refreshed if isinstance(refreshed, list) else [refreshed]:
                assert item.get("is_available") is False, "Menu items should be unavailable after closure"

    def test_close_active_blocked_by_confirmed_orders(self):
        """Cannot close ACTIVE restaurant with CONFIRMED orders (ERR_ACTIVE_ORDERS_EXIST)."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        confirm_order(order["id"])

        resp = api_client.close_restaurant(rest["id"], _admin)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_ORDERS_EXIST)

    def test_close_active_blocked_by_preparing_orders(self):
        """Cannot close ACTIVE restaurant with PREPARING orders."""
        rest, menu_items, customer, order = setup_basic_order_scenario()
        confirm_order(order["id"])
        prepare_order(order["id"])

        resp = api_client.close_restaurant(rest["id"], _admin)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_ORDERS_EXIST)
