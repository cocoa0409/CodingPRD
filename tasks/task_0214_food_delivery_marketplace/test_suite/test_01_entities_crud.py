"""Entity CRUD corners: creation envelope, not-found, required fields,
defaults, system-generated fields, enum validation, FK existence, empty order.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    api_client, ApiErrorId,
    assert_zone, assert_order,
    make_admin_headers, make_customer_headers,
    create_zone_payload, create_dasher_payload, create_restaurant_payload,
    create_order_payload, line_item,
    create_zone, create_restaurant, create_menu_item, create_customer,
    place_simple_order, get_first_line_item, dispatch,
    setup_issue_ready, setup_order_delivered,
    make_dasher_headers,
)

ADMIN = make_admin_headers()


def test_create_zone_returns_201_with_fields(api):
    """PRD §3.1: "A zone also exposes a read-only `active_order_count`, initialized to 0 at creation"
    PRD §2.4: "**`version`** (integer): A system-managed counter that starts at 1 on creation and increments by 1 on every mutation of the resource."

    Design: Corner/entities/create_zone_returns_201_with_fields
    """
    resp = api_client.create_zone(create_zone_payload(), ADMIN)
    data = validate_success(resp, expected_status=201)
    assert_zone(data)
    assert data["active_order_count"] == 0, "active_order_count must initialize to 0"
    assert data["version"] == 1, "version must start at 1"


def test_get_order_nonexistent_returns_not_found(api):
    """PRD §2.6: "the server validates them strictly left to right and rejects on the **first** identifier that does not resolve, using that resource's own not-found error."
    PRD §2.6: "The not-found codes are `ERR_ZONE_NOT_FOUND`, `ERR_RESTAURANT_NOT_FOUND`, `ERR_MENU_ITEM_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_DASHER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`"

    Design: Corner/entities/get_order_nonexistent_returns_not_found
    """
    resp = api_client.get_order(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)


def test_create_dasher_missing_required_home_zone_id(api):
    """PRD §2.7: "Malformed payloads — a missing required field or a type mismatch — are rejected with `ERR_INVALID_PAYLOAD`"
    PRD §3.3: "A **Dasher** is registered with a `name`, a `home_zone_id` identifying the single zone in which the dasher may be dispatched"

    Design: Corner/entities/create_dasher_missing_required_home_zone_id
    """
    resp = api_client.create_dasher({"name": "Dan"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_PAYLOAD.value)


def test_create_dasher_default_max_batch_size_applied(api):
    """PRD §3.3: "an optional `max_batch_size` (default 2, at least 1) ... and an optional `availability` (default `ONLINE`, the only other value being `OFFLINE`)."

    Design: Corner/entities/create_dasher_default_max_batch_size_applied
    """
    zone = create_zone()
    resp = api_client.create_dasher({"name": "Dan", "home_zone_id": zone["id"]}, ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["max_batch_size"] == 2, f"default max_batch_size must be 2, got {data['max_batch_size']}"
    assert data["availability"] == "ONLINE", "default availability must be ONLINE"


def test_order_system_fields_generated_input_ignored(api):
    """PRD §3.4: "At placement the order's `zone_id` is copied from the restaurant, fixing the pricing zone for the order's life."
    PRD §3.4: "is assigned `billing_status` `UNSETTLED`, and is assigned `fulfillment_status` `PLACED`"

    Design: Corner/entities/order_system_fields_generated_input_ignored
    """
    zone = create_zone()
    restaurant = create_restaurant(zone["id"])
    item = create_menu_item(restaurant["id"])
    customer = create_customer()
    order = place_simple_order(customer["id"], restaurant["id"], item["id"])
    assert_order(order)
    assert order["zone_id"] == zone["id"], "zone_id must be copied from the restaurant"
    assert order["fulfillment_status"] == "PLACED"
    assert order["billing_status"] == "UNSETTLED"


def test_place_order_invalid_refund_destination_enum(api):
    """PRD §2.7: "an enum field carrying an undeclared value is rejected with `ERR_INVALID_ENUM`." refund_destination is ORIGINAL or WALLET (PRD §3.12).

    Design: Corner/entities/place_order_invalid_refund_destination_enum
    """
    # Build a DELIVERED order then file an issue with a bad enum value.
    delivered = setup_order_delivered(zone_overrides={"service_fee_bps": 0},
                                      item_overrides={"price_cents": 500},
                                      order_overrides={"quantity": 2})
    order = delivered["order"]
    customer = delivered["customer"]
    li = get_first_line_item(order["id"], customer["id"])
    resp = api_client.file_issue(
        order["id"],
        {"line_item_id": li["id"], "missing_quantity": 1, "refund_destination": "BANK"},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_create_restaurant_unknown_zone_returns_not_found(api):
    """PRD §2.6: "Foreign-key identifiers supplied in a request body are
    validated after the path identifiers, in the order they appear, with the same
    per-resource not-found codes." ERR_ZONE_NOT_FOUND covers a missing zone.

    Design: Corner/entities/create_restaurant_unknown_zone_returns_not_found
    """
    resp = api_client.create_restaurant(
        {"zone_id": NON_EXISTENT_UUID, "name": "Burgers", "route_distance_km": 4}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_ZONE_NOT_FOUND.value)


def test_empty_line_items_returns_empty_order_error(api):
    """PRD §3.4: "An order placed with an empty `line_items` list is rejected with `ERR_EMPTY_ORDER`."

    Design: Corner/entities/empty_line_items_returns_empty_order_error
    """
    zone = create_zone()
    restaurant = create_restaurant(zone["id"])
    customer = create_customer()
    resp = api_client.create_order(
        create_order_payload(customer["id"], restaurant["id"], []),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER.value)
