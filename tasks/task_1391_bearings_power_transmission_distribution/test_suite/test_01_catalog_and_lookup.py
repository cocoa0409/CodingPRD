"""Catalog, interchange lookup, branch creation, and listing envelope tests."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, NON_EXISTENT_UUID,
    create_product_payload, create_interchange_record_payload,
    create_contract_payload, create_branch_payload,
    assert_product, assert_interchange_record,
    ApiErrorId, TEST_USERS,
)

ANALYST = TEST_USERS["pricing_analyst_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
CONTRACT_ADMIN = TEST_USERS["contract_admin_headers"]


def test_product_create_missing_sku_returns_invalid_request(api):
    """PRD §3.1: "Creating a product requires `sku`, `description`, `family`,
    and `list_price_cents`".
    PRD §2.5: "required fields present and well-typed (`ERR_INVALID_REQUEST`, 400)".

    Design: Corner/entities/product_create_missing_sku_returns_invalid_request
    """
    payload = {"description": "No sku", "family": "BEARING", "list_price_cents": 1000}
    res = api.create_product(payload, ANALYST)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_product_create_defaults_and_system_fields(api):
    """PRD §3.1: "A new product starts in `ACTIVE` status with
    `last_price_change_at` null, meaning no price file has ever taken effect for it."

    Design: Corner/entities/product_create_defaults_and_system_fields
    """
    res = api.create_product(
        create_product_payload(sku="BRG-6000", list_price_cents=2500), ANALYST)
    product = validate_success(res, 201)
    assert_product(product)
    assert product["status"] == "ACTIVE", (
        f"new product must start ACTIVE, got {product['status']}")
    assert product["last_price_change_at"] is None, (
        f"last_price_change_at must be null until first price change, "
        f"got {product['last_price_change_at']}")
    assert product["superseded_by_id"] is None
    assert isinstance(product["version"], int)


def test_product_create_system_field_input_ignored(api):
    """PRD §3.1: "A new product starts in `ACTIVE` status with
    `last_price_change_at` null, meaning no price file has ever taken effect for it."

    Design: Corner/entities/product_create_system_field_input_ignored
    """
    payload = create_product_payload(sku="BRG-6001", list_price_cents=2500)
    payload["status"] = "OBSOLETE"  # client-supplied system field must not take
    res = api.create_product(payload, ANALYST)
    product = validate_success(res, 201)
    assert product["status"] == "ACTIVE", (
        f"client-supplied status must be ignored; product starts ACTIVE, "
        f"got {product['status']}")


def test_product_create_invalid_enum_returns_invalid_request(api):
    """PRD §3.1: "the family is one of `BEARING`, `GEARBOX`, `BELT`, `CHAIN`,
    or `SEAL`, and the `sku` must be unique across the catalog (`ERR_DUPLICATE_SKU`)".
    PRD §2.5: "required fields present and well-typed (`ERR_INVALID_REQUEST`, 400)".

    Design: Corner/entities/product_create_invalid_enum_returns_invalid_request
    """
    payload = create_product_payload(sku="XXX-1", family="WIDGET",
                                     list_price_cents=1000)
    res = api.create_product(payload, ANALYST)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_product_get_not_found_returns_404(api):
    """PRD §2.5: "every path resource id must exist, validated left to right
    along the path ... each missing resource yields its own not-found error
    with HTTP 404 — `ERR_PRODUCT_NOT_FOUND`".

    Design: Corner/entities/product_get_not_found_returns_404
    """
    res = api.get_product(NON_EXISTENT_UUID, ANALYST)
    validate_error(res, ApiErrorId.ERR_PRODUCT_NOT_FOUND, expected_status=404)


def test_contract_create_body_fk_must_exist(api):
    """PRD §2.5: "every body-supplied foreign key (`customer_id`, `branch_id`,
    `product_id`, `order_line_id`, `consumption_id`, `branch_stock_id`,
    `warranty_claim_id`) must also exist before any state or business rule runs".

    Design: Corner/entities/contract_create_body_fk_must_exist
    """
    payload = create_contract_payload(
        NON_EXISTENT_UUID, family="BEARING", price_basis="LIST_LESS",
        discount_pct=0.1, effective_from="2026-01-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z")
    res = api.create_contract(payload, CONTRACT_ADMIN)
    validate_error(res, ApiErrorId.ERR_CUSTOMER_NOT_FOUND, expected_status=404)


def test_products_list_pagination_envelope(api):
    """PRD §2.3: "All list endpoints accept the query parameters `limit` and
    `offset`. `limit` defaults to 10, must be at least 1, and may not exceed
    100; `offset` defaults to 0. List responses are sorted by `created_at`
    ascending, and the `meta` object of a list response carries `limit`,
    `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/products_list_pagination_envelope
    """
    for sku in ("PG-1", "PG-2", "PG-3"):
        api.create_product(
            create_product_payload(sku=sku, family="SEAL", list_price_cents=100),
            ANALYST)
    data, meta = validate_paginated(
        api.list_products(ANALYST, params={"limit": 1, "offset": 1}))
    assert len(data) == 1, f"limit=1 must return exactly 1 row, got {len(data)}"
    assert meta["total_count"] == 3, f"total_count must be 3, got {meta['total_count']}"
    assert meta["has_more"] is True, "offset 1 of 3 with limit 1 must report has_more"
    assert meta["limit"] == 1 and meta["offset"] == 1


def test_interchange_lookup_sizing_envelope_boundaries(api):
    """PRD §3.1: "A mapping names a `competitor_part_number`, the in-catalog
    `product_id` it interchanges to, an `interchange_class` of `EXACT`,
    `DIMENSIONAL`, or `FUNCTIONAL`, and the application shaft-diameter envelope
    `min_shaft_diameter_mm` through `max_shaft_diameter_mm`, both bounds
    inclusive. The flag `requires_engineering_review` is computed by the server:
    it is true if and only if the class is `FUNCTIONAL`."

    Design: Corner/entities/interchange_lookup_sizing_envelope_boundaries
    """
    product = validate_success(api.create_product(
        create_product_payload(sku="BRG-6010", list_price_cents=2500), ANALYST), 201)
    ir1 = validate_success(api.create_interchange_record(
        create_interchange_record_payload(
            product["id"], competitor_part_number="CMP-10",
            interchange_class="EXACT",
            min_shaft_diameter_mm=45, max_shaft_diameter_mm=55),
        ANALYST), 201)
    ir2 = validate_success(api.create_interchange_record(
        create_interchange_record_payload(
            product["id"], competitor_part_number="CMP-20",
            interchange_class="FUNCTIONAL",
            min_shaft_diameter_mm=45, max_shaft_diameter_mm=55),
        ANALYST), 201)
    assert_interchange_record(ir1)
    assert ir1["requires_engineering_review"] is False
    assert ir2["requires_engineering_review"] is True

    hits, _ = validate_paginated(
        api.list_interchange_records(ANALYST, params={"shaft_diameter_mm": 45}))
    assert len(hits) == 2, f"probe at inclusive lower bound 45 must match both, got {len(hits)}"
    misses, _ = validate_paginated(
        api.list_interchange_records(ANALYST, params={"shaft_diameter_mm": 56}))
    assert len(misses) == 0, f"probe 56 above max 55 must match nothing, got {len(misses)}"


def test_branch_create_invalid_hours_returns_invalid_request(api):
    """PRD §3.2: "a `business_open_hour` and `business_close_hour` (each 0–23,
    close strictly later than open or the create fails with `ERR_INVALID_REQUEST`)".

    Design: Corner/entities/branch_create_invalid_hours_returns_invalid_request
    """
    payload = create_branch_payload(
        code="BAD-1", business_open_hour=17, business_close_hour=8)
    res = api.create_branch(payload, ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
