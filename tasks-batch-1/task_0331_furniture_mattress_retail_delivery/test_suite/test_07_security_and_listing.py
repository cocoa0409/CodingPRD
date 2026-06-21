"""Access control (authentication, authorization, ownership) and list endpoints
(pagination envelope and FK filtering).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    get_success_data, build_user_headers, TEST_USERS, make_customer_headers,
    create_customer, create_sofa_product, create_draft_order, add_line, pay_in_full,
    confirm, create_route, book_stop, deliver_order, apply_financing,
    setup_pending_financing_plan, setup_delivered_order,
)

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]
DD = TEST_USERS["dispatcher_headers"]


# ─── Corner: Customer cannot approve financing (403 UNAUTHORIZED) ──────────
def test_customer_cannot_approve_financing(api):
    """PRD 2.1: "When a recognized role attempts an operation it is not permitted to
    perform, the request is rejected with `ERR_UNAUTHORIZED`."

    A Customer calling the StoreManager-exclusive approve endpoint is unauthorized.

    Design: Corner/rbac/customer_cannot_approve_financing_returns_unauthorized
    """
    customer, product, order, line, plan = setup_pending_financing_plan(
        customer_overrides={"credit_score": 760})
    res = api.approve_financing_plan(plan["id"], make_customer_headers(customer["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner: unknown role -> UNAUTHENTICATED (401) ────────────────────────
def test_unknown_role_returns_unauthenticated(api):
    """PRD 2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    ghost = build_user_headers("ghost-1", "GhostRole")
    res = api.create_customer({
        "full_name": "No Role", "email": "norole@x.com", "credit_score": 700,
        "monthly_income_cents": 5000000}, ghost)
    validate_error(res, "ERR_UNAUTHENTICATED")


# ─── Corner: Dispatcher cannot approve a return (403) ─────────────────────
def test_dispatcher_cannot_approve_return(api):
    """PRD 2.1: "A `DeliveryDispatcher` owns routing ... When a recognized role attempts
    an operation it is not permitted to perform, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Approving a return is StoreManager-exclusive; a dispatcher is unauthorized.

    Design: Corner/rbac/dispatcher_cannot_approve_returns_unauthorized
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-03-01T09:00:00Z"}, SM))
    customer, product, order, line, route, stop = setup_delivered_order()
    ret = get_success_data(api.create_return_request(
        {"order_line_id": line["id"], "reason": "DAMAGED"},
        make_customer_headers(customer["id"])))
    res = api.approve_return_request(ret["id"], DD)
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner: Customer files return on another customer's line (403 owner) ──
def test_customer_files_return_on_foreign_line_forbidden(api):
    """PRD 2.1: "when a `Customer` files a return or lists a customer's orders or
    financing plans, the system verifies that the targeted customer (directly, or
    transitively via the order line's order) is the one identified by `X-User-ID`; a
    mismatch is rejected with `ERR_FORBIDDEN_NOT_OWNER`."

    Design: Corner/rbac/customer_files_return_on_other_customers_line_forbidden
    """
    get_success_data(api.set_clock({"to_iso8601": "2026-03-01T09:00:00Z"}, SM))
    cust_a, product, order, line, route, stop = setup_delivered_order()
    cust_b = create_customer(email="custb@x.com")
    res = api.create_return_request(
        {"order_line_id": line["id"], "reason": "DAMAGED"},
        make_customer_headers(cust_b["id"]))  # B acts on A's line
    validate_error(res, "ERR_FORBIDDEN_NOT_OWNER")


# ─── Corner: list orders pagination envelope ──────────────────────────────
def test_list_orders_pagination_envelope(api):
    """PRD 2.3: "The meta object of every list response carries limit, offset,
    total_count, and has_more."
    PRD 2.2: "The response_type is either "object" for a single resource or "array" for
    a list of resources."

    Design: Corner/endpoints/list_orders_pagination_envelope
    """
    customer = create_customer()
    create_draft_order(customer["id"])
    data, meta = validate_paginated(api.list_orders(SA))
    assert isinstance(data, list)
    assert "total_count" in meta and "has_more" in meta
    assert meta["limit"] == 10, "limit defaults to 10"


def test_list_orders_default_limit_caps_results(api):
    """PRD 2.3: "The limit parameter caps the number of items returned; when omitted it
    defaults to 10 ..."

    Second test for this instance: with 11 orders, the default page returns 10 and
    signals has_more.

    Design: Corner/endpoints/list_orders_pagination_envelope
    """
    customer = create_customer()
    for _ in range(11):
        create_draft_order(customer["id"])
    data, meta = validate_paginated(api.list_orders(SA))
    assert len(data) == 10, "default limit caps the page at 10"
    assert meta["has_more"] is True
    assert meta["total_count"] >= 11


# ─── Corner: filter orders by customer_id ─────────────────────────────────
def test_filter_orders_by_customer_id(api):
    """PRD 4 (endpoint table): "GET /orders | List orders, filterable by customer_id".
    PRD 3.1: "A sale begins when a SalesAssociate creates an Order for a customer,
    supplying the buyer's customer_id ..."

    Only customer A's orders come back when filtering by A's id.

    Design: Corner/endpoints/filter_orders_by_customer_id
    """
    cust_a = create_customer(email="a@x.com")
    cust_b = create_customer(email="b@x.com")
    create_draft_order(cust_a["id"])
    create_draft_order(cust_b["id"])
    data, meta = validate_paginated(api.list_orders(SA, params={"customer_id": cust_a["id"]}))
    assert len(data) >= 1
    for o in data:
        assert o["customer_id"] == cust_a["id"], "filtered list is scoped to customer A"
