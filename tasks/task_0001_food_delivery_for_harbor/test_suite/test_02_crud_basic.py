"""Basic CRUD tests for Restaurant, Rider, Customer, and MenuItem (PRD §2.4, §3.1–§3.3).

Covers:
- Create → 201 with all declared fields populated
- GET /{id} returns the created entity
- GET list supports limit / offset / total_count / has_more
- Non-existent id → ERR_NOT_FOUND (404)
- Common audit fields (id, created_at, updated_at, version) per PRD §2.4
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    assert_customer,
    assert_menu_item,
    assert_restaurant,
    assert_rider,
    create_active_restaurant,
    create_customer_payload,
    create_listed_menu_item,
    create_menu_item_payload,
    create_restaurant_payload,
    create_rider_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_restaurant_headers,
    setup_restaurant_with_menu,
    validate_error,
    validate_paginated,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# Restaurants
# ──────────────────────────────────────────────────────────

class TestRestaurantCrud:
    def test_register_returns_pending_approval(self, api, admin_headers):
        """PRD §3.1: "A registered restaurant starts in PENDING_APPROVAL."

        Claim: POST /api/restaurants → 201 with status=PENDING_APPROVAL.
        """
        res = api.create_restaurant(create_restaurant_payload(), admin_headers)
        data = validate_success(res, 201)
        assert_restaurant(data)
        assert data["status"] == "PENDING_APPROVAL"
        assert data["pending_settlement_cents"] == 0

    def test_commission_rate_override_defaults_to_null(self, api, admin_headers):
        """PRD §3.1: "The PlatformAdmin may specify a commission_rate_override at
        registration … or leave it unset (the default is a null-meaning-tiered sentinel)."

        Claim: omitting commission_rate_override → null.
        """
        res = api.create_restaurant(create_restaurant_payload(), admin_headers)
        data = validate_success(res, 201)
        assert data["commission_rate_override"] is None

    def test_commission_rate_override_accepted(self, api, admin_headers):
        """PRD §3.1: "a flat decimal rate in [0.05, 0.35] that, when set, supplants the
        tiered commission formula for that restaurant's orders."

        Claim: commission_rate_override=0.12 is stored.
        """
        res = api.create_restaurant(
            create_restaurant_payload(commission_rate_override=0.12), admin_headers
        )
        data = validate_success(res, 201)
        assert data["commission_rate_override"] == pytest.approx(0.12)

    def test_get_restaurant_by_id(self, api, admin_headers):
        """PRD §4: GET /api/restaurants/{id} returns the restaurant record."""
        created = get_success_data(
            api.create_restaurant(create_restaurant_payload(), admin_headers)
        )
        res = api.get_restaurant(created["id"], admin_headers)
        data = validate_success(res, 200)
        assert data["id"] == created["id"]
        assert_restaurant(data)

    def test_get_nonexistent_restaurant_returns_404(self, api, admin_headers):
        """PRD §2.6 priority 3: "Existence of every path-parameter id, validated
        left-to-right (ERR_NOT_FOUND)."

        Claim: GET with non-existent UUID → ERR_NOT_FOUND (404).
        """
        res = api.get_restaurant(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_list_restaurants_pagination(self, api, admin_headers):
        """PRD §2.3: "List endpoints accept two query parameters that control windowing."

        Claim: list endpoint exposes limit/offset/total_count/has_more in meta.
        """
        for _ in range(3):
            api.create_restaurant(create_restaurant_payload(), admin_headers)
        res = api.list_restaurants(admin_headers, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(res)
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] >= 3
        assert isinstance(meta["has_more"], bool)
        assert len(data) <= 2

    def test_list_restaurants_default_limit_is_10(self, api, admin_headers):
        """PRD §2.3: "limit … defaults to 10 when omitted."

        Claim: omitted limit → meta.limit == 10.
        """
        res = api.list_restaurants(admin_headers)
        _, meta = validate_paginated(res)
        assert meta["limit"] == 10


# ──────────────────────────────────────────────────────────
# Riders
# ──────────────────────────────────────────────────────────

class TestRiderCrud:
    def test_register_rider_starts_offline(self, api, admin_headers):
        """PRD §3.3: "New riders start in OFFLINE."

        Claim: POST /api/riders → 201 with status=OFFLINE.
        """
        res = api.create_rider(create_rider_payload(), admin_headers)
        data = validate_success(res, 201)
        assert_rider(data)
        assert data["status"] == "OFFLINE"

    def test_new_rider_defaults(self, api, admin_headers):
        """PRD §3.3: "on_time_rate … is initialized to 1.0 for riders with fewer than 10
        completed deliveries," and "rating is … initialized at 5.0", and "BRONZE as the
        default for a new rider."

        Claim: fresh rider has on_time_rate=1.0, acceptance_rate=1.0, rating=5.0, tier=BRONZE,
        wallet=0.
        """
        res = api.create_rider(create_rider_payload(), admin_headers)
        data = validate_success(res, 201)
        assert data["on_time_rate"] == pytest.approx(1.0)
        assert data["acceptance_rate"] == pytest.approx(1.0)
        assert data["rating"] == pytest.approx(5.0)
        assert data["bonus_tier"] == "BRONZE"
        assert data["wallet_balance_cents"] == 0


# ──────────────────────────────────────────────────────────
# Customers
# ──────────────────────────────────────────────────────────

class TestCustomerCrud:
    def test_register_customer_defaults(self, api, admin_headers):
        """PRD §3.2: "credit_balance_cents, a non-negative integer …" and "trust_score … a
        behavioral aggregate initialized at 1.0."

        Claim: new customer → credit_balance_cents=0, trust_score=1.0.
        """
        res = api.create_customer(create_customer_payload(), admin_headers)
        data = validate_success(res, 201)
        assert_customer(data)
        assert data["credit_balance_cents"] == 0
        assert data["trust_score"] == pytest.approx(1.0)


# ──────────────────────────────────────────────────────────
# Menu items
# ──────────────────────────────────────────────────────────

class TestMenuItemCrud:
    def test_create_menu_item_is_listed_default(self, api):
        """PRD §3.1: "an is_listed flag that defaults to true."

        Claim: omitting is_listed → is_listed=True.
        """
        restaurant = create_active_restaurant()
        headers = make_restaurant_headers(restaurant["id"])
        res = api.create_menu_item(restaurant["id"], create_menu_item_payload(), headers)
        data = validate_success(res, 201)
        assert_menu_item(data)
        assert data["is_listed"] is True
        assert data["restaurant_id"] == restaurant["id"]


# ──────────────────────────────────────────────────────────
# Common audit fields
# ──────────────────────────────────────────────────────────

class TestCommonAuditFields:
    def test_restaurant_has_full_audit_trail(self, api, admin_headers):
        """PRD §2.4: "Top-level resources that carry the standard audit trail — Restaurant,
        Rider, Customer, MenuItem, Order, Return, and WorkOrder — expose four system-managed
        fields: id, created_at, updated_at, version."

        Claim: Restaurant response carries all four fields with correct types.
        """
        data = get_success_data(
            api.create_restaurant(create_restaurant_payload(), admin_headers)
        )
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])
        assert isinstance(data["version"], int) and data["version"] == 1

    def test_assignment_has_no_updated_at_or_version(self, api, admin_headers):
        """PRD §2.4: "Three entities — Assignment, RouteGroup, and Fine — are internal
        operational records; these carry only id (UUID) and created_at. For these three,
        both updated_at and version are absent from the persisted representation and from
        the API response body."

        Claim: an Assignment returned from dispatch carries id + created_at but omits
        updated_at and version.
        """
        from test_helpers import (
            create_available_rider,
            dispatch_order_as_admin,
            place_order,
            restaurant_accept_order,
            setup_customer_restaurant_menu,
        )
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        _rider = create_available_rider()  # ensures dispatch has a candidate
        order = place_order(customer, restaurant, menu_item)
        restaurant_accept_order(order, restaurant)
        asg = dispatch_order_as_admin(order)
        assert is_valid_uuid(asg["id"])
        assert is_iso8601_timestamp(asg["created_at"])
        assert asg.get("updated_at") in (None, )  # absent or explicitly null
        assert asg.get("version") in (None, )
