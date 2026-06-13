"""Catalog CRUD, defaults, cross-distributor references, par replenishment, pagination,
duplicate constraints, catalog-revision counter, and RBAC denials.

Covers corner entities / calculations / endpoints / rbac / cross_cutting
(derived field reconciliation).
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    setup_base, create_distributor, create_warehouse, create_product, add_price_tier,
    create_customer, create_order, create_draft_order_with_line,
    TEST_USERS, NON_EXISTENT_UUID,
)

ADMIN = TEST_USERS["distributor_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
WAREHOUSE = TEST_USERS["warehouse_op_headers"]


# ─── Entities ──────────────────────────────────────────────────────────────

def test_create_distributor_starts_at_epoch_with_zero_revision(api):
    """PRD §3.1: "A new distributor starts with its `current_utc` at the epoch and its
    `catalog_revision` at zero."
    PRD §2.9: "a server-held clock that starts at the Unix epoch,
    `1970-01-01T00:00:00.000Z`."

    POST /distributors returns 201; the persisted record carries catalog_revision 0 and
    current_utc at the epoch.

    Design: Corner/entities/create_distributor_returns_201_with_system_fields
    """
    dist = validate_success(api.create_distributor({"name": "FreshCo"}, ADMIN), 201)
    fetched = validate_success(api.get_distributor(dist["id"], ADMIN), 200)
    assert fetched["catalog_revision"] == 0
    assert fetched["current_utc"] == "1970-01-01T00:00:00.000Z"


def test_create_product_missing_sku_rejected(api):
    """PRD §3.1: "It is created with its `distributor_id`, a `sku` unique within the
    distributor (a clash raising `ERR_DUPLICATE_SKU`), a `name`, a `category` such as
    DAIRY, PRODUCE, or DRY, and a `splits_per_case` giving how many split (each) units
    make up one case, which must be at least 1."
    PRD §3.3: "then request-body well-formedness — required fields present, enum members
    valid, and constrained integers non-negative — which on failure yields
    `ERR_INVALID_REQUEST`."

    POST /products without sku is rejected ERR_INVALID_REQUEST (422); sku is required.

    Design: Corner/entities/create_product_missing_required_sku_returns_invalid_request
    """
    dist = create_distributor()
    res = api.create_product(
        {"distributor_id": dist["id"], "name": "Cheddar", "category": "DAIRY",
         "splits_per_case": 12, "case_cost_cents": 1000}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_order_line_invalid_uom_enum_rejected(api):
    """PRD §3.3: "the `uom` (either CASE or SPLIT)."
    PRD §3.3: "then request-body well-formedness — required fields present, enum members
    valid, and constrained integers non-negative — which on failure yields
    `ERR_INVALID_REQUEST`."

    POST /orders/{id}/lines with uom 'BOX' (not CASE|SPLIT) is rejected
    ERR_INVALID_REQUEST (422).

    Design: Corner/entities/create_order_line_invalid_uom_enum_returns_invalid_request
    """
    base = setup_base()
    prod = create_product(base["distributor"]["id"])
    cust = create_customer(base["distributor"]["id"], base["route"]["id"])
    order = create_order(cust["id"])

    res = api.add_order_line(
        order["id"], {"product_id": prod["id"], "uom": "BOX", "ordered_qty": 1}, SALES)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_get_nonexistent_customer_not_found(api):
    """PRD §2.5: "the first identifier that does not resolve to an existing resource under
    the distributor causes the request to be rejected with `ERR_NOT_FOUND`."

    GET /customers/{id} with a well-formed but unknown UUID returns ERR_NOT_FOUND (404).

    Design: Corner/entities/get_customer_nonexistent_id_returns_not_found
    """
    create_distributor()
    res = api.get_customer(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_customer_with_route_in_other_distributor_rejected(api):
    """PRD §3.2: "The named `route_id` must resolve within the same distributor, or
    creation is rejected with `ERR_CROSS_DISTRIBUTOR_REFERENCE`."

    Creating a Customer whose route_id belongs to a different distributor is rejected
    ERR_CROSS_DISTRIBUTOR_REFERENCE (409).

    Design: Corner/entities/create_customer_route_in_other_distributor_cross_reference
    """
    d1 = create_distributor("D1")
    wh1 = create_warehouse(d1["id"])
    route1 = validate_success(api.create_route(
        {"distributor_id": d1["id"], "warehouse_id": wh1["id"], "code": "R1",
         "delivery_dow": 2, "cutoff_lead_hours": 24}, ADMIN), 201)
    d2 = create_distributor("D2")

    res = api.create_customer(
        {"distributor_id": d2["id"], "route_id": route1["id"], "name": "Diner A",
         "credit_limit_cents": 100000}, SALES)
    validate_error(res, "ERR_CROSS_DISTRIBUTOR_REFERENCE")


def test_product_status_default_active_then_discontinue(api):
    """PRD §3.1: "`split_allowed`, defaulting to true, controls whether the product may be
    ordered in split units."
    PRD §3.1: "The product's `status` begins `ACTIVE` and is system-managed; discontinuing
    a product sets `status` to `DISCONTINUED`."

    A newly created product defaults split_allowed true; discontinue flips status to
    DISCONTINUED.

    Design: Corner/entities/product_status_defaults_active_and_discontinue_sets_discontinued
    """
    dist = create_distributor()
    prod = create_product(dist["id"])
    assert prod["split_allowed"] is True
    assert prod["status"] == "ACTIVE"

    discontinued = validate_success(api.discontinue_product(prod["id"], ADMIN), 200)
    assert discontinued["status"] == "DISCONTINUED"


# ─── Calculations: par replenishment ───────────────────────────────────────

def test_par_replenishment_split_capable_vs_case_only(api):
    """PRD §3.2: "When the product's `split_allowed` is true, the suggestion is given in
    split units: `suggested_uom` is SPLIT and `suggested_qty` is exactly the split deficit."
    PRD §3.2: "When the product's `split_allowed` is false, the suggestion is rounded up to
    whole cases: `suggested_uom` is CASE and `suggested_qty` is the split deficit divided
    by the product's `splits_per_case`, rounded up to the next whole case."

    A split-capable item (par 30, on_hand 12) suggests SPLIT 18; a case-only item
    (par 30, on_hand 12, spc 12) suggests CASE ceil(18/12)=2.

    Design: Corner/calculations/par_replenishment_split_capable_vs_case_only
    """
    base = setup_base()
    dist_id, route_id = base["distributor"]["id"], base["route"]["id"]
    prod_split = create_product(dist_id, sku="SP-1", name="Splitable", category="DRY",
                                splits_per_case=6, split_allowed=True, case_cost_cents=600)
    prod_case = create_product(dist_id, sku="CO-1", name="CaseOnly", category="DRY",
                               splits_per_case=12, split_allowed=False, case_cost_cents=1200)
    cust = create_customer(dist_id, route_id)
    guide = validate_success(api.create_order_guide(
        {"customer_id": cust["id"], "name": "WEEKLY"}, SALES), 201)
    item_split = validate_success(api.create_order_guide_item(
        {"order_guide_id": guide["id"], "product_id": prod_split["id"],
         "par_level_splits": 30, "on_hand_splits": 12}, SALES), 201)
    item_case = validate_success(api.create_order_guide_item(
        {"order_guide_id": guide["id"], "product_id": prod_case["id"],
         "par_level_splits": 30, "on_hand_splits": 12}, SALES), 201)

    res = api.get_replenishment(guide["id"], SALES)
    data = validate_success(res, 200)
    by_item = {row["id"]: row for row in data}
    assert by_item[item_split["id"]]["suggested_uom"] == "SPLIT"
    assert by_item[item_split["id"]]["suggested_qty"] == 18
    assert by_item[item_case["id"]]["suggested_uom"] == "CASE"
    assert by_item[item_case["id"]]["suggested_qty"] == 2


# ─── Validations: split-not-allowed at line add ────────────────────────────

def test_split_uom_on_non_splittable_product_rejected(api):
    """PRD §3.3: "A line requested in SPLIT units against a product whose `split_allowed`
    is false is rejected with `ERR_SPLIT_NOT_ALLOWED`."

    Adding a SPLIT line for a product with split_allowed=false is rejected
    ERR_SPLIT_NOT_ALLOWED (422).

    Design: Corner/validations/split_uom_on_non_splittable_product_rejected
    """
    base = setup_base()
    prod = create_product(base["distributor"]["id"], sku="CO-1", name="CaseOnly",
                          category="DRY", splits_per_case=12, split_allowed=False,
                          case_cost_cents=1200)
    cust = create_customer(base["distributor"]["id"], base["route"]["id"])
    order = create_order(cust["id"])

    res = api.add_order_line(
        order["id"], {"product_id": prod["id"], "uom": "SPLIT", "ordered_qty": 3}, SALES)
    validate_error(res, "ERR_SPLIT_NOT_ALLOWED")


# ─── Endpoints: pagination, duplicates ─────────────────────────────────────

def test_list_products_pagination_envelope(api):
    """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    GET /products?distributor_id&limit=1 over a distributor with two products returns a
    one-element array with total_count 2 and has_more true.

    Design: Corner/endpoints/list_products_pagination_envelope
    """
    dist = create_distributor()
    create_product(dist["id"], sku="P-1", name="A", category="DRY")
    create_product(dist["id"], sku="P-2", name="B", category="DRY")

    data, meta = validate_paginated(
        api.list_products(ADMIN, params={"distributor_id": dist["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_pagination_limit_out_of_bounds_rejected(api):
    """PRD §2.3: "A `limit` outside the range 1 through 100, or a negative `offset`, is
    rejected with `ERR_VALIDATION_LIMIT`."

    GET /products with limit=101 (> max 100) is rejected ERR_VALIDATION_LIMIT (422).

    Design: Corner/endpoints/pagination_limit_out_of_bounds_rejected
    """
    dist = create_distributor()
    res = api.list_products(ADMIN, params={"distributor_id": dist["id"], "limit": 101})
    validate_error(res, "ERR_VALIDATION_LIMIT")


def test_duplicate_sku_rejected(api):
    """PRD §3.1: "a `sku` unique within the distributor (a clash raising
    `ERR_DUPLICATE_SKU`)."

    Creating a second product with an sku already used in the distributor is rejected
    ERR_DUPLICATE_SKU (409).

    Design: Corner/endpoints/duplicate_sku_rejected
    """
    dist = create_distributor()
    create_product(dist["id"], sku="P-1", name="A", category="DRY")
    res = api.create_product(
        {"distributor_id": dist["id"], "sku": "P-1", "name": "Dup", "category": "DRY",
         "splits_per_case": 6, "case_cost_cents": 800}, ADMIN)
    validate_error(res, "ERR_DUPLICATE_SKU")


def test_duplicate_price_tier_min_cases_rejected(api):
    """PRD §3.1: "A product may not have two tiers with the same `min_cases`; a duplicate is
    rejected with `ERR_DUPLICATE_TIER`."

    Adding a second PriceTier with min_cases already present on the product is rejected
    ERR_DUPLICATE_TIER (409).

    Design: Corner/endpoints/duplicate_price_tier_min_cases_rejected
    """
    dist = create_distributor()
    prod = create_product(dist["id"], sku="P-1", name="A", category="DRY")
    add_price_tier(prod["id"], 1, 2400)
    res = api.create_price_tier(
        {"product_id": prod["id"], "min_cases": 1, "case_price_cents": 2200}, ADMIN)
    validate_error(res, "ERR_DUPLICATE_TIER")


def test_duplicate_warehouse_code_rejected(api):
    """PRD §3.1: "the `code` must be unique within the distributor, and a clash is rejected
    with `ERR_DUPLICATE_CODE`."

    Creating a second warehouse with a code already used in the distributor is rejected
    ERR_DUPLICATE_CODE (409).

    Design: Corner/endpoints/duplicate_warehouse_code_rejected
    """
    dist = create_distributor()
    create_warehouse(dist["id"], code="WH1")
    res = api.create_warehouse(
        {"distributor_id": dist["id"], "code": "WH1", "name": "Dup"}, ADMIN)
    validate_error(res, "ERR_DUPLICATE_CODE")


# ─── Catalog revision counter ──────────────────────────────────────────────

def test_catalog_revision_increments_on_product_and_tier(api):
    """PRD §2.8: "It begins at zero when the distributor is created and increments by one
    whenever a `Product` or a `PriceTier` under that distributor is created or repriced."

    catalog_revision starts 0, becomes 1 after creating a product, and 2 after adding a
    price tier.

    Design: Corner/cross_cutting_complexity_layers/catalog_revision_increments_on_product_and_tier_create
    """
    dist = create_distributor()
    prod = create_product(dist["id"], sku="P-1", name="A", category="DRY")
    add_price_tier(prod["id"], 1, 2400)

    fetched = validate_success(api.get_distributor(dist["id"], ADMIN), 200)
    assert fetched["catalog_revision"] == 2


# ─── RBAC ──────────────────────────────────────────────────────────────────

def test_warehouse_op_cannot_create_product(api):
    """PRD §2.1: "When the headers are present but the declared role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
    PRD §4 endpoint table: POST /products is authorized for DistributorAdmin.

    A WarehouseOp calling POST /products (a DistributorAdmin catalog op) is rejected
    ERR_FORBIDDEN_FOR_ROLE (403).

    Design: Corner/rbac/warehouse_op_cannot_create_product
    """
    dist = create_distributor()
    res = api.create_product(
        {"distributor_id": dist["id"], "sku": "P-1", "name": "A", "category": "DRY",
         "splits_per_case": 12, "case_cost_cents": 1000}, WAREHOUSE)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")


def test_sales_rep_cannot_approve_credit(api):
    """PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."
    PRD §4 endpoint table: POST /orders/{orderId}/approve-credit is authorized for
    CreditManager.

    A SalesRep calling approve-credit (CreditManager-only) on a submitted order is rejected
    ERR_FORBIDDEN_FOR_ROLE (403).

    Design: Corner/rbac/sales_rep_cannot_approve_credit
    """
    from test_helpers import setup_catalog, create_submitted_order, get_customer_version, approve_credit_payload
    cat = setup_catalog(splits_per_case=12, tiers=((1, 2400),),
                        on_hand_splits=24, credit_limit_cents=100000)
    order, _ = create_submitted_order(cat["customer"]["id"], cat["product"]["id"],
                                      lines=[(cat["product"]["id"], "CASE", 1)])
    cust_v = get_customer_version(cat["customer"]["id"])

    res = api.approve_credit(order["id"], approve_credit_payload(cust_v), SALES)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_MISSING_USER_CONTEXT`."

    A request with no X-User-ID / X-User-Role headers is rejected ERR_MISSING_USER_CONTEXT
    (401) before any business logic runs.

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    dist = create_distributor()
    res = api.get_distributor(dist["id"], {})
    validate_error(res, "ERR_MISSING_USER_CONTEXT")
