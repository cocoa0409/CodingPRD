"""Role authorization on privileged operations and order-list pagination."""
from test_helpers import (
    validate_error, validate_paginated,
    make_store, make_sku, make_member, make_order, order_line, create_store_payload,
    make_member_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ASSOC = TEST_USERS["associate_headers"]


# ── Corner/rbac/rbac_member_cannot_create_store ──────────────
def test_member_cannot_create_store(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/rbac_member_cannot_create_store
    """
    seed_store = make_store(state_code="OR")
    member = make_member(seed_store["id"])
    res = api.create_store(create_store_payload(name="Rogue Store", state_code="CA"),
                           make_member_headers(member["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


# ── Corner/rbac/rbac_associate_cannot_set_clock ──────────────
def test_associate_cannot_set_clock(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/rbac_associate_cannot_set_clock
    """
    res = api.set_clock({"to_iso8601": "2026-07-06T00:00:00Z"}, ASSOC)
    validate_error(res, "ERR_UNAUTHORIZED")


# ── Corner/endpoints/orders_list_pagination ──────────────────
def test_orders_list_pagination(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when omitted it
    defaults to 10, and it must lie between a minimum of 1 and a maximum of 100."
    PRD §2.3: "List responses carry the pagination bookkeeping in the `meta` object of the
    envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/orders_list_pagination
    """
    store = make_store(state_code="OR")
    sku = make_sku(list_price_cents=2000, on_hand_qty=20, category="APPLIANCE", name="Timer")
    member = make_member(store["id"])
    make_order(member["id"], store["id"], [order_line(sku["id"], 1)])
    make_order(member["id"], store["id"], [order_line(sku["id"], 1)])
    data, meta = validate_paginated(api.list_orders(ADMIN, params={"member_id": member["id"], "limit": 1}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1
