"""Configuration, CRUD basics, pagination, RBAC, and authentication.

Translates queue-B (corner) instances from sections entities / validations / rbac.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_event_order_payload, create_menu_item_payload, create_order_line_payload,
    create_ingredient_payload,
)
from test_helpers import fixtures as fx


def test_create_event_order_returns_201_with_defaults(api, sales_manager_headers):
    """PRD §3.2: "A `SalesManager` opens an event by creating an `EventOrder`, which
    begins life in `DRAFT` status with `version` 1."
    PRD §3.6: "the order's `actual_labor_total_cents`, a running sum that starts at 0"

    Design: Corner/entities/create_event_order_returns_201_with_defaults
    """
    data = validate_success(api.create_event_order(create_event_order_payload(), sales_manager_headers), 201)
    assert data["status"] == "DRAFT", f"new order must be DRAFT, got {data['status']}"
    assert data["version"] == 1, f"new order version must be 1, got {data['version']}"
    assert data["actual_labor_total_cents"] == 0


def test_create_event_order_missing_guest_count_returns_validation(api, sales_manager_headers):
    """PRD §2.6: "(3) request-shape and value checks — a well-formed body with required
    fields of the correct type (`ERR_VALIDATION`)"

    Design: Corner/entities/create_event_order_missing_required_guest_count_returns_validation
    """
    payload = create_event_order_payload()
    payload.pop("guest_count")
    validate_error(api.create_event_order(payload, sales_manager_headers), ApiErrorId.ERR_VALIDATION)


def test_create_menu_item_invalid_enum_category_returns_400(api, kitchen_manager_headers):
    """PRD §3.1: "An enum field bearing a value outside its declared set (for `unit`
    here, and likewise `category`, `asset_type`, and `staff_role` elsewhere) is rejected
    with `ERR_INVALID_ENUM`."

    Design: Corner/entities/create_menu_item_invalid_enum_category_returns_400
    """
    payload = create_menu_item_payload(category="APPETIZER")
    validate_error(api.create_menu_item(payload, kitchen_manager_headers), ApiErrorId.ERR_INVALID_ENUM)


def test_create_order_line_nonpositive_portions_returns_422(api, sales_manager_headers):
    """PRD §2.6: "The positive-value guard at priority 3 applies to `qty`, `portions`,
    `portions_per_guest`, `unit_cost_cents`, `total_units`, `rental_price_cents`,
    `hourly_rate_cents`, and `concurrent_capacity`; any of these supplied as zero or
    negative on the relevant create is rejected with `ERR_QUANTITY_NOT_POSITIVE`."

    Design: Corner/entities/create_order_line_nonpositive_portions_returns_422
    """
    menu_item = fx.create_menu_item(api)
    order = fx.create_event_order(api, guest_count=20, service_charge_pct=0.10, gratuity_pct=0.10)
    payload = create_order_line_payload(order["id"], menu_item["id"], portions_per_guest=0)
    validate_error(api.create_order_line(payload, sales_manager_headers), ApiErrorId.ERR_QUANTITY_NOT_POSITIVE)


def test_create_event_order_invalid_time_window_returns_422(api, sales_manager_headers):
    """PRD §2.6: "The strictly-ordered-window guard applies wherever an interval is
    supplied — `event_end` must be strictly after `event_start`, `scheduled_end`
    strictly after `scheduled_start`, `return_time` strictly after `out_time`,
    `shift_end` strictly after `shift_start`, and, at check-out, `actual_end` strictly
    after `actual_start` — and each violation surfaces as `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/entities/create_event_order_invalid_time_window_returns_422
    """
    payload = create_event_order_payload(
        event_start="2026-06-01T17:00:00Z", event_end="2026-06-01T09:00:00Z",
        service_charge_pct=0.10, gratuity_pct=0.10,
    )
    validate_error(api.create_event_order(payload, sales_manager_headers), ApiErrorId.ERR_INVALID_TIME_WINDOW)


def test_create_event_order_nonpositive_guest_count_returns_422(api, sales_manager_headers):
    """PRD §3.2: "the booked `guest_count` (the estimated headcount, which must be
    positive — a non-positive value yields `ERR_INVALID_GUEST_COUNT`)"

    Design: Corner/validations/create_event_order_nonpositive_guest_count_returns_422
    """
    payload = create_event_order_payload(guest_count=0, service_charge_pct=0.10, gratuity_pct=0.10)
    validate_error(api.create_event_order(payload, sales_manager_headers), ApiErrorId.ERR_INVALID_GUEST_COUNT)


def test_get_event_order_nonexistent_returns_not_found(api, sales_manager_headers):
    """PRD §2.9: "A request that names a missing event order fails with
    `ERR_EVENT_ORDER_NOT_FOUND`"

    Design: Corner/entities/get_event_order_nonexistent_returns_not_found
    """
    validate_error(api.get_event_order(NON_EXISTENT_UUID, sales_manager_headers),
                   ApiErrorId.ERR_EVENT_ORDER_NOT_FOUND)


def test_list_event_orders_pagination_envelope(api, sales_manager_headers):
    """PRD §2.3: "Each list response echoes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object, where `total_count` reflects the full size of
    the filtered result set before the limit/offset window is applied and `has_more`
    indicates whether further items remain beyond the returned page."

    Design: Corner/entities/list_event_orders_pagination_envelope
    """
    fx.create_event_order(api, guest_count=10, service_charge_pct=0.10, gratuity_pct=0.10, venue_address="A")
    fx.create_event_order(api, guest_count=12, service_charge_pct=0.10, gratuity_pct=0.10, venue_address="B")
    data, meta = validate_paginated(api.list_event_orders(sales_manager_headers, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true with 2 items and limit 1"
    assert len(data) == 1, f"limit 1 must return exactly 1 item, got {len(data)}"


def test_list_event_orders_invalid_pagination_returns_400(api, sales_manager_headers):
    """PRD §2.3: "A `limit` outside the range of 1 through 100, or a negative `offset`,
    is rejected with `ERR_INVALID_PAGINATION`."

    Design: Corner/entities/list_event_orders_invalid_pagination_returns_400
    """
    validate_error(api.list_event_orders(sales_manager_headers, params={"limit": 500, "offset": 0}),
                   ApiErrorId.ERR_INVALID_PAGINATION)


def test_kitchenmanager_create_event_order_unauthorized(api, kitchen_manager_headers):
    """PRD §2.1: "`SalesManager` owns event orders, order lines, quotes, confirmation,
    actualization, and cancellation."
    PRD §2.1: "When the headers are valid but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/kitchenmanager_create_event_order_unauthorized
    """
    validate_error(api.create_event_order(create_event_order_payload(), kitchen_manager_headers),
                   ApiErrorId.ERR_UNAUTHORIZED)


def test_salesmanager_create_ingredient_unauthorized(api, sales_manager_headers):
    """PRD §2.1: "`Admin` owns configuration assets — the ingredient inventory,
    production stations, rental equipment pool, and the staff roster."
    PRD §2.1: "When the headers are valid but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/salesmanager_create_ingredient_unauthorized
    """
    validate_error(api.create_ingredient(create_ingredient_payload(on_hand_qty=100), sales_manager_headers),
                   ApiErrorId.ERR_UNAUTHORIZED)


def test_create_event_order_missing_auth_returns_401(api, no_auth_headers):
    """PRD §2.1: "If either header is missing or carries an unrecognized value, the
    request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/create_event_order_missing_auth_returns_401
    """
    validate_error(api.create_event_order(create_event_order_payload(), no_auth_headers),
                   ApiErrorId.ERR_UNAUTHENTICATED)
