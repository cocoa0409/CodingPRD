"""Catalog CRUD: product/sku creation, computed safety flag, defaults, listings, not-found."""
import test_helpers as H


def test_create_product_returns_201_with_fields(api, merchops_headers):
    """PRD §3.1: "A `MerchOps` or `PlatformAdmin` operator seeds the catalog by creating a
    `Product`, supplying its `product_type` — one of `CANDLE`, `WAX_MELT`, `SOAP`, or
    `BATH_BOMB` — along with a marketing `collection_name` (such as an "Autumn Hearth" line),
    a `scent_family` grouping (such as WOODY, CITRUS, or FLORAL), and a display `title`."
    PRD §4: "Operations that create a new, distinct resource return `201 Created`."

    Design: Corner/entities/product_create_returns_201_with_fields
    """
    payload = H.create_product_payload(
        product_type="BATH_BOMB", collection_name="Spa", scent_family="FLORAL", title="Rose Bomb")
    product = H.validate_success(api.create_product(payload, merchops_headers), 201)
    H.assert_product(product)
    assert product["product_type"] == "BATH_BOMB"
    assert product["collection_name"] == "Spa"
    assert product["scent_family"] == "FLORAL"
    assert product["title"] == "Rose Bomb"


def test_sku_requires_safety_label_computed_from_product_type(api, merchops_headers):
    """PRD §3.1: "The sku's `requires_safety_label` flag is computed, not supplied: it is true
    exactly when the parent product's `product_type` is `CANDLE` or `WAX_MELT`, and any
    client-provided value is ignored."

    Design: Corner/entities/sku_requires_safety_label_computed
    """
    candle = H.new_product(product_type="CANDLE")
    soap = H.new_product(product_type="SOAP")
    candle_sku = H.validate_success(
        api.create_sku(candle["id"], H.create_sku_payload(scent="Amber", list_price_cents=3000),
                       merchops_headers), 201)
    soap_sku = H.validate_success(
        api.create_sku(soap["id"], H.create_sku_payload(scent="Lemon", list_price_cents=900),
                       merchops_headers), 201)
    assert candle_sku["requires_safety_label"] is True
    assert soap_sku["requires_safety_label"] is False


def test_create_sku_missing_list_price_rejected(api, merchops_headers):
    """PRD §2.11: "General request-format validation (`ERR_VALIDATION`) — required fields
    present, correct types, valid enums, and strictly positive quantities and prices — applies
    to all endpoints as the catch-all for malformed input."

    Design: Corner/entities/create_sku_missing_required_list_price
    """
    product = H.new_product(product_type="SOAP")
    payload = {"size": "SMALL", "scent": "Lime"}  # no list_price_cents
    H.validate_error(api.create_sku(product["id"], payload, merchops_headers),
                     H.ApiErrorId.ERR_VALIDATION)


def test_list_skus_filtered_by_product(api, merchops_headers):
    """PRD §3.1: "Skus can be listed and filtered by their `product_id` for reverse lookup."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and `has_more` in
    the `meta` object of the envelope, where `total_count` is the number of matching items
    before pagination and `has_more` is true when items remain beyond the returned page."

    Design: Corner/entities/list_skus_by_product_reverse_lookup
    """
    product = H.new_product(product_type="SOAP")
    H.new_sku(product["id"], list_price_cents=500, scent="A")
    H.new_sku(product["id"], list_price_cents=700, scent="B", size="LARGE")
    data, meta = H.validate_paginated(api.list_skus(merchops_headers, params={"product_id": product["id"]}))
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert all(s["product_id"] == product["id"] for s in data)


def test_order_type_defaults_to_retail(api):
    """PRD §3.6: "The optional `order_type` — one of `RETAIL`, `BULK`, or `GIFT`, defaulting to
    `RETAIL` — drives later pricing eligibility and checkout constraints."

    Design: Corner/entities/order_type_defaults_retail
    """
    customer = H.new_customer()
    resp = api.create_order(customer["id"], {}, H.make_customer_headers(customer["id"]))
    order = H.validate_success(resp, 201)
    assert order["order_type"] == "RETAIL"


def test_get_nonexistent_order_returns_not_found(api, merchops_headers):
    """PRD §2.10: "The not-found errors are entity-specific: `ERR_PRODUCT_NOT_FOUND`,
    `ERR_SKU_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_DROP_NOT_FOUND`, `ERR_BUNDLE_NOT_FOUND`,
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, and
    `ERR_SUBSCRIPTION_NOT_FOUND`, each returning HTTP 404."

    Design: Corner/entities/get_order_nonexistent_returns_not_found
    """
    H.validate_error(api.get_order(H.NON_EXISTENT_UUID, merchops_headers),
                     H.ApiErrorId.ERR_ORDER_NOT_FOUND)


def test_list_order_lines_filtered_by_order(api, merchops_headers):
    """PRD §3.6: "Individual lines can be fetched by `order_line_id` or listed and filtered by
    `order_id`, `sku_id`, or `batch_id`."

    Design: Corner/endpoints/list_order_lines_by_order_reverse_lookup
    """
    cat = H.released_catalog(product_type="SOAP", list_price_cents=900, quantity=50)
    customer = H.new_customer()
    order = H.new_order(customer["id"])
    H.add_line(order["id"], customer["id"], cat["sku"]["id"], cat["batch"]["id"], 1)
    H.add_line(order["id"], customer["id"], cat["sku"]["id"], cat["batch"]["id"], 2)
    data, meta = H.validate_paginated(api.list_order_lines(merchops_headers, params={"order_id": order["id"]}))
    assert len(data) == 2
    assert meta["total_count"] == 2
    assert all(line["order_id"] == order["id"] for line in data)


def test_activate_bundle_with_items_succeeds(api, merchops_headers):
    """PRD §3.4: "Activating a bundle moves it `DRAFT → ACTIVE`, after which it is publicly
    purchasable; activation requires the bundle to contain at least one item, and activating an
    empty bundle is rejected with `ERR_EMPTY_BUNDLE`."

    Design: Corner/endpoints/bundle_activate_with_items_succeeds
    """
    cat = H.released_catalog(product_type="SOAP", list_price_cents=900)
    bundle = H.new_bundle(items=[{"sku_id": cat["sku"]["id"], "quantity": 2}],
                          bundle_price_cents=1700, title="Gift Set")
    assert bundle["status"] == "DRAFT"
    activated = H.validate_success(api.activate_bundle(bundle["id"], merchops_headers), 200)
    assert activated["status"] == "ACTIVE"
