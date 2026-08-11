"""Role-based access, entity-backed CustomerRep identity, optimistic concurrency on
customer terms, reverse lookups, and the pagination envelope (PRD §2.1, §2.3, §2.7)."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    build_user_headers,
    create_commodity,
    create_customer,
    create_accepted_lot,
    create_ordered_lot,
    create_pending_order,
    file_inspection,
    get_customer,
    get_order,
    get_success_data,
    make_customer_rep_headers,
    patch_customer,
    receive_lot,
    setup_accepted_lot,
    setup_market_day,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    ADMIN_HEADERS,
    INSPECTOR_HEADERS,
    RECEIVER_HEADERS,
    SALES_HEADERS,
)


# --- RBAC denials and the CustomerRep ownership scope -------------------------

def test_salesdesk_cannot_post_daily_price_returns_forbidden(api):
    """PRD §2.1: "If the role is recognized but is not authorized for the endpoint,
    or if a `CustomerRep` attempts to touch a resource owned by another customer, the
    request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "POST | /market/daily-prices | Post the daily price line for a commodity;
    one per (commodity, date) | MarketAdmin"

    Design: Corner/roles/salesdesk_cannot_post_daily_price_returns_forbidden
    """
    commodity = create_commodity(code="TOM", name="Tomato")
    resp = api_client.create_daily_price(
        {"commodity_id": commodity["id"], "market_date": "2026-05-01",
         "low_price": 8.00, "high_price": 12.00}, SALES_HEADERS)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    rows, meta = validate_paginated(
        api_client.list_daily_prices(ADMIN_HEADERS,
                                     params={"commodity_id": commodity["id"]}))
    assert rows == [], "a forbidden post must not persist a price row"


def test_customer_rep_cannot_cancel_other_customers_order(api):
    """PRD §2.1: "If the role is recognized but is not authorized for the endpoint,
    or if a `CustomerRep` attempts to touch a resource owned by another customer, the
    request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.1: "When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id` of the
    acting `Customer`; ownership checks on any resource that references a `Customer`
    (orders, invoices, reverse-lookup listings) compare the resource's `customer_id`
    field to `X-User-ID`, and a mismatch is `ERR_FORBIDDEN`."

    Design: Corner/roles/customer_rep_cannot_cancel_other_customers_order
    """
    base = setup_accepted_lot(defect_pct=0)
    cust_a = create_customer(name="Buyer A", credit_limit_cents=1000000)
    cust_b = create_customer(name="Buyer B", credit_limit_cents=1000000)
    order_b = create_pending_order(cust_b["id"], base["lot"]["id"], quantity=1,
                                   unit_price=10.00)

    resp = api_client.cancel_order(order_b["id"], make_customer_rep_headers(cust_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_order(order_b["id"])["status"] == "PENDING"


def test_customer_rep_own_order_create_and_cancel_allowed(api):
    """PRD §2.1: "A `CustomerRep` may create orders only for their own `customer_id`
    and may cancel only their own orders while those orders are still `PENDING`; the
    shared `SalesDesk` cancel path covers the broader state set."
    PRD §3.6: "Confirming an order is the exclusive province of `SalesDesk`."

    Design: Corner/roles/customer_rep_own_order_create_and_cancel_allowed
    """
    base = setup_accepted_lot(defect_pct=0)
    cust = create_customer(name="Buyer A", credit_limit_cents=1000000)
    rep = make_customer_rep_headers(cust["id"])

    created = api_client.create_sales_order(
        {"customer_id": cust["id"], "delivery_date": "2026-05-02",
         "window_start": "08:00", "window_end": "10:00",
         "lines": [{"lot_id": base["lot"]["id"], "quantity": 1,
                    "unit_price": 10.00}]}, rep)
    order = validate_success(created, 201)
    assert order["status"] == "PENDING"

    denied = api_client.confirm_order(order["id"], rep)
    validate_error(denied, ApiErrorId.ERR_FORBIDDEN)

    cancelled = validate_success(api_client.cancel_order(order["id"], rep), 200)
    assert cancelled["status"] == "CANCELLED"


# --- Authentication (priority 1) ----------------------------------------------

def test_missing_or_undeclared_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, if the role string is not one of the
    declared roles, or — for the entity-backed role below — if the supplied user id
    does not resolve to an existing `Customer`, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/roles/missing_or_undeclared_role_header_returns_unauthenticated
    """
    no_headers = api_client.create_shipper(
        {"name": "No Auth Shipper", "paca_license": "PACA-009"}, headers=None)
    validate_error(no_headers, ApiErrorId.ERR_UNAUTHENTICATED)

    bad_role = api_client.create_shipper(
        {"name": "Bad Role Shipper", "paca_license": "PACA-010"},
        build_user_headers("test-anon-1", "Anonymous"))
    validate_error(bad_role, ApiErrorId.ERR_UNAUTHENTICATED)


def test_customer_rep_with_unknown_id_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, if the role string is not one of the
    declared roles, or — for the entity-backed role below — if the supplied user id
    does not resolve to an existing `Customer`, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/roles/customer_rep_with_unknown_id_returns_unauthenticated
    """
    cust = create_customer(name="Buyer A", credit_limit_cents=1000000)
    resp = api_client.list_customer_sales_orders(
        cust["id"], headers=make_customer_rep_headers(NON_EXISTENT_UUID))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# --- Optimistic concurrency on customer terms (PRD §2.7) -----------------------

def test_customer_patch_with_current_version_succeeds(api):
    """PRD §2.7: "The request must carry `expected_customer_version`, a non-optional
    field holding the `Customer.version` value the caller last observed."
    PRD §2.4: "an integer `version` that starts at 1 and increments by exactly 1 on
    every mutation of that entity, including mutations driven by system cascades"

    Design: Corner/concurrency_rules/customer_patch_with_current_version_succeeds
    """
    cust = create_customer(name="Buyer A", credit_limit_cents=500000)
    assert cust["version"] == 1
    patched = patch_customer(cust["id"], cust["version"], terms_days=14)
    assert patched["terms_days"] == 14
    assert patched["version"] == cust["version"] + 1


def test_customer_patch_with_stale_version_returns_stale_version(api):
    """PRD §2.7: "If the value does not match the server's current `Customer.version`
    — because another writer has advanced the customer since the caller last read it —
    the update is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/concurrency_rules/customer_patch_with_stale_version_returns_stale_version
    """
    cust = create_customer(name="Buyer A", credit_limit_cents=500000)
    patch_customer(cust["id"], cust["version"], terms_days=14)  # version 1 -> 2
    resp = api_client.update_customer(
        cust["id"], {"credit_limit_cents": 600000,
                     "expected_customer_version": cust["version"]}, ADMIN_HEADERS)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    after = get_customer(cust["id"])
    assert after["terms_days"] == 14, "the stale write must not apply"
    assert after["credit_limit_cents"] == 500000
    assert after["version"] == 2


# --- Reverse lookups and the pagination envelope -------------------------------

def test_reverse_lookup_lists_children_by_fk(api):
    """PRD §4: "GET | /market/purchase-lots/{id}/inspections | List inspections of a
    lot"
    PRD §4: "GET | /market/customers/{id}/sales-orders | List orders of a customer"
    PRD §2.2: "The `data` field contains the resource object or an array of resource
    objects."

    Design: Corner/endpoints/reverse_lookup_lists_children_by_fk
    """
    base = setup_market_day()
    lot1 = create_ordered_lot(base["shipper"]["id"], base["commodity"]["id"])
    receive_lot(lot1["id"])
    inspection = file_inspection(lot1["id"], defect_pct=2, result="PASS")
    # A second ACCEPTED lot to host the order (the first stays INSPECTED).
    lot2 = create_accepted_lot(base["shipper"]["id"], base["commodity"]["id"],
                               defect_pct=0)
    cust = create_customer(name="Buyer A", credit_limit_cents=1000000)
    order = create_pending_order(cust["id"], lot2["id"], quantity=1, unit_price=10.00)

    resp_insp = api_client.list_lot_inspections(lot1["id"], RECEIVER_HEADERS)
    assert resp_insp.json()["response_type"] == "array"
    inspections = validate_success(resp_insp, 200)
    assert len(inspections) == 1
    assert inspections[0]["id"] == inspection["id"]

    resp_orders = api_client.list_customer_sales_orders(cust["id"], SALES_HEADERS)
    assert resp_orders.json()["response_type"] == "array"
    orders = validate_success(resp_orders, 200)
    assert len(orders) == 1
    assert orders[0]["id"] == order["id"]


def test_list_pagination_envelope_fields(api):
    """PRD §2.3: "`limit` defaults to 10, with a minimum of 1 and a maximum of 100.
    `offset` defaults to 0. List responses always include `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` block."

    Design: Corner/endpoints/list_pagination_envelope_fields
    """
    base = setup_market_day()
    lot1 = create_ordered_lot(base["shipper"]["id"], base["commodity"]["id"],
                              quantity_units=10)
    lot2 = create_ordered_lot(base["shipper"]["id"], base["commodity"]["id"],
                              quantity_units=10)

    page1, meta1 = validate_paginated(
        api_client.list_purchase_lots(RECEIVER_HEADERS, params={"limit": 1,
                                                                "offset": 0}))
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api_client.list_purchase_lots(RECEIVER_HEADERS, params={"limit": 1,
                                                                "offset": 1}))
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False

    assert {page1[0]["id"], page2[0]["id"]} == {lot1["id"], lot2["id"]}, (
        "the two pages must be disjoint and cover both lots")
