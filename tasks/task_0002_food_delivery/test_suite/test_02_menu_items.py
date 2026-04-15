"""Tests for menu item CRUD.

Covers: PRD Section 3.2 (Menu Curation), Table 1 (MenuItem entity),
Table 5 (menu item endpoints), Table 6 (errors).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId, TEST_USERS,
    assert_menu_item, create_menu_item_payload,
    create_and_approve_restaurant,
)


_admin = TEST_USERS["admin_headers"]
_restaurant = TEST_USERS["restaurant_headers"]
_customer = TEST_USERS["customer_headers"]


class TestMenuItemCreation:
    """PRD 3.2: Restaurant role adds items to menu."""

    def test_create_menu_item_success(self):
        """Create a menu item with all required fields."""
        rest = create_and_approve_restaurant()
        payload = create_menu_item_payload(base_price_cents=1200)
        resp = api_client.create_menu_item(rest["id"], payload, _restaurant)
        data = validate_success(resp, 201)
        assert_menu_item(data)
        assert data["restaurant_id"] == rest["id"]
        assert data["base_price_cents"] == 1200
        assert data["is_available"] is True

    def test_create_menu_item_with_optional_description(self):
        """Optional description is accepted."""
        rest = create_and_approve_restaurant()
        payload = create_menu_item_payload(description="A delicious test item")
        resp = api_client.create_menu_item(rest["id"], payload, _restaurant)
        data = validate_success(resp, 201)
        assert data.get("description") == "A delicious test item"

    def test_create_menu_item_minimum_price(self):
        """base_price_cents must be >= 100 ($1.00 minimum)."""
        rest = create_and_approve_restaurant()
        payload = create_menu_item_payload(base_price_cents=100)
        resp = api_client.create_menu_item(rest["id"], payload, _restaurant)
        data = validate_success(resp, 201)
        assert data["base_price_cents"] == 100

    def test_create_menu_item_below_minimum_price(self):
        """base_price_cents < 100 should be rejected."""
        rest = create_and_approve_restaurant()
        payload = create_menu_item_payload(base_price_cents=99)
        resp = api_client.create_menu_item(rest["id"], payload, _restaurant)
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST)

    def test_create_menu_item_restaurant_not_found(self):
        """Menu item on non-existent restaurant returns ERR_RESTAURANT_NOT_FOUND."""
        payload = create_menu_item_payload()
        resp = api_client.create_menu_item(NON_EXISTENT_UUID, payload, _restaurant)
        validate_error(resp, ApiErrorId.ERR_RESTAURANT_NOT_FOUND)

    def test_create_menu_item_forbidden_for_customer(self):
        """Only restaurant role can create menu items."""
        rest = create_and_approve_restaurant()
        payload = create_menu_item_payload()
        resp = api_client.create_menu_item(rest["id"], payload, _customer)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestMenuItemRetrieval:
    """PRD 3.2 + Section 4: List and filter menu items."""

    def test_list_menu_items(self):
        """List all menu items for a restaurant."""
        rest = create_and_approve_restaurant()
        get_success_data(api_client.create_menu_item(
            rest["id"], create_menu_item_payload(category="main"), _restaurant
        ))
        get_success_data(api_client.create_menu_item(
            rest["id"], create_menu_item_payload(category="dessert"), _restaurant
        ))
        resp = api_client.list_menu_items(rest["id"], _restaurant)
        assert resp.status_code == 200


class TestMenuItemUpdate:
    """PRD 3.2: Updating menu items with OCC."""

    def test_update_menu_item_price(self):
        """Updating base_price_cents changes the price."""
        rest = create_and_approve_restaurant()
        mi = get_success_data(api_client.create_menu_item(
            rest["id"], create_menu_item_payload(), _restaurant
        ))
        resp = api_client.update_menu_item(
            rest["id"], mi["id"], {"base_price_cents": 2500}, _restaurant
        )
        data = validate_success(resp)
        assert data["base_price_cents"] == 2500

    def test_update_menu_item_availability(self):
        """Toggle is_available to false."""
        rest = create_and_approve_restaurant()
        mi = get_success_data(api_client.create_menu_item(
            rest["id"], create_menu_item_payload(), _restaurant
        ))
        resp = api_client.update_menu_item(
            rest["id"], mi["id"], {"is_available": False}, _restaurant
        )
        data = validate_success(resp)
        assert data["is_available"] is False

    def test_update_menu_item_version_conflict(self):
        """OCC: stale version on menu item update triggers ERR_VERSION_CONFLICT."""
        rest = create_and_approve_restaurant()
        mi = get_success_data(api_client.create_menu_item(
            rest["id"], create_menu_item_payload(), _restaurant
        ))
        stale_version = mi["version"]
        get_success_data(api_client.update_menu_item(
            rest["id"], mi["id"], {"name": "Updated"}, _restaurant
        ))
        resp = api_client.update_menu_item(
            rest["id"], mi["id"], {"name": "Conflict", "version": stale_version}, _restaurant
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_CONFLICT)

    def test_update_menu_item_not_found(self):
        """Updating non-existent menu item returns ERR_MENU_ITEM_NOT_FOUND."""
        rest = create_and_approve_restaurant()
        resp = api_client.update_menu_item(
            rest["id"], NON_EXISTENT_UUID, {"name": "Ghost"}, _restaurant
        )
        validate_error(resp, ApiErrorId.ERR_MENU_ITEM_NOT_FOUND)

    def test_update_menu_item_parent_not_found(self):
        """Hierarchical validation: non-existent restaurant checked first (PRD 2.7)."""
        resp = api_client.update_menu_item(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, {"name": "Ghost"}, _restaurant
        )
        validate_error(resp, ApiErrorId.ERR_RESTAURANT_NOT_FOUND)
