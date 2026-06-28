"""Product catalog CRUD, defaults, SKU uniqueness, soft-delete, par supersession,
the empty-menu guard, and role-based access control.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    create_product, create_par, create_submitted_po, create_draft_invoice_with_lines,
    archive_product, get_product,
    create_product_payload,
    INVENTORY_MANAGER, PURCHASING_AGENT, BAR_MANAGER, make_unknown_role_headers,
)


def test_create_product_returns_201_with_system_fields(api):
    """PRD §3.1: "A newly created product is born `ACTIVE`, with `on_hand_units` at 0 and
    `needs_reorder` false."
    PRD §2.4: "an integer `version` that begins at 1 on creation and increments by exactly
    1 on each subsequent mutation."

    Design: Corner/entities/create_product_returns_201_with_system_fields
    """
    data = validate_success(api.create_product({
        "sku": "GIN-CR", "name": "Gin", "container_type": "BOTTLE",
        "container_volume_ml": 750, "unit_cost_cents": 2000}, INVENTORY_MANAGER),
        expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["on_hand_units"] == 0
    assert data["needs_reorder"] is False
    assert data["version"] == 1


def test_create_product_missing_required_field_rejected(api):
    """PRD §2.5: "Schema-level request validation — required fields present, enum values
    legal, numbers within their declared ranges, and any method-conditional field present —
    is enforced as the request is parsed, raising `ERR_INVALID_REQUEST` (HTTP 400) when the
    body is malformed."

    Design: Corner/entities/create_product_missing_required_field_returns_invalid_request
    """
    validate_error(api.create_product({
        "sku": "GIN-MR", "name": "Gin", "container_volume_ml": 750, "unit_cost_cents": 2000},
        INVENTORY_MANAGER),
        ApiErrorId.ERR_INVALID_REQUEST)


def test_create_product_invalid_enum_rejected(api):
    """PRD §3.1: "An `InventoryManager` registers a product by supplying its `sku` (a
    human-readable stock-keeping code of 1 to 40 characters), its display `name`, its
    `container_type` — one of `BOTTLE` or `KEG` — and its `container_volume_ml`, the
    nominal volume of one full container, which must be greater than zero."
    PRD §2.5: "Schema-level request validation — required fields present, enum values legal,
    numbers within their declared ranges, and any method-conditional field present — is
    enforced as the request is parsed, raising `ERR_INVALID_REQUEST` (HTTP 400) when the body
    is malformed."

    Design: Corner/entities/create_product_invalid_enum_returns_invalid_request
    """
    validate_error(api.create_product({
        "sku": "GIN-EN", "name": "Gin", "container_type": "CAN",
        "container_volume_ml": 750, "unit_cost_cents": 2000}, INVENTORY_MANAGER),
        ApiErrorId.ERR_INVALID_REQUEST)


def test_product_defaults_applied_when_optional_fields_omitted(api):
    """PRD §3.1: "`empty_container_weight_g`, the tare weight of an empty container in grams
    (defaulting to 0 ...); `density_g_per_ml`, the liquid density used to turn net weight into
    volume during weight counts (defaulting to 1.0 ...); and `case_pack`, the number of
    containers per ordering case (defaulting to 1 ...)."

    Design: Corner/entities/product_defaults_applied_when_optional_fields_omitted
    """
    data = validate_success(api.create_product({
        "sku": "GIN-DF", "name": "Gin", "container_type": "BOTTLE",
        "container_volume_ml": 750, "unit_cost_cents": 2000}, INVENTORY_MANAGER),
        expected_status=201)
    assert data["case_pack"] == 1
    assert data["density_g_per_ml"] == 1.0
    assert data["empty_container_weight_g"] == 0


def test_get_nonexistent_product_returns_not_found(api):
    """PRD §2.5: "The first reference that does not resolve to an existing resource causes
    the request to fail with `ERR_NOT_FOUND` (HTTP 404) before any business rule runs."

    Design: Corner/entities/get_product_nonexistent_returns_not_found
    """
    validate_error(api.get_product("00000000-0000-4000-8000-000000000000", INVENTORY_MANAGER),
                   ApiErrorId.ERR_NOT_FOUND)


def test_list_products_paginated_envelope(api):
    """PRD §2.3: "Every list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope, where
    `total_count` is the number of matching resources across all pages and `has_more`
    indicates whether further pages remain beyond the current one."

    Design: Corner/entities/list_products_paginated_envelope
    """
    create_product(sku="P-L1", name="A", unit_cost_cents=100)
    create_product(sku="P-L2", name="B", unit_cost_cents=200)
    data, meta = validate_paginated(api.list_products(INVENTORY_MANAGER, params={"limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_duplicate_sku_on_active_product_rejected(api):
    """PRD §3.1: "The `sku` must be unique across all products that are not archived; an
    attempt to register a `sku` that collides with an existing non-archived product is
    rejected with `ERR_DUPLICATE_SKU` (HTTP 409)."

    Design: Corner/entities/duplicate_sku_on_active_product_rejected
    """
    create_product(sku="GIN-DUP", name="Gin", unit_cost_cents=2000)
    validate_error(api.create_product({
        "sku": "GIN-DUP", "name": "Gin 2", "container_type": "BOTTLE",
        "container_volume_ml": 750, "unit_cost_cents": 2100}, INVENTORY_MANAGER),
        ApiErrorId.ERR_DUPLICATE_SKU)


def test_archived_product_frees_sku_for_reuse(api):
    """PRD §3.1: "Because uniqueness is enforced only over non-archived products, archiving
    a product frees its `sku` for reuse by a future product."

    Design: Corner/entities/archived_product_frees_sku_for_reuse
    """
    p = create_product(sku="GIN-RE", name="Gin", unit_cost_cents=2000)
    archive_product(p["id"])
    data = validate_success(api.create_product({
        "sku": "GIN-RE", "name": "Gin v2", "container_type": "BOTTLE",
        "container_volume_ml": 750, "unit_cost_cents": 2100}, INVENTORY_MANAGER),
        expected_status=201)
    assert data["sku"] == "GIN-RE"
    assert data["status"] == "ACTIVE"


def test_archived_product_excluded_from_active_filtered_list(api):
    """PRD §3.1: "The flat product list itself can be narrowed by `status`, by
    `container_type`, and by the `needs_reorder` flag."
    PRD §3.1: "Archiving a product is a soft delete performed by an `InventoryManager`: it
    sets the product's `status` to `ARCHIVED` and bumps its `version`."

    Design: Corner/cross_cutting/archived_product_excluded_from_default_list
    """
    active = create_product(sku="P-AC", name="Active", unit_cost_cents=100)
    archived = create_product(sku="P-AR", name="ToArchive", unit_cost_cents=100)
    archive_product(archived["id"])
    data, meta = validate_paginated(api.list_products(INVENTORY_MANAGER, params={"status": "ACTIVE"}))
    assert meta["total_count"] == 1
    ids = {p["id"] for p in data}
    assert archived["id"] not in ids
    assert active["id"] in ids


def test_par_supersede_recomputes_reorder_flag(api):
    """PRD §2.8: "Only one par setting may be active per product at any instant: when a new
    one is created it supersedes the prior active setting, which moves to `SUPERSEDED`, while
    the new setting is `ACTIVE`."
    PRD §2.8: "This flag is recomputed every single time `on_hand_units` changes, and also
    whenever a new par setting supersedes the old one."

    Design: Corner/cross_cutting/par_supersede_recomputes_reorder_flag
    """
    p = create_product(sku="P-SUP", name="A", unit_cost_cents=100)
    par1 = create_par(p["id"], par_level_units=10, reorder_point_units=0)
    # on_hand 0 >= reorder_point 0 -> needs_reorder false.
    data = validate_success(api.create_par_setting({
        "product_id": p["id"], "par_level_units": 12, "reorder_point_units": 5}, INVENTORY_MANAGER),
        expected_status=201)
    par2_id = data["id"]
    assert data["status"] == "ACTIVE"

    par1_refreshed = next(s for s in validate_success(
        api.list_par_settings(INVENTORY_MANAGER, params={"product_id": p["id"]}))
        if s["id"] == par1["id"])
    assert par1_refreshed["status"] == "SUPERSEDED"
    assert get_product(p["id"])["needs_reorder"] is True, "on_hand 0 < new reorder_point 5"


def test_empty_menu_engineering_rejected(api):
    """PRD §3.4: "The report's universe is exactly those active items on published recipes;
    it requires at least one such item whose combined cumulative `units_sold` across the
    universe is at least 1, otherwise it is rejected with `ERR_EMPTY_MENU` (HTTP 422)."

    Design: Corner/validations/empty_menu_engineering_rejected
    """
    validate_error(api.menu_engineering(BAR_MANAGER), ApiErrorId.ERR_EMPTY_MENU)


def test_bar_manager_cannot_create_product(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation under the access-control matrix in §4, the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/bar_manager_cannot_create_product
    """
    validate_error(api.create_product({
        "sku": "GIN-RB", "name": "Gin", "container_type": "BOTTLE",
        "container_volume_ml": 750, "unit_cost_cents": 2000}, BAR_MANAGER),
        ApiErrorId.ERR_UNAUTHORIZED)


def test_inventory_manager_cannot_post_invoice(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation under the access-control matrix in §4, the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/inventory_manager_cannot_post_invoice
    """
    p = create_product(sku="P-IV", name="A", unit_cost_cents=100)
    po = create_submitted_po([{"product_id": p["id"], "ordered_qty": 2, "unit_cost_cents": 100}])
    inv = create_draft_invoice_with_lines(po["id"], [
        {"product_id": p["id"], "received_qty": 2, "unit_cost_cents": 100}])
    # InventoryManager attempts a PurchasingAgent-exclusive post.
    validate_error(api.post_invoice(inv["id"], INVENTORY_MANAGER), ApiErrorId.ERR_UNAUTHORIZED)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a role the
    system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unknown_role_returns_unauthenticated
    """
    validate_error(api.create_product({
        "sku": "GIN-NA", "name": "Gin", "container_type": "BOTTLE",
        "container_volume_ml": 750, "unit_cost_cents": 2000}, make_unknown_role_headers()),
        ApiErrorId.ERR_UNAUTHENTICATED)
