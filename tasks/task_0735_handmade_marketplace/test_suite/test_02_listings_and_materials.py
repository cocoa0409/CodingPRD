"""Listing creation/defaults/publication, material stock posture, and listing lists."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    make_seller_headers,
    create_shop, create_shipping_profile, create_listing, publish_listing,
)


# ==========================================================================
# Difficulty / boundary_precision_check / material_low_stock_at_reorder_threshold
# ==========================================================================
def test_material_at_reorder_threshold_is_low_stock(api):
    """PRD §3.2: "When `stock_qty` is above 0 but at or below the `reorder_threshold` the
    material is `LOW_STOCK` — the threshold value itself counts as low."

    Design: Difficulty/boundary_precision_check/material_low_stock_at_reorder_threshold
    """
    shop = create_shop()
    resp = api.create_material(
        {"shop_id": shop["id"], "name": "Clay", "stock_qty": 5, "reorder_threshold": 5},
        make_seller_headers(shop["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "LOW_STOCK", "stock_qty == reorder_threshold must be LOW_STOCK"


def test_material_above_reorder_threshold_is_in_stock(api):
    """PRD §3.2: "When `stock_qty` is strictly greater than the `reorder_threshold` the
    material is `IN_STOCK`."

    Design: Difficulty/boundary_precision_check/material_low_stock_at_reorder_threshold
    """
    shop = create_shop()
    resp = api.create_material(
        {"shop_id": shop["id"], "name": "Glaze", "stock_qty": 6, "reorder_threshold": 5},
        make_seller_headers(shop["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "IN_STOCK", "stock_qty one above threshold must be IN_STOCK"


# ==========================================================================
# Corner / entities / listing_create_missing_required_returns_validation
# ==========================================================================
def test_listing_create_missing_fulfillment_type_returns_validation(api):
    """PRD §2.5: "Once identifiers resolve, request payloads are checked for structural
    validity: required fields present, correctly typed, and enumerated fields carrying a
    legal value. A structural failure is reported as `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/listing_create_missing_required_returns_validation
    """
    shop = create_shop()
    sp = create_shipping_profile(shop["id"])
    resp = api.create_listing(
        {"shop_id": shop["id"], "shipping_profile_id": sp["id"], "title": "No Type",
         "processing_time_days": 1, "price_cents": 2000},
        make_seller_headers(shop["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


# ==========================================================================
# Corner / entities / listing_defaults_applied_on_create
# ==========================================================================
def test_listing_defaults_to_draft_and_personalization_disabled(api):
    """PRD §3.3: "A newly created listing begins in `DRAFT`."
    PRD §3.3: "`personalization_enabled` (defaulting to false) controls whether buyers may
    attach a note at all".

    Design: Corner/entities/listing_defaults_applied_on_create
    """
    shop = create_shop()
    sp = create_shipping_profile(shop["id"])
    resp = api.create_listing(
        {"shop_id": shop["id"], "shipping_profile_id": sp["id"], "title": "Plain",
         "fulfillment_type": "READY_TO_SHIP", "processing_time_days": 1,
         "price_cents": 2000, "quantity": 3},
        make_seller_headers(shop["id"]))
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"
    assert data["personalization_enabled"] is False


# ==========================================================================
# Corner / entities / listings_list_pagination_envelope
# ==========================================================================
def test_listing_list_reports_total_count_and_has_more(api):
    """PRD §2.3: "The `meta` object of a list response carries the four pagination fields
    `limit`, `offset`, `total_count`, and `has_more`, where `total_count` reflects the
    full matching set before the limit/offset window is applied and `has_more` indicates
    whether items remain beyond the returned window."

    Design: Corner/entities/listings_list_pagination_envelope
    """
    shop = create_shop()
    sp = create_shipping_profile(shop["id"])
    seller = make_seller_headers(shop["id"])
    create_listing(shop["id"], sp["id"], title="A", price_cents=1000, quantity=1)
    create_listing(shop["id"], sp["id"], title="B", price_cents=1000, quantity=1)
    resp = api.list_listings(seller, params={"shop_id": shop["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


# ==========================================================================
# Corner / state_machines / publish_removed_listing_returns_invalid_state
# ==========================================================================
def test_publish_removed_listing_returns_invalid_state(api):
    """PRD §3.3: "deactivating with a `remove` flag set to true drives the listing to the
    terminal `REMOVED` state — permitted from `ACTIVE`, `INACTIVE`, or `SOLD_OUT` — after
    which it is hidden from all lists but still retrievable by explicit id fetch. Any of
    these transitions requested from a state in which it is undefined is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/publish_removed_listing_returns_invalid_state
    """
    shop = create_shop()
    sp = create_shipping_profile(shop["id"])
    seller = make_seller_headers(shop["id"])
    listing = create_listing(shop["id"], sp["id"], title="Gone", price_cents=2000, quantity=5)
    publish_listing(shop["id"], listing["id"])
    removed = validate_success(api.deactivate_listing(listing["id"], seller, {"remove": True}))
    assert removed["status"] == "REMOVED"
    resp = api.publish_listing(listing["id"], seller)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ==========================================================================
# Corner / validations / restock_invalid_qty_returns_error
# ==========================================================================
def test_material_restock_zero_qty_returns_error(api):
    """PRD §3.2: "A seller replenishes a material by restocking it, supplying a
    `restock_qty` that must be a positive integer; a non-positive or non-integer quantity
    is rejected with `ERR_RESTOCK_INVALID_QTY` (HTTP 400)."

    Design: Corner/validations/restock_invalid_qty_returns_error
    """
    shop = create_shop()
    seller = make_seller_headers(shop["id"])
    material = validate_success(api.create_material(
        {"shop_id": shop["id"], "name": "Beads", "stock_qty": 3, "reorder_threshold": 1},
        seller), 201)
    resp = api.restock_material(material["id"], seller, {"restock_qty": 0})
    validate_error(resp, ApiErrorId.ERR_RESTOCK_INVALID_QTY)


# ==========================================================================
# Corner / endpoints / listings_filtered_by_shop_id_reverse_reach
# ==========================================================================
def test_listings_filtered_by_shop_id(api):
    """PRD §2.5: "List endpoints accept optional filters that reverse-navigate these
    foreign keys — for example listings may be filtered by `shop_id`,
    `shipping_profile_id`, `primary_material_id`, `status`, or `fulfillment_type`".

    Design: Corner/endpoints/listings_filtered_by_shop_id_reverse_reach
    """
    shop = create_shop()
    sp = create_shipping_profile(shop["id"])
    seller = make_seller_headers(shop["id"])
    create_listing(shop["id"], sp["id"], title="A", price_cents=1000, quantity=1)
    create_listing(shop["id"], sp["id"], title="B", price_cents=1000, quantity=1)
    resp = api.list_listings(seller, params={"shop_id": shop["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert all(listing["shop_id"] == shop["id"] for listing in data)


# ==========================================================================
# Corner / errors / shipping_profile_not_found_on_listing_create
# ==========================================================================
def test_listing_create_with_missing_shipping_profile_returns_not_found(api):
    """PRD §2.5: "Every identifier a request supplies — whether a resource id in the URL
    path or a foreign-key field in the body — must resolve to an existing resource, and
    resolution proceeds left to right."
    PRD §2.5: "a missing shipping profile `ERR_SHIPPING_PROFILE_NOT_FOUND`".

    Design: Corner/errors/shipping_profile_not_found_on_listing_create
    """
    shop = create_shop()
    resp = api.create_listing(
        {"shop_id": shop["id"], "shipping_profile_id": NON_EXISTENT_UUID, "title": "Orphan",
         "fulfillment_type": "READY_TO_SHIP", "processing_time_days": 1,
         "price_cents": 2000, "quantity": 1},
        make_seller_headers(shop["id"]))
    validate_error(resp, ApiErrorId.ERR_SHIPPING_PROFILE_NOT_FOUND)
