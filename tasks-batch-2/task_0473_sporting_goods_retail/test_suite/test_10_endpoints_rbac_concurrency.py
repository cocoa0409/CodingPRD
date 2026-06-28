"""Endpoints, error existence-precedence, RBAC, OCC concurrency, derived-field
reconciliation, and consistency.

Corner queue: endpoints, errors, rbac, cross_cutting_complexity_layers,
consistency_model sections. The cross-cutting stub
occ_order_fulfill_stale_after_pricematch_approve is excluded_because its assertion
is owned by the difficulty instance
dual_variant_calc/order_provisional_vs_final_pricematch_divergence (translated in
test_01) — no separate test is emitted for the stub.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    build_user_headers,
    NON_EXISTENT_UUID,
    create_store,
    create_sku,
    create_customer,
    create_inventory_row,
    stock_sku,
    create_draft_order,
    add_order_line,
    place_order,
    setup_placed_order,
    setup_ready_order,
    fulfill_order,
    make_customer_headers,
    create_sku_payload,
    create_order_payload,
    receive_payload,
    fulfill_payload,
    create_fishing_license_payload,
    get_order,
    get_inventory,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]


# ===========================================================================
# endpoints section
# ===========================================================================
def test_list_skus_returns_paginated_array(api):
    """PRD §2.3: "Every list-based response includes the following fields in the
    `meta` object: `limit`, `offset`, `total_count`, and `has_more`."

    With two SKUs and limit 1, total_count is 2 and has_more is true.

    Design: Corner/endpoints/list_skus_pagination_envelope
    """
    get_success_data(api.create_sku(
        create_sku_payload(sport="HOCKEY", name="S1", base_price_cents=1000, size_label="NA"),
        ADMIN))
    get_success_data(api.create_sku(
        create_sku_payload(sport="HOCKEY", name="S2", base_price_cents=2000, size_label="NA"),
        ADMIN))

    data, meta = validate_paginated(api.list_skus(ADMIN, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_receive_stock_increments_on_hand_and_version(api):
    """PRD §3.1: "On success the row's `on_hand_qty` rises by `quantity`,
    `available_qty` is recomputed, and the row's `version` increments by one."

    A fresh row (version 1, on_hand 0) receiving 7 reaches on_hand 7, available 7,
    version 2.

    Design: Corner/endpoints/receive_stock_increments_on_hand_and_version
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="FOOTWEAR", name="Boot", base_price_cents=7000, size_label="11D")
    row = create_inventory_row(store["id"], sku["id"])
    assert row["version"] == 1
    assert row["on_hand_qty"] == 0

    received = get_success_data(api.receive_store_inventory(
        row["id"], receive_payload(7, row["version"]), ADMIN
    ))
    assert received["on_hand_qty"] == 7
    assert received["available_qty"] == 7
    assert received["version"] == 2


# ===========================================================================
# errors section
# ===========================================================================
def test_issue_license_against_missing_store_returns_not_found(api):
    """PRD §2.9: "All path identifiers and all foreign-key references in the body are
    validated for existence in left-to-right order; the first identifier that does
    not resolve to an existing resource causes the request to be rejected with
    `ERR_NOT_FOUND` before any later identifier is examined."

    A non-existent issuing_store_id fails existence (P4) before any jurisdiction
    business check (P10).

    Design: Corner/errors/invalid_jurisdiction_license_against_missing_store
    """
    customer = create_customer(home_state_code="CA")
    res = api.create_fishing_license(
        create_fishing_license_payload(customer["id"], NON_EXISTENT_UUID), ASSOCIATE
    )
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


# ===========================================================================
# rbac section
# ===========================================================================
def test_customer_cannot_fulfill_order_forbidden(api):
    """PRD §2.1: "When a recognized role attempts an operation it is not permitted to
    perform, the request is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD endpoints: POST `/orders/{id}/fulfill` is authorized for StoreAssociate.

    A Customer calling fulfill (StoreAssociate-exclusive) is forbidden.

    Design: Corner/rbac/customer_cannot_fulfill_order_forbidden
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Glove2", base_price_cents=3000, size_label="M")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    ready, _ = setup_ready_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    current = get_order(ready["id"])
    res = api.fulfill_order(
        ready["id"], fulfill_payload(current["version"]),
        make_customer_headers(customer["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_customer_cannot_place_other_customers_order(api):
    """PRD §2.1: "A `Customer` placing or cancelling an order, submitting a
    price-match claim on its own order, or submitting a team order it owns must be
    the owning customer; if not, the request is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Customer B placing customer A's order (X-User-ID != Order.customer_id) is
    rejected with ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/customer_cannot_place_other_customers_order_not_owner
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Glove3", base_price_cents=3000, size_label="M")
    cust_a = create_customer(email="ca_owner@x.com", home_state_code="CA")
    cust_b = create_customer(email="cb_other@x.com", home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    order = create_draft_order(cust_a["id"], store["id"])
    add_order_line(order["id"], cust_a["id"], sku["id"], 1)

    res = api.place_order(order["id"], make_customer_headers(cust_b["id"]))
    validate_error(res, "ERR_NOT_RESOURCE_OWNER", expected_status=403)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two mandatory HTTP headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming their operational
    capacity. A request missing either header, or carrying an unrecognized role, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_header_unauthenticated
    """
    store = create_store(state_code="CA")
    customer = create_customer(home_state_code="CA")
    res = api.create_order(
        create_order_payload(customer["id"], store["id"], "BOPIS"), {}
    )
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


# ===========================================================================
# cross_cutting_complexity_layers section
# ===========================================================================
def test_inventory_receive_stale_version_rejected(api):
    """PRD §2.6: "Receiving stock must carry `expected_store_inventory_version`
    matching the target stock row's current `version`."
    PRD §2.6: "If a reservation (an order placement or a service start) has advanced
    the row's `version` since the operator last read it — changing its `reserved_qty`
    and `available_qty` — the receive is rejected with `ERR_STALE_INVENTORY_VERSION`
    (HTTP 412), because the operator's on-hand baseline is stale."

    Row received to qty 5 (version 2); an order place bumps the row's version past
    2; a receive carrying the now-stale version 2 is rejected.

    Design: Corner/cross_cutting_complexity_layers/occ_inventory_receive_stale_version_rejected
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="FOOTWEAR", name="Cleat", base_price_cents=6000, size_label="10D")
    customer = create_customer(home_state_code="CA")
    row = create_inventory_row(store["id"], sku["id"])
    received = get_success_data(api.receive_store_inventory(
        row["id"], receive_payload(5, row["version"]), ADMIN
    ))
    stale_version = received["version"]  # version 2, before the place bumps it

    setup_placed_order(customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}])

    res = api.receive_store_inventory(
        row["id"], receive_payload(3, stale_version), ADMIN
    )
    validate_error(res, "ERR_STALE_INVENTORY_VERSION", expected_status=412)


def test_available_qty_reconciled_after_reserve_and_commit(api):
    """PRD §2.5: "The `available_qty` is a derived field equal to `on_hand_qty` minus
    `reserved_qty`; it must be recomputed and kept consistent on every reserve,
    commit, and release".

    Received 5 -> place qty 2 -> fulfill: on_hand 3, reserved 0, available 3, with
    the identity available == on_hand - reserved holding throughout.

    Design: Corner/cross_cutting_complexity_layers/derived_available_qty_reconciled_after_reserve_and_commit
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="FOOTWEAR", name="Spike", base_price_cents=5000, size_label="9D")
    customer = create_customer(home_state_code="CA")
    inv = stock_sku(store["id"], sku["id"], 5)
    assert inv["available_qty"] == 5

    ready, _ = setup_ready_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 2}]
    )
    mid = get_inventory(inv["id"])
    assert mid["available_qty"] == 3
    assert mid["reserved_qty"] == 2

    fulfill_order(ready["id"])
    after = get_inventory(inv["id"])
    assert after["on_hand_qty"] == 3
    assert after["reserved_qty"] == 0
    assert after["available_qty"] == 3


# ===========================================================================
# consistency_model section
# ===========================================================================
def test_place_effects_visible_in_place_response(api):
    """PRD §3.3: "Placing an order advances the fulfillment axis `DRAFT → RESERVED`."
    PRD §3.3: "advances the payment axis `UNPAID → AUTHORIZED`, placing an
    authorization hold for the provisional total".

    All effects of place (RESERVED, provisional > 0) are visible immediately in the
    place response: a base-4000 single-line order reads RESERVED with
    provisional_total_cents 4000.

    Design: Corner/consistency_model/immediate_reservation_visible_in_place_response
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="BASEBALL", name="Ball2", base_price_cents=4000, size_label="NA")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    placed, _ = setup_placed_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    assert placed["fulfillment_status"] == "RESERVED"
    assert placed["provisional_total_cents"] == 4000
