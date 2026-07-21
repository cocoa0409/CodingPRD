"""Role authorization, not-found resolution, and list/filter envelopes (corners)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, NON_EXISTENT_UUID,
    new_product, new_account, new_order, new_line,
    setup_confirmed_order, make_wholesaler_headers, create_product_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
CATALOG = TEST_USERS["catalog_headers"]
PROD = TEST_USERS["production_headers"]
SALES = TEST_USERS["sales_headers"]


# ---- Corner / entities & errors — not found ----

def test_get_unknown_product_returns_not_found(api):
    """PRD §2.5: "The first identifier that fails to resolve determines the rejection, each
    with its own dedicated code: `ERR_PRODUCT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_BATCH_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`,
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_LINE_RESOURCE_NOT_FOUND` (for a production line),
    `ERR_STATION_NOT_FOUND`, `ERR_TIN_RUN_NOT_FOUND`, and `ERR_COMPONENT_NOT_FOUND`."

    Design: Corner/entities/corner_product_get_not_found
    """
    resp = api.get_product(NON_EXISTENT_UUID, CATALOG)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_FOUND.value)


def test_get_unknown_order_returns_not_found(api):
    """PRD §2.5: "All existence checks return HTTP 404."
    PRD §2.5: "The first identifier that fails to resolve determines the rejection, each
    with its own dedicated code: `ERR_PRODUCT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
    `ERR_BATCH_NOT_FOUND`, `ERR_LINE_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, ..."

    Design: Corner/errors/corner_order_not_found_returns_404
    """
    resp = api.get_order(NON_EXISTENT_UUID, SALES)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND.value)


def test_get_unknown_account_returns_not_found(api):
    """PRD §2.5: "The first identifier that fails to resolve determines the rejection, each
    with its own dedicated code: ... `ERR_ORDER_NOT_FOUND`, `ERR_ACCOUNT_NOT_FOUND`,
    `ERR_LINE_RESOURCE_NOT_FOUND` (for a production line), ..."

    Design: Corner/errors/corner_account_not_found_returns_404
    """
    resp = api.get_wholesale_account(NON_EXISTENT_UUID, SALES)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value)


# ---- Corner / rbac ----

def test_wholesaler_cannot_create_product(api):
    """PRD §2.1: "When a well-authenticated caller attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/corner_wholesaler_cannot_create_product
    """
    account = new_account(api)
    headers = make_wholesaler_headers(account["id"])
    resp = api.create_product(create_product_payload(), headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_sales_agent_cannot_pack_order(api):
    """PRD §2.1: "`ProductionOperator` owns production and packing — production lines,
    batches, labeling stations, tin runs, and order packing."

    Design: Corner/rbac/corner_sales_agent_cannot_pack_order
    """
    ctx = setup_confirmed_order(api, requested_grams=100, allergen_ack=True, lot_grams=500)
    measurements = [{"line_id": ctx["line"]["id"], "gross_grams": 108, "tare_grams": 8}]
    resp = api.pack_order(ctx["order"]["id"], {"line_measurements": measurements}, SALES)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ---- Corner / endpoints ----

def test_list_orders_returns_pagination_envelope(api):
    """PRD §2.3: "Paginated and non-paginated list-based responses include the following
    fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`,
    and `has_more`."

    Design: Corner/endpoints/corner_list_orders_returns_pagination_envelope
    """
    account = new_account(api)
    new_order(api, account["id"])
    new_order(api, account["id"])
    resp = api.list_orders(SALES, params={"wholesale_account_id": account["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, meta["total_count"]
    assert meta["has_more"] is False, meta["has_more"]
    assert len(data) == 2, len(data)


def test_list_order_lines_filtered_by_order(api):
    """PRD §3.6: "Each line belongs to its parent via `order_id`."

    Design: Corner/endpoints/corner_reverse_reach_order_lines_by_order
    """
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    account = new_account(api)
    order = new_order(api, account["id"])
    line = new_line(api, order["id"], cham["id"], 100)
    resp = api.list_order_lines(SALES, params={"order_id": order["id"]})
    data, _meta = validate_paginated(resp)
    assert any(item["id"] == line["id"] for item in data), "order's line must be listed"
