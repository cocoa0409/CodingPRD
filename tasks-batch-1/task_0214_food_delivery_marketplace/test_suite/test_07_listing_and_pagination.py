"""List endpoints: pagination envelope and filter-by-zone."""
import pytest

from test_helpers import (
    validate_paginated,
    api_client,
    make_admin_headers, make_customer_headers,
    create_zone, create_restaurant, create_menu_item, create_customer,
    place_simple_order,
)

ADMIN = make_admin_headers()


def test_list_orders_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to return." and "Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Two orders, limit=1 -> one item, total_count 2, has_more true.

    Design: Corner/endpoints/list_orders_pagination_envelope
    """
    zone = create_zone()
    restaurant = create_restaurant(zone["id"])
    item = create_menu_item(restaurant["id"])
    customer = create_customer()
    place_simple_order(customer["id"], restaurant["id"], item["id"])
    place_simple_order(customer["id"], restaurant["id"], item["id"])
    ch = make_customer_headers(customer["id"])
    resp = api_client.list_orders(ch, params={"customer_id": customer["id"],
                                              "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"limit=1 must return one item, got {len(data)}"
    assert meta["total_count"] == 2, f"total_count must be 2, got {meta['total_count']}"
    assert meta["has_more"] is True, "has_more must be true with 2 of 1 returned"


def test_filtered_restaurants_by_zone(api):
    """PRD §3.13: "Restaurant listings may be narrowed by `zone_id`"

    Filtering by a zone with no restaurants returns an empty list.

    Design: Corner/endpoints/filtered_restaurants_by_zone
    """
    zone_a = create_zone(name="A")
    zone_b = create_zone(name="B")
    create_restaurant(zone_a["id"], name="OnlyA")
    resp = api_client.list_restaurants(ADMIN, params={"zone_id": zone_b["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 0, f"zone B has no restaurants, got {len(data)}"
