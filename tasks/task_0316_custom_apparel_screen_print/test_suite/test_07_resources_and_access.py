"""Resource-lifecycle and access-control tests: shop-default creation, not-found,
input-body validation, customer soft-delete listing, customer-filtered order listing,
RBAC role denials, missing user-context, and entity-backed ownership denial.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    setup_shop_catalog,
    create_shop,
    create_draft_order,
    add_line,
    create_proof,
    submit_proof,
    create_customer,
    api_client,
    TEST_USERS,
    make_customer_headers,
    build_user_headers,
)

SM = TEST_USERS["shop_manager_headers"]
ART = TEST_USERS["art_staff_headers"]
NON_EXISTENT = "00000000-0000-0000-0000-000000000000"


# ═══════════════════════════════════════════════════════════════════════════
# entities (corner) — shop defaults at creation
# ═══════════════════════════════════════════════════════════════════════════

def test_create_shop_applies_documented_defaults(api):
    """PRD §3.1: "the misprint `spoilage_pct` (default five hundredths, i.e. 0.05), the
    `rush_threshold_days` window (default 7), and the `rush_surcharge_pct` (default one
    quarter, i.e. 0.25)."

    Design: Corner/entities/create_shop_returns_201_with_defaults
    """
    res = api.create_shop({"name": "Ink Co"}, SM)
    shop = validate_success(res, 201)
    assert shop["spoilage_pct"] == 0.05
    assert shop["rush_threshold_days"] == 7
    assert shop["rush_surcharge_pct"] == 0.25


# ═══════════════════════════════════════════════════════════════════════════
# entities (corner) — not found
# ═══════════════════════════════════════════════════════════════════════════

def test_get_nonexistent_order_returns_not_found(api):
    """PRD §2.5: "the server validates them left to right and rejects the request with
    `ERR_NOT_FOUND` at the *first* identifier that does not resolve to an existing
    resource within the shop."

    Design: Corner/entities/get_order_nonexistent_returns_not_found
    """
    create_shop()
    res = api.get_order(NON_EXISTENT, SM)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ═══════════════════════════════════════════════════════════════════════════
# entities (corner) — input body validation
# ═══════════════════════════════════════════════════════════════════════════

def test_create_line_missing_size_run_rejected(api):
    """PRD §3.3: "a `size_run` — a map from size to quantity such as `{S: 10, M: 30,
    L: 20}`. Every key in `size_run` must be one of the style's `available_sizes` and
    every value must be a positive integer; an empty `size_run` or any non-positive
    quantity is rejected as a malformed body."

    Design: Corner/entities/create_order_line_missing_required_size_run
    """
    cat = setup_shop_catalog(stock_qty=100)
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    res = api.create_line(
        order["id"],
        {"garment_style_id": cat["style"]["id"], "decoration_method_id": cat["method"]["id"],
         "color": "BLACK", "num_locations": 1, "num_colors": 1},  # no size_run
        SM,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_line_color_not_in_catalog_rejected(api):
    """PRD §3.3: "A line names its `garment_style_id`, its `decoration_method_id`, a
    `color` drawn from the style's `available_colors`".
    PRD §2.10: "the request body must be well-formed — valid enum members,
    positive-integer quantities, a non-empty `size_run`, and colors and sizes drawn from
    the style's catalog — else `ERR_INVALID_REQUEST`".

    Design: Corner/entities/create_order_line_color_not_in_catalog
    """
    cat = setup_shop_catalog(stock_qty=100)  # available_colors [BLACK]
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    res = api.create_line(
        order["id"],
        {"garment_style_id": cat["style"]["id"], "decoration_method_id": cat["method"]["id"],
         "color": "RED", "num_locations": 1, "num_colors": 1, "size_run": {"L": 10}},
        SM,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_line_empty_size_run_rejected(api):
    """PRD §3.3: "an empty `size_run` or any non-positive quantity is rejected as a
    malformed body."

    Design: Corner/entities/order_line_empty_size_run_zero_qty
    """
    cat = setup_shop_catalog(stock_qty=100)
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    res = api.create_line(
        order["id"],
        {"garment_style_id": cat["style"]["id"], "decoration_method_id": cat["method"]["id"],
         "color": "BLACK", "num_locations": 1, "num_colors": 1, "size_run": {}},
        SM,
    )
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


# ═══════════════════════════════════════════════════════════════════════════
# entities (corner) — soft-delete listing
# ═══════════════════════════════════════════════════════════════════════════

def test_archived_customer_excluded_from_default_list(api):
    """PRD §3.1: "Archiving a customer is a soft delete — it sets `archived` to true,
    after which the customer is excluded from default list results unless a caller
    explicitly passes `include_archived` to surface them."

    Design: Corner/entities/customer_soft_delete_excluded_from_list
    """
    shop = create_shop()
    create_customer(shop["id"], name="Acme", email="a@x.com")
    beta = create_customer(shop["id"], name="Beta", email="b@x.com")
    archived = validate_success(api.archive_customer(beta["id"], SM), 200)
    assert archived["archived"] is True

    data, meta = validate_paginated(api.list_customers(SM, params={"shop_id": shop["id"]}))
    assert meta["total_count"] == 1

    data_all, meta_all = validate_paginated(
        api.list_customers(SM, params={"shop_id": shop["id"], "include_archived": "true"})
    )
    assert meta_all["total_count"] == 2


# ═══════════════════════════════════════════════════════════════════════════
# endpoints (corner) — order list filtered by customer
# ═══════════════════════════════════════════════════════════════════════════

def test_list_orders_filtered_by_customer(api):
    """PRD §2.5: "lines, proofs, reservations, and production runs can be narrowed by
    their parent `order_id`".
    PRD §2.3: "Each list response carries the pagination bookkeeping inside the `meta`
    object: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_orders_filtered_by_customer
    """
    cat = setup_shop_catalog(with_sku=False)
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    data, meta = validate_paginated(
        api.list_orders(SM, params={"customer_id": cat["customer"]["id"]})
    )
    assert meta["total_count"] == 1
    assert data[0]["customer_id"] == cat["customer"]["id"]


# ═══════════════════════════════════════════════════════════════════════════
# rbac (corner) — role denials
# ═══════════════════════════════════════════════════════════════════════════

def test_customer_cannot_confirm_order(api):
    """PRD §4 endpoint table: confirm is authorized for ShopManager only.
    PRD §2.1: "When a role is syntactically valid but not permitted to perform the
    requested operation ... the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/customer_cannot_confirm_order
    """
    cat = setup_shop_catalog(stock_qty=100)
    cust_headers = make_customer_headers(cat["customer"]["id"])
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"], actor=cust_headers)
    order_v = order["version"]
    add_line(order["id"], cat["style"]["id"], cat["method"]["id"], {"L": 30}, actor=cust_headers)
    proof = create_proof(order["id"])
    submit_proof(order["id"], proof["id"])
    from test_helpers import approve_proof
    approve_proof(order["id"], proof["id"], cat["customer"]["id"], order_v)

    res = api.confirm_order(order["id"], cust_headers)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


def test_artstaff_cannot_approve_proof(api):
    """PRD §4 endpoint table: approve a proof is authorized for Customer only.
    PRD §2.1: "When a role is syntactically valid but not permitted to perform the
    requested operation ... the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/artstaff_cannot_approve_proof
    """
    cat = setup_shop_catalog(with_sku=False)
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    order_v = order["version"]
    proof = create_proof(order["id"])
    submit_proof(order["id"], proof["id"])
    res = api.approve_proof(order["id"], proof["id"], {"expected_order_version": order_v}, ART)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "A request missing or malforming either header is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    shop = create_shop()
    res = api.get_shop(shop["id"], headers={"Content-Type": "application/json"})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT", expected_status=400)


def test_customer_cannot_act_on_another_customers_order(api):
    """PRD §2.1: "A `Customer` may therefore act only on orders whose `customer_id`
    equals their own `X-User-ID`, and any attempt to approve a proof, request changes,
    pay an invoice, or cancel another customer's order is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/customer_cannot_act_on_another_customers_order
    """
    shop = create_shop()
    cust_a = create_customer(shop["id"], name="Acme", email="a@x.com")
    cust_b = create_customer(shop["id"], name="Beta", email="b@x.com")
    order = create_draft_order(shop["id"], cust_a["id"])
    proof = create_proof(order["id"])
    submit_proof(order["id"], proof["id"])
    # Customer B (not the owner) requests changes on Customer A's proof.
    res = api.request_changes_proof(order["id"], proof["id"], make_customer_headers(cust_b["id"]))
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE", expected_status=403)
