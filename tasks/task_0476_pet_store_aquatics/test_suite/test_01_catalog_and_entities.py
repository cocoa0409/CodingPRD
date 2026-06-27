"""Catalog & entity CRUD: creation defaults, required fields, enums,
system fields, computed fields, FK existence, uniqueness, and listing."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS,
    create_store_payload, create_product_payload, create_inventory_lot_payload,
    assert_store, assert_product, assert_inventory_lot,
    make_store, make_product,
)

INVMGR = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["store_clerk_headers"]


def test_create_store_returns_201_with_defaults(api):
    """PRD §3.1: "an optional `loyalty_point_value_cents` may be supplied to set
    the cents of redeemable value carried by one loyalty point at that store,
    defaulting to 1 when omitted. A store is born `OPEN`".
    PRD §2.4: "The `version` field is an integer that begins at its initial value
    when the resource is created".

    Design: Corner/entities/create_store_returns_201_with_defaults
    """
    res = api.create_store({"name": "Main", "state_code": "CA"}, INVMGR)
    store = validate_success(res, 201)
    assert_store(store)
    assert store["status"] == "OPEN", "new store defaults to OPEN"
    assert store["loyalty_point_value_cents"] == 1, "default loyalty value is 1"
    assert store["version"] == 1, "version begins at 1 on creation"


def test_get_store_not_found_returns_404(api):
    """PRD §2.5: "The request is rejected with the not-found error specific to
    the first missing resource — `ERR_STORE_NOT_FOUND`, ... according to which
    resource type was not found."

    Design: Corner/entities/get_store_not_found_returns_404
    """
    res = api.get_store(NON_EXISTENT_UUID, INVMGR)
    validate_error(res, ApiErrorId.ERR_STORE_NOT_FOUND)


def test_create_product_missing_required_field_returns_422(api):
    """PRD §3.1: "a `unit_price_cents` list price that must be greater than zero."
    PRD §2.6: "Field-level validation under the sixth step rejects with
    `ERR_INVALID_FIELD_VALUE` (HTTP 422) any body whose values are out of range
    or of the wrong type."

    Design: Corner/entities/create_product_missing_required_field_returns_422
    """
    res = api.create_product(
        {"sku": "X1", "name": "NoPrice", "category": "FOOD"}, INVMGR
    )
    validate_error(res, ApiErrorId.ERR_INVALID_FIELD_VALUE)


def test_create_product_invalid_enum_category_returns_422(api):
    """PRD §3.1: "a `category` that is one of `FOOD`, `HABITAT`, `ACCESSORY`, or
    `MEDICATION`".
    PRD §2.6: "any value of `severity`, `category`, `animal_class`, or
    `service_type` that is not one of its permitted enumeration members."

    Design: Corner/entities/create_product_invalid_enum_category_returns_422
    """
    res = api.create_product(
        {"sku": "X2", "name": "Bad", "category": "TOY", "unit_price_cents": 100},
        INVMGR,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_FIELD_VALUE)


def test_product_default_is_prescription_diet_false(api):
    """PRD §3.1: "Two optional flags shape downstream behavior:
    `is_prescription_diet`, which defaults to false ..., and
    `loyalty_points_per_unit`, a non-negative count of loyalty points earned per
    unit sold, defaulting to 0. Every product also exposes a derived
    `recall_state`, one of `CLEAR` or `RECALLED`, ...; a freshly created product
    is `CLEAR`."

    Design: Corner/entities/product_default_is_prescription_diet_false
    """
    res = api.create_product(
        {"sku": "X3", "name": "Plain", "category": "FOOD", "unit_price_cents": 500},
        INVMGR,
    )
    product = validate_success(res, 201)
    assert product["is_prescription_diet"] is False
    assert product["loyalty_points_per_unit"] == 0
    assert product["recall_state"] == "CLEAR"


def test_system_fields_ignored_on_inventory_lot_create(api):
    """PRD §3.2: "A newly received lot is `AVAILABLE`, with `quantity_reserved`
    initialized to zero."
    PRD §2.4: "The `version` field is an integer that begins at its initial value
    when the resource is created".

    Design: Corner/entities/system_fields_ignored_on_inventory_lot_create
    """
    store = make_store()
    product = make_product()
    res = api.create_inventory_lot(
        create_inventory_lot_payload(
            store["id"], product["id"], lot_code="L1", quantity_on_hand=20,
        ),
        INVMGR,
    )
    lot = validate_success(res, 201)
    assert_inventory_lot(lot)
    assert lot["quantity_reserved"] == 0
    assert lot["status"] == "AVAILABLE"
    assert lot["version"] == 1


def test_computed_recall_state_clear_when_no_open_recall(api):
    """PRD §3.1: "A product is `RECALLED` whenever at least one `OPEN` `Recall`
    covers it ..., and `CLEAR` when no open recall does."

    Design: Corner/entities/computed_recall_state_clear_when_no_open_recall
    """
    product = make_product()
    res = api.get_product(product["id"], CLERK)
    fetched = validate_success(res, 200)
    assert fetched["recall_state"] == "CLEAR"


def test_fk_referenced_store_not_found_on_lot_create(api):
    """PRD §2.5: "Creation endpoints that carry foreign-key body fields (such as
    `product_id`, `store_id`, ...) resolve each referenced entity and reject with
    the corresponding not-found error when any does not exist."

    Design: Corner/entities/fk_referenced_store_not_found_on_lot_create
    """
    product = make_product()
    res = api.create_inventory_lot(
        create_inventory_lot_payload(
            NON_EXISTENT_UUID, product["id"], lot_code="L1", quantity_on_hand=5,
        ),
        INVMGR,
    )
    validate_error(res, ApiErrorId.ERR_STORE_NOT_FOUND)


def test_duplicate_sku_returns_409(api):
    """PRD §2.7: "A `Product` `sku` must be globally unique across the catalog."
    PRD §2.7: "Three uniqueness rules are enforced, each rejecting a violating
    create with `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

    Design: Corner/entities/duplicate_sku_returns_409
    """
    validate_success(
        api.create_product(
            {"sku": "DUP", "name": "First", "category": "FOOD",
             "unit_price_cents": 1000},
            INVMGR,
        ), 201,
    )
    res = api.create_product(
        {"sku": "DUP", "name": "Second", "category": "FOOD",
         "unit_price_cents": 2000},
        INVMGR,
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_RESOURCE)


def test_list_products_pagination_envelope(api):
    """PRD §2.3: "Paginated list responses include the following fields in the
    `meta` object of the response envelope: `limit`, `offset`, `total_count`, and
    `has_more`."
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    Design: Corner/entities/list_products_pagination_envelope
    """
    make_product(sku="PG1", name="A")
    make_product(sku="PG2", name="B")
    res = api.list_products(CLERK, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert len(data) == 1, "limit=1 returns exactly one product"
    assert meta["total_count"] >= 2
    assert meta["has_more"] is True
