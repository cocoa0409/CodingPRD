"""Catalog creation, inventory pricing, listing, and basic error surfaces.

Covers queue-B corner instances for entities and item-pricing calculations.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_product, create_inventory_item,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["store_clerk_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_create_product_returns_201_draft_version_one(api):
    """PRD §3.1: "Every new product begins with a catalog_status of DRAFT."
    PRD §2.4: "an integer version that starts at 1 and increments by one on every
    mutation of that resource."

    Design: Corner/entities/create_product_returns_201_with_all_fields
    """
    resp = api.create_product(
        {"artist": "Prince", "title": "Purple Rain", "format": "VINYL", "base_price_cents": 2500},
        MANAGER,
    )
    data = validate_success(resp, expected_status=201)
    assert data["catalog_status"] == "DRAFT", f"expected DRAFT, got {data['catalog_status']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"


def test_get_customer_not_found_returns_404(api):
    """PRD §2.8: "any missing resource yields ERR_NOT_FOUND (HTTP 404)."

    Design: Corner/entities/get_customer_not_found_returns_404
    """
    resp = api.get_customer(NON_EXISTENT_UUID, MANAGER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_product_missing_base_price_returns_invalid_request(api):
    """PRD §2.9: "A malformed body, a missing required field, or an invalid enum
    value is reported as ERR_INVALID_REQUEST (HTTP 400)."

    Design: Corner/entities/create_product_missing_required_field_returns_invalid_request
    """
    resp = api.create_product(
        {"artist": "Prince", "title": "1999", "format": "VINYL"}, MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_item_list_price_computed_ignores_client_input(api):
    """PRD §3.1: "For a store-owned copy, the price is the product's base_price_cents
    multiplied by the grade multiplier for the copy's condition_grade (the multipliers
    in §2.5), with that product rounded half up to whole cents."
    PRD §2.5: "NM by 1.00".

    Design: Corner/entities/item_list_price_computed_ignores_client_input
    """
    product = create_product(api, artist="U2", title="Achtung Baby", format="CD",
                             base_price_cents=2000)
    resp = api.create_inventory_item(
        {"product_id": product["id"], "is_used": False, "condition_grade": "NM"}, CLERK
    )
    data = validate_success(resp, expected_status=201)
    assert data["list_price_cents"] == 2000, f"NM of base-2000 must list at 2000, got {data['list_price_cents']}"


def test_list_products_pagination_envelope(api):
    """PRD §2.3: "Each list response carries limit, offset, total_count, and has_more
    inside its meta object, where total_count is the total number of matching records
    across all pages and has_more indicates whether records remain beyond the current page."

    Design: Corner/entities/list_products_pagination_envelope
    """
    create_product(api, artist="A1", title="T1", format="VINYL", base_price_cents=1000)
    create_product(api, artist="A2", title="T2", format="CD", base_price_cents=1200)
    resp = api.list_products(ANON, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert "total_count" in meta, "meta must contain total_count"
    assert "has_more" in meta, "meta must contain has_more"
    assert len(data) == 1, f"limit=1 must return exactly one record, got {len(data)}"


def test_item_list_price_used_vg_multiplier(api):
    """PRD §2.5: "VG by 0.60".
    PRD §3.1: "For a store-owned copy, the price is the product's base_price_cents
    multiplied by the grade multiplier for the copy's condition_grade (the multipliers
    in §2.5), with that product rounded half up to whole cents."

    Design: Corner/calculations/item_list_price_used_vg_multiplier
    """
    product = create_product(api, artist="Genesis", title="Duke", format="VINYL",
                             base_price_cents=2000)
    resp = api.create_inventory_item(
        {"product_id": product["id"], "is_used": True, "condition_grade": "VG"}, CLERK
    )
    data = validate_success(resp, expected_status=201)
    assert data["list_price_cents"] == 1200, f"used VG of base-2000 must list at 1200, got {data['list_price_cents']}"


def test_new_item_price_floored_at_base(api):
    """PRD §3.1: "a copy whose is_used is false is never priced below the product's
    reference price, so its list_price_cents is the greater of the rounded computed
    price and base_price_cents."
    PRD §2.5: "M multiplies by 1.10".

    Design: Corner/calculations/new_item_price_floored_at_base
    """
    product = create_product(api, artist="Rush", title="Moving Pictures", format="VINYL",
                             base_price_cents=2000)
    resp = api.create_inventory_item(
        {"product_id": product["id"], "is_used": False, "condition_grade": "M"}, CLERK
    )
    data = validate_success(resp, expected_status=201)
    assert data["list_price_cents"] == 2200, f"NEW M of base-2000 must list at 2200, got {data['list_price_cents']}"


def test_new_item_invalid_grade_rejected(api):
    """PRD §3.1: "when is_used is false, the condition_grade must be either M or NM,
    and any other grade on a new copy is rejected with ERR_INVALID_GRADE_FOR_NEW (HTTP 422)."

    Design: Corner/validations/new_item_invalid_grade_rejected
    """
    product = create_product(api, artist="Kraftwerk", title="Autobahn", format="VINYL",
                             base_price_cents=2000)
    resp = api.create_inventory_item(
        {"product_id": product["id"], "is_used": False, "condition_grade": "VG"}, CLERK
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_GRADE_FOR_NEW.value)


def test_fk_reverse_list_inventory_by_product(api):
    """PRD §4 (GET /shop/inventory-items): "List inventory items". PRD §3.1:
    "Physical stock is represented by InventoryItem records, each a single copy."

    Design: Corner/endpoints/fk_reverse_list_inventory_by_product
    """
    product = create_product(api, artist="Oasis", title="Definitely Maybe", format="CD",
                             base_price_cents=1500)
    create_inventory_item(api, product_id=product["id"], is_used=True, condition_grade="VG")
    create_inventory_item(api, product_id=product["id"], is_used=False, condition_grade="NM")
    resp = api.list_inventory_items(ANON, params={"product_id": product["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 copies of the product, got {len(data)}"
