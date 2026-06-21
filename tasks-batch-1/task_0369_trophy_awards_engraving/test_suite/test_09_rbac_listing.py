"""RBAC denials, listing/pagination, reorder, config validation — breadth coverage (queue B)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    make_customer_headers,
    make_staff_headers,
    make_manager_headers,
    fixtures,
    factories,
)

STAFF = make_staff_headers()
MANAGER = make_manager_headers()


# ─── RBAC ─────────────────────────────────────────────
def test_staff_cannot_confirm_order(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the `POST /orders/{id}/confirm` endpoint is authorized for the `Customer` role.

    Design: Corner/rbac/staff_cannot_confirm_order
    """
    ctx = fixtures.setup_priced_order(
        product_overrides={"base_price_cents": 4000, "standard_lead_days": 3}, on_hand_qty=10
    )
    order, cust_obj = ctx["order"], ctx["customer"]
    cust = make_customer_headers(cust_obj["id"])
    resp = api.confirm_order(order["id"], {"expected_order_version": order["version"]}, STAFF)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["production_status"] == "PRICED"


def test_customer_cannot_create_catalog_product(api):
    """PRD §2.1: "When the headers are well-formed but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the `POST /catalog-products` endpoint is authorized for the `ShopManager` role.

    Design: Corner/rbac/customer_cannot_create_catalog_product
    """
    component = fixtures.create_component(on_hand_qty=10)
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    payload = factories.create_catalog_product_payload(_component_id=component["id"])
    resp = api.create_catalog_product(payload, cust)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_customer_cannot_act_on_other_customers_order(api):
    """PRD §2.1: "Ownership is enforced on every order a customer touches: the order's
    `customer_id` must equal the caller's `X-User-ID`, and a customer attempting to read or
    drive an order it does not own is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/customer_cannot_act_on_other_customers_order
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="EP-35", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    cust_a = fixtures.register_customer()
    cust_b = fixtures.register_customer()
    headers_a = make_customer_headers(cust_a["id"])
    headers_b = make_customer_headers(cust_b["id"])
    order = fixtures.create_order(cust_a)
    line = fixtures.add_line(order, cust_a, product["id"], quantity=1)
    fixtures.add_approved_proof(line, cust_a, content_ref="X")
    priced = fixtures.price(order, cust_a)
    # Customer B (different X-User-ID) attempts to confirm A's order.
    resp = api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, headers_b)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
    reread = validate_success(api.get_order(order["id"], headers_a))
    assert reread["production_status"] == "PRICED"


def test_missing_headers_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing on a protected endpoint, or if `X-User-Role`
    names a role the system does not recognize, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_headers_returns_unauthenticated
    """
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer)
    # Protected GET with NO auth headers at all.
    resp = api._request("GET", f"/orders/{order['id']}", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─── Config validation ────────────────────────────────
def test_promo_percent_without_percent_off_returns_validation(api):
    """PRD §3.1: "a well-typed but semantically invalid value here — a percent outside that
    range, a `PERCENT` code with no `percent_off`, or a `FLAT` code with no `flat_off_cents`
    — is rejected with `ERR_VALIDATION`."

    Design: Corner/validations/promo_percent_without_percent_off_returns_validation
    """
    payload = {"code": "BADPCT", "kind": "PERCENT", "min_subtotal_cents": 0, "active": True}
    resp = api.create_promo_code(payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_add_line_inactive_product_returns_product_inactive(api):
    """PRD §3.2: "The referenced product must be active at the moment the line is created;
    adding a line for a product whose `active` is false is rejected with
    `ERR_PRODUCT_INACTIVE`."

    Design: Corner/validations/add_line_inactive_product_returns_product_inactive
    """
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="EP-24", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=3, active=True,
    )
    validate_success(api.update_catalog_product(product["id"], {"active": False}, MANAGER))
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order = fixtures.create_order(customer)
    resp = api.add_line(order["id"], factories.create_line_payload(product["id"], quantity=1), cust)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_INACTIVE.value)


def test_rush_policy_create_active_deactivates_prior(api):
    """PRD §3.1: "Exactly one rush policy may be active at a time: when a policy is created
    with `active` set to true, any other currently active policy is set inactive, and the
    pricing engine always reads the single active policy."

    Design: Corner/state_machines/rush_policy_create_active_deactivates_prior
    """
    p1 = fixtures.create_active_rush_policy(name="P1", expedited_surcharge_pct=0.20,
                                            rush_surcharge_pct=0.40)
    p2 = fixtures.create_active_rush_policy(name="P2", expedited_surcharge_pct=0.25,
                                            rush_surcharge_pct=0.50)
    p1_reread = validate_success(api.get_rush_policy(p1["id"], STAFF))
    p2_reread = validate_success(api.get_rush_policy(p2["id"], STAFF))
    assert p1_reread["active"] is False
    assert p2_reread["active"] is True


def test_new_order_initial_state_is_draft_unpaid(api):
    """PRD §3.2: "A new order begins in `production_status` `DRAFT` and `payment_status`
    `UNPAID`, with `version` 1 and every computed total at its default."

    Design: Corner/state_machines/new_order_initial_state_is_draft_unpaid
    """
    customer = fixtures.register_customer()
    order = validate_success(
        api.create_order(factories.create_order_payload(customer["id"]),
                         make_customer_headers(customer["id"])), 201
    )
    assert order["production_status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"


# ─── Listing / pagination ─────────────────────────────
def test_list_customer_orders_paginated(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in its `meta` block, where `total_count` is the total number of records
    matching the query before pagination and `has_more` indicates whether records remain
    beyond the current page."

    Design: Corner/endpoints/list_customer_orders_paginated
    """
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    fixtures.create_order(customer)
    fixtures.create_order(customer, due_date="2026-07-16T00:00:00Z")
    resp = api.list_customer_orders(customer["id"], cust)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert len(data) == 2


def test_list_order_lines_reverse_reachability(api):
    """PRD §3.10: "and may page through collections: a customer's orders, an order's lines,
    an order's proofs, an order's payments, an order's fulfillments, and a line's component
    allocations."

    Design: Corner/endpoints/list_order_lines_reverse_reachability
    """
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="EP-30", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    order = fixtures.create_order(customer)
    line = fixtures.add_line(order, customer, product["id"], quantity=1)
    resp = api.list_order_lines_of_order(order["id"], cust)
    data, _meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == line["id"]


def test_list_component_allocations_filtered_by_component(api):
    """PRD §3.10: "Component allocations may also be listed across the system and filtered by
    `component_id` or `order_line_id`".
    PRD §3.5: "Confirmation also creates the material reservations: one `ComponentAllocation`
    in `alloc_status` `RESERVED` is created for each (line, bom-component) pair, with its
    `qty` equal to the component's `qty_per_unit` multiplied by the line's `quantity`".

    Design: Corner/endpoints/list_component_allocations_filtered_by_component
    """
    ctx = fixtures.setup_confirmed_order(
        product_overrides={"base_price_cents": 4000, "standard_lead_days": 3}, on_hand_qty=10
    )
    component = ctx["component"]
    resp = api.list_component_allocations(STAFF, params={"component_id": component["id"]})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["alloc_status"] == "RESERVED"
    assert data[0]["qty"] == 1


# ─── Reorder ──────────────────────────────────────────
def test_reorder_clones_lines_into_new_draft(api):
    """PRD §3.9: "A successful reorder creates a brand-new order in `DRAFT` whose
    `reorder_source_order_id` points back at the source, copying the source's lines and
    their `engraving_text` but **not** copying any proofs — the clone must be proofed and
    approved afresh."

    Design: Corner/endpoints/reorder_clones_lines_into_new_draft
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="EP-32", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    src = fixtures.create_order(customer)
    fixtures.add_line(src, customer, product["id"], quantity=3, engraving_text="TEAM")
    src_reread = validate_success(api.get_order(src["id"], cust))
    resp = api.reorder(
        src["id"], {"expected_order_version": src_reread["version"], "due_date": "2026-08-01T00:00:00Z"}, cust
    )
    new_order = validate_success(resp, 201)
    assert new_order["reorder_source_order_id"] == src["id"]
    assert new_order["production_status"] == "DRAFT"
    assert new_order["line_count"] == 1


def test_reorder_stale_source_returns_stale_version(api):
    """PRD §2.8: "The reorder request must carry `expected_order_version` equal to the
    **source** order's current `version`; if the source has been edited, re-priced, or
    otherwise advanced since the caller last read it, the reorder is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/reorder_stale_source_returns_stale_version
    """
    fixtures.set_clock()
    component = fixtures.create_component(on_hand_qty=20)
    product = fixtures.create_product(
        component["id"], sku="EP-41", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=3,
    )
    customer = fixtures.register_customer()
    cust = make_customer_headers(customer["id"])
    src = fixtures.create_order(customer)
    fixtures.add_line(src, customer, product["id"], quantity=1, engraving_text="ONE")
    src_reread = validate_success(api.get_order(src["id"], cust))
    stale_version = src_reread["version"]
    # Add a second line -> source version advances, making the captured version stale.
    fixtures.add_line(src, customer, product["id"], quantity=1, engraving_text="TWO")
    resp = api.reorder(src["id"], {"expected_order_version": stale_version}, cust)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    final = validate_success(api.get_order(src["id"], cust))
    assert final["production_status"] == "DRAFT"
    assert final["line_count"] == 2
