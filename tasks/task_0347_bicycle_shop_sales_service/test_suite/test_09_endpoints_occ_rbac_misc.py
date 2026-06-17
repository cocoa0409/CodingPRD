"""Endpoint, OCC, RBAC, cross-cutting, and consistency corner tests
(PRD §2.1, §2.6, §2.7, §3.1, §3.5, §3.6).

Queue B — corner sections: endpoints, errors, rbac,
cross_cutting_complexity_layers, consistency_model.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    create_customer, create_sku, create_order, add_order_line, get_sku,
    create_reserved_order,
    restock_payload, create_sku_payload, reserve_payload,
    create_order_line_payload, create_layaway_plan_payload,
    create_sales_order_payload,
    make_customer_headers, TEST_USERS, build_user_headers,
)

MGR = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]
ADV = TEST_USERS["service_advisor_headers"]


# ─── Endpoints ──────────────────────────────────────────────────────────────
def test_restock_increases_on_hand_and_version():
    """PRD §3.1: "a restock supplies a count of `units` to add to `on_hand`,
    bumps the `Sku`'s `version`, and re-reconciles availability."

    Restocking units=5 on a Sku at on_hand 2 / version 1 yields on_hand 7 and
    version 2.

    Design: Corner/endpoints/restock_increases_on_hand_and_version
    """
    sku = create_sku(name="Restock Sku", category="PART", list_price_cents=1000, on_hand=2)
    assert sku["version"] == 1
    restocked = validate_success(api_client.restock_sku(sku["id"], restock_payload(5), MGR), 200)
    assert restocked["on_hand"] == 7
    assert restocked["version"] == 2


def test_reservations_subresource_lists_active_reservation():
    """PRD §2.6: "Reservations are never created directly through their own
    endpoint; they come into being only as side effects of holder transitions,
    and they are read back through the reservation list and the per-`Sku`
    reservation listing."

    After a reserve, GET /shop/skus/{id}/reservations returns the ACTIVE
    reservation as an array of total_count 1.

    Design: Corner/endpoints/reservations_subresource_lists_active_reservation
    """
    cust = create_customer()
    sku = create_sku(name="Listed Sku", category="PART", list_price_cents=2000, on_hand=4)
    create_reserved_order(sku["id"], qty=1, customer_id=cust["id"])
    data, meta = validate_paginated(
        api_client.list_sku_reservations(sku["id"], SA, params={"status": "ACTIVE"}))
    assert meta["total_count"] == 1
    assert len(data) == 1


# ─── Errors — OCC stale version ─────────────────────────────────────────────
def test_stale_sku_version_on_reserve():
    """PRD §2.7: "Reserving stock for a sales order requires the caller to submit
    `expected_sku_version` ... If that value does not equal the `Sku`'s current
    `version` ... the reserve is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Order B reserving with the pre-reserve version (after order A's reserve
    bumped Sku.version) is rejected with ERR_STALE_VERSION.

    Design: Corner/errors/stale_sku_version_on_reserve
    """
    cust = create_customer()
    sku = create_sku(name="Contended Sku", category="PART", list_price_cents=3000, on_hand=10)
    v0 = sku["version"]
    orderA = create_order(cust["id"])
    add_order_line(orderA["id"], sku["id"], 1)
    validate_success(api_client.reserve_sales_order(orderA["id"], reserve_payload(v0), SA), 200)
    orderB = create_order(cust["id"])
    add_order_line(orderB["id"], sku["id"], 1)
    res = api_client.reserve_sales_order(orderB["id"], reserve_payload(v0), SA)
    validate_error(res, "ERR_STALE_VERSION")


def test_stale_sku_version_on_layaway_open():
    """PRD §2.7: "Opening a layaway plan likewise requires `expected_sku_version`
    matching the target `Sku`'s current `version`; a layaway immediately reserves
    a unit, so an advanced version means the availability the client saw is stale
    and the open is refused with `ERR_STALE_VERSION` (HTTP 412)."

    Opening a layaway with a pre-reserve version (after a reserve bumped it) is
    rejected with ERR_STALE_VERSION.

    Design: Corner/errors/stale_sku_version_on_layaway_open
    """
    cust = create_customer()
    sku = create_sku(name="Lay Contended", category="BIKE", list_price_cents=40000, on_hand=5)
    v0 = sku["version"]
    orderA = create_order(cust["id"])
    add_order_line(orderA["id"], sku["id"], 1)
    validate_success(api_client.reserve_sales_order(orderA["id"], reserve_payload(v0), SA), 200)
    res = api_client.create_layaway_plan(
        create_layaway_plan_payload(cust["id"], sku["id"], v0, 1), SA)
    validate_error(res, "ERR_STALE_VERSION")


# ─── RBAC ───────────────────────────────────────────────────────────────────
def test_sales_associate_cannot_create_sku():
    """PRD §3.1: "Only a `ShopManager` creates stock-keeping units".
    PRD §2.1: "When an authenticated caller invokes an endpoint their role is not
    permitted to use, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    A SalesAssociate calling POST /shop/skus returns ERR_FORBIDDEN_ROLE (403).

    Design: Corner/rbac/sales_associate_cannot_create_sku
    """
    res = api_client.create_sku(
        create_sku_payload(name="Sneaky Sku", category="PART", list_price_cents=1000), SA)
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_customer_cannot_approve_other_customers_ticket():
    """PRD §2.1: "When a `Customer` approves a ticket, the acting `X-User-ID`
    must equal that ticket's `customer_id`; if it does not, the request is
    rejected with `ERR_NOT_RESOURCE_OWNER`."

    A Customer whose X-User-ID != the ticket's customer_id is rejected with
    ERR_NOT_RESOURCE_OWNER on approve.

    Design: Corner/rbac/customer_cannot_approve_other_customers_ticket
    """
    from test_helpers import create_tier, create_ticket
    owner = create_customer()
    intruder = create_customer()
    tier = create_tier(code="BASIC", base_labor_cents=8000, turnaround_hours=5)
    ticket = create_ticket(owner["id"], tier["id"])
    validate_success(api_client.quote_service_ticket(ticket["id"], ADV), 200)
    res = api_client.approve_service_ticket(ticket["id"], make_customer_headers(intruder["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER")


def test_missing_auth_headers_unauthenticated():
    """PRD §2.1: "Every request must carry two mandatory HTTP headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their
    operational capacity. If either header is missing, or if `X-User-Role` is not
    one of the recognized role names, the request is rejected with
    `ERR_UNAUTHENTICATED`."

    A request with no auth headers returns ERR_UNAUTHENTICATED (401).

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    res = api_client.list_skus({})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_shop_manager_override_can_create_sales_order():
    """PRD §2.1: "`ShopManager` is a hierarchical override role: in addition to
    its exclusive catalog, recall, trade-in, and forfeit powers, a `ShopManager`
    may perform any operation a `SalesAssociate` may perform."

    A ShopManager creating a sales order (a SalesAssociate-shared operation)
    succeeds with 201, PENDING|UNPAID.

    Design: Corner/rbac/shop_manager_override_can_create_sales_order
    """
    cust = create_customer()
    order = validate_success(api_client.create_sales_order(
        create_sales_order_payload(cust["id"]), MGR), 201)
    assert order["fulfillment_status"] == "PENDING"
    assert order["payment_status"] == "UNPAID"


# ─── Cross-cutting complexity layers ────────────────────────────────────────
def test_occ_correct_version_reserve_succeeds_and_bumps():
    """PRD §2.7: "on success the reserve increments that `Sku`'s `version`."
    PRD §3.5: "On success it creates one `ACTIVE` reservation per order line ...
    raises each `Sku`'s `reserved`, increments the primary `Sku`'s `version`".

    Reserving with the correct expected_sku_version succeeds, bumping Sku.version
    1 -> 2 and raising reserved to 1.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_reserve_succeeds_and_bumps
    """
    cust = create_customer()
    sku = create_sku(name="OCC Sku", category="PART", list_price_cents=3000, on_hand=5)
    assert sku["version"] == 1
    order = create_order(cust["id"])
    add_order_line(order["id"], sku["id"], 1)
    validate_success(api_client.reserve_sales_order(order["id"], reserve_payload(sku["version"]), SA), 200)
    sku_after = validate_success(api_client.get_sku(sku["id"], MGR), 200)
    assert sku_after["version"] == 2
    assert sku_after["reserved"] == 1


def test_derived_reserved_field_reconciled_from_active_reservations():
    """PRD §2.6: "The `reserved` count is the sum of the `qty` of every
    `Reservation` row that points at this `Sku` and is currently in `ACTIVE`
    status; `Reservation` rows in `COMMITTED` or `RELEASED` status contribute
    nothing."

    After reserving qty 2, the Sku's derived reserved count is 2.

    Design: Corner/cross_cutting_complexity_layers/derived_reserved_field_reconciled_after_release
    """
    cust = create_customer()
    sku = create_sku(name="Recon Sku", category="PART", list_price_cents=2000, on_hand=8)
    create_reserved_order(sku["id"], qty=2, customer_id=cust["id"])
    sku_after = validate_success(api_client.get_sku(sku["id"], MGR), 200)
    assert sku_after["reserved"] == 2


# ─── Consistency model ──────────────────────────────────────────────────────
def test_deliver_response_shows_updated_totals_immediately():
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.5: "Delivering the order advances fulfillment from `RESERVED` to
    `DELIVERED`."

    The deliver response itself shows fulfillment_status=DELIVERED and final
    totals (subtotal 5000, no store credit) without any re-read.

    Design: Corner/consistency_model/deliver_response_shows_updated_totals_immediately
    """
    from test_helpers import pay_order
    cust = create_customer()
    sku = create_sku(name="Imm Sku", category="ACCESSORY", list_price_cents=5000, on_hand=3)
    cust2, order, line = create_reserved_order(sku["id"], qty=1, customer_id=cust["id"])
    pay_order(order["id"], order["subtotal_cents"])
    delivered = validate_success(api_client.deliver_sales_order(order["id"], SA), 200)
    assert delivered["fulfillment_status"] == "DELIVERED"
    assert delivered["total_due_cents"] == 5000
    assert delivered["store_credit_applied_cents"] == 0
