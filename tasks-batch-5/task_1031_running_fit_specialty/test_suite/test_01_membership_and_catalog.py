"""Membership registration, catalog defaults, and list envelopes.

Queue B (Corner) — entities & endpoints sections.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_member,
    assert_product,
    fixtures as fx,
)


def test_member_create_success(api, sm):
    """PRD 3.1: "A freshly created `Member` begins with `status` `ACTIVE` (the
    alternative being `SUSPENDED`), a `loyalty_points_balance` of zero, a
    `tier_qualifying_spend_cents` of zero, and a `loyalty_tier` of `STANDARD`."

    Design: Corner/entities/c_member_create_success
    """
    resp = api.create_member(
        {"email": "c1@x.com", "full_name": "C One", "state_code": "OR"}, sm
    )
    data = validate_success(resp, 201)
    assert_member(data)
    assert data["loyalty_points_balance"] == 0
    assert data["loyalty_tier"] == "STANDARD"
    assert data["status"] == "ACTIVE"


def test_member_not_found(api, sm):
    """PRD 2.10: "a nonexistent identifier anywhere in the path yields
    `ERR_NOT_FOUND` before any body is inspected."

    Design: Corner/entities/c_member_not_found_returns_404
    """
    resp = api.get_member(NON_EXISTENT_UUID, sm)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_member_missing_required_field(api, sm):
    """PRD 2.9: "**Body well-formedness** — required fields present, enum values
    valid, `quantity` at least 1, and `scheduled_end` strictly after
    `scheduled_start`, else `ERR_VALIDATION` (422)."

    Design: Corner/entities/c_member_missing_required_field_returns_invalid_request
    """
    resp = api.create_member({"email": "c2@x.com", "state_code": "OR"}, sm)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)


def test_product_defaults_applied(api, sm):
    """PRD 3.2: "For a shoe, `mileage_life_miles` records the recommended
    retirement mileage and defaults to 500 when omitted"
    PRD 3.2: "The manager may seed inventory at creation with `initial_stock`,
    which sets `stock_on_hand` (defaulting to zero); `stock_reserved` starts at
    zero and `availability` is computed immediately."
    PRD 2.6: "`availability` is `IN_STOCK` whenever `stock_on_hand` is greater
    than zero and `OUT_OF_STOCK` otherwise."

    Design: Corner/entities/c_product_defaults_applied
    """
    resp = api.create_product(
        {"sku": "C-DEF", "name": "Default Gel", "category": "NUTRITION", "unit_price_cents": 3000},
        sm,
    )
    data = validate_success(resp, 201)
    assert_product(data)
    assert data["mileage_life_miles"] == 500
    assert data["stock_on_hand"] == 0
    assert data["available_units"] == 0
    assert data["availability"] == "OUT_OF_STOCK"


def test_orderline_unit_price_snapshot(api, sm):
    """PRD 3.3: "On creation the system creates one `OrderLine` per entry,
    stamping each line's `order_id`, snapshotting the product's price into the
    line's `unit_price_cents`, and setting `is_returned` to false. A line's
    `line_gross_cents` is its snapshot `unit_price_cents` multiplied by its
    `quantity`."

    Design: Corner/entities/c_orderline_unit_price_snapshot
    """
    member = fx.create_member()
    product = fx.create_product(category="SHOE", unit_price_cents=4599, initial_stock=3)
    order = fx.create_single_line_order(member["id"], product["id"], 1)
    line = fx.get_first_order_line(order["id"])
    assert line["unit_price_cents"] == 4599
    assert line["line_gross_cents"] == 4599


def test_orders_list_paginated_envelope(api, sm):
    """PRD 2.3: "The `meta` block of a list response reports `limit`, `offset`,
    `total_count` (the total number of matching resources before pagination),
    and `has_more` (true when unreturned matches remain beyond the current page)."

    Design: Corner/endpoints/c_orders_list_paginated_envelope
    """
    member = fx.create_member()
    product = fx.create_product(category="GEAR", unit_price_cents=3000, initial_stock=3)
    fx.create_single_line_order(member["id"], product["id"], 1)
    resp = api.list_orders(sm, params={"member_id": member["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1
