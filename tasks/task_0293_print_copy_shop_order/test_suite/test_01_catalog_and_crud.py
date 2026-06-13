"""Catalog CRUD, input validation, computed fields, defaults, and listing."""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    is_valid_uuid,
    assert_shop, assert_product, assert_customer, assert_order_line,
    create_shop_payload, create_product_payload, create_order_line_payload,
    create_shop, create_customer, create_product, create_order, add_line,
    TEST_USERS, make_customer_headers, NON_EXISTENT_UUID, ApiErrorId,
)

STAFF = TEST_USERS["shop_staff_headers"]


def test_create_shop_returns_201_with_echoed_config(api):
    """PRD §3.1: "These include `tax_rate_bps`, the sales tax in basis points applied to
    the taxable subtotal (which must be between 0 and 2000 inclusive)". PRD §2.4: "Each
    resource also carries a `created_at` timestamp, an `updated_at` timestamp, and an
    integer `version`."

    Design: Corner/entities/create_shop_returns_201_with_all_fields
    """
    payload = create_shop_payload(name="S1", tax_rate_bps=825, rush_surcharge_bps=2000,
                                  rush_cutoff_hour_utc=14, standard_turnaround_days=3,
                                  rush_turnaround_days=1, daily_unit_capacity=50)
    shop = validate_success(api.create_shop(payload, STAFF), 201)
    assert_shop(shop)
    assert shop["tax_rate_bps"] == 825
    assert isinstance(shop["version"], int)


def test_get_nonexistent_order_returns_not_found(api):
    """PRD §2.5: "the first identifier that does not resolve produces `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_order_nonexistent_returns_not_found
    """
    create_shop(name="S2")
    res = api.get_order(NON_EXISTENT_UUID, STAFF)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_create_order_line_missing_quantity_returns_validation(api):
    """PRD §3.9: "A malformed request or a missing required body field is rejected with
    `ERR_VALIDATION` (HTTP 400)." PRD §3.2: "Adding a line requires the parent `order_id`,
    the `product_id` being ordered, and a `quantity` (at least 1)".

    Design: Corner/entities/create_order_line_missing_quantity_returns_validation
    """
    shop = create_shop(name="S3")
    cust = create_customer(shop["id"], email="s3@x.com")
    prod = create_product(shop["id"], name="P", category="COPIES",
                          base_unit_price_cents=500, requires_proof=False, requires_press=False)
    order = create_order(shop["id"], cust["id"])
    res = api.create_order_line(
        {"order_id": order["id"], "product_id": prod["id"]},
        make_customer_headers(cust["id"]))
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_order_line_service_level_defaults_to_standard(api):
    """PRD §3.2: "a `service_level` that is either `STANDARD` or `RUSH` (defaulting to
    `STANDARD`)."

    Design: Corner/entities/order_line_service_level_defaults_to_standard
    """
    shop = create_shop(name="S4")
    cust = create_customer(shop["id"], email="s4@x.com")
    prod = create_product(shop["id"], name="P", category="COPIES",
                          base_unit_price_cents=500, requires_proof=False, requires_press=False)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 10, cust["id"])
    assert line["service_level"] == "STANDARD"


def test_order_line_estimate_and_production_units_computed(api):
    """PRD §3.2: "On creation the system computes the line's `estimate_line_cents` and its
    `production_units`." PRD §3.2: "The `production_units` for a line is the quantity
    multiplied by the product's `unit_size`."

    Design: Corner/entities/order_line_estimate_and_production_units_computed
    """
    shop = create_shop(name="S5")
    cust = create_customer(shop["id"], email="s5@x.com")
    prod = create_product(shop["id"], name="Banner", category="BANNER",
                          base_unit_price_cents=5000, unit_size=2,
                          requires_proof=False, requires_press=True)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 3, cust["id"])
    assert_order_line(line)
    assert line["production_units"] == 6, "production_units = quantity 3 * unit_size 2"
    assert line["estimate_line_cents"] == 15000, "base 5000 * qty 3, no tier"


def test_customer_id_is_server_minted_uuid(api):
    """PRD §2.4: "The `id` field is never supplied by the client; clients address resources
    by their server-assigned identifiers". PRD §2.4: "carries a system-minted `id` that is
    a UUID with no type prefix, used for identity only."

    Design: Corner/entities/customer_id_system_minted_ignores_client_id
    """
    shop = create_shop(name="S6")
    cust = validate_success(
        api.create_customer({"shop_id": shop["id"], "email": "s6@x.com", "name": "S6C"}, STAFF),
        201)
    assert_customer(cust)
    assert is_valid_uuid(cust["id"]), "id must be a server-minted UUID"


def test_create_product_invalid_category_enum_rejected(api):
    """PRD §3.1: "giving it a `name` and a `category` that is one of `COPIES`, `BANNER`, or
    `BINDING`." PRD §3.9: "A malformed request or a missing required body field is rejected
    with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_product_invalid_category_enum_rejected
    """
    shop = create_shop(name="S7")
    res = api.create_product(
        {"shop_id": shop["id"], "name": "Bad", "category": "POSTER", "base_unit_price_cents": 500},
        STAFF)
    validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)


def test_list_products_filtered_by_shop_paginated(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_products_filtered_by_shop_paginated
    """
    shop = create_shop(name="S8")
    create_product(shop["id"], name="A", category="COPIES", base_unit_price_cents=500)
    create_product(shop["id"], name="B", category="BANNER", base_unit_price_cents=5000)
    data, meta = validate_paginated(
        api.list_products(STAFF, params={"shop_id": shop["id"], "limit": 10, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
