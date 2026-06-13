"""Entity creation, defaults, computed fields, not-found/validation errors, listing,
pagination, RBAC, and OCC.

Corner queue B: entities, endpoints, rbac, cross_cutting_concerns (OCC).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_pickup_event, assert_pickup_event_is_ledger, assert_inventory_movement,
    make_customer_headers, make_manager_headers,
    factories as f, fixtures as fx,
)


# --- entities --------------------------------------------------------------

def test_create_order_returns_201_with_defaults(api):
    """PRD §3.3: "A new order starts in `DRAFT` fulfillment with `payment_status`
    `UNAUTHORIZED` and `verified` false."
    PRD §2.4: "`version`, an integer that begins at 1 and increments by one on every
    mutation of that resource."

    Design: Corner/entities/create_order_returns_201_with_defaults
    """
    store = fx.create_store()
    customer = fx.create_customer()
    resp = validate_success(api.create_order(
        f.create_order_payload(customer["id"], store["id"]),
        make_customer_headers(customer["id"])), expected_status=201)
    assert resp["fulfillment_status"] == "DRAFT", resp
    assert resp["payment_status"] == "UNAUTHORIZED", resp
    assert resp["verified"] is False, resp
    assert resp["version"] == 1, resp


def test_store_default_hold_window_applied(api):
    """PRD §3.1: "an optional `hold_window_minutes` that defaults to 120 and must be at
    least one."

    Design: Corner/entities/store_default_hold_window_applied
    """
    resp = validate_success(api.create_store(
        f.create_store_payload(name="S", state_code="CA", curbside_spaces=2),
        fx.make_admin_headers()), expected_status=201)
    assert resp["hold_window_minutes"] == 120, resp


def test_slot_default_cutoff_offset_applied(api):
    """PRD §2.7: "a `cutoff_offset_minutes` (the number of minutes before the window
    start after which booking is no longer allowed; this defaults to 30 and must be at
    least zero)."

    Design: Corner/entities/slot_default_cutoff_offset_applied
    """
    store = fx.create_store()
    payload = f.create_pickup_slot_payload(
        store["id"], "2026-06-02T00:00:00Z", "2026-06-02T01:00:00Z", capacity=3)
    resp = validate_success(api.create_pickup_slot(payload, fx.make_admin_headers()),
                            expected_status=201)
    assert resp["cutoff_offset_minutes"] == 30, resp


def test_pickup_event_is_immutable_ledger_with_no_version(api):
    """PRD §2.4: "Two entities are deliberately lightweight ledgers and carry only `id`
    and `created_at`: a `PickupEvent` (the record of one line handed over in one pickup)
    and an `InventoryMovement` (an append-only inventory ledger entry)."
    PRD §2.4: "Neither of these carries `updated_at` or `version`, because both are
    immutable once written — they are never updated after creation."
    PRD §3.6: "a `PickupEvent` is created for each handed line recording the `order_id`,
    the `order_line_id`, the `qty_handed_over` for that event, and the `captured_cents`
    for that event"

    Design: Corner/entities/pickup_event_immutable_no_version_field
    """
    s = fx.setup_awaiting_pickup_order([{"price": 1000, "qty": 1}])
    order, lines = s["order"], s["lines"]
    validate_success(api.pickup_order(
        order["id"], f.pickup_payload([f.handover(lines[0]["id"], 1)]),
        fx.make_associate_headers()))
    events, meta = validate_paginated(api.list_order_pickup_events(order["id"], make_manager_headers()))
    assert meta["total_count"] == 1, meta
    ev = events[0]
    assert_pickup_event(ev)
    assert_pickup_event_is_ledger(ev)
    assert ev["captured_cents"] == 1000, ev


def test_get_order_not_found_returns_404(api):
    """PRD §2.5: "each path-referenced resource must exist before the next segment is
    considered, and the first missing resource yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_order_not_found_returns_404
    """
    resp = api.get_order(NON_EXISTENT_UUID, make_manager_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_order_missing_store_id_returns_invalid_request(api):
    """PRD §2.5: "Request bodies are also checked for the presence and type of required
    fields, valid enum values, and positive quantities where required; a malformed body
    is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.3: "supplying the `customer_id` (which must be their own) and the fulfilling
    `store_id`."

    Design: Corner/entities/create_order_missing_store_id_returns_invalid_request
    """
    customer = fx.create_customer()
    resp = api.create_order({"customer_id": customer["id"]}, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_order_line_non_positive_qty_returns_invalid_request(api):
    """PRD §2.5: "positive quantities where required; a malformed body is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.3: "each carrying a `product_id` and a positive `qty_ordered`"

    Design: Corner/entities/create_product_invalid_enum_substitution_group_type
    """
    store = fx.create_store()
    product = fx.create_product()
    customer = fx.create_customer()
    order = fx.create_draft_order(customer["id"], store["id"])
    resp = api.add_order_line(order["id"], {"product_id": product["id"], "qty_ordered": 0},
                              make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_submit_nonexistent_slot_returns_reference_not_found(api):
    """PRD §2.5: "when a request body carries a foreign key — for example the `store_id`
    and `product_id` on an inventory row, or the `slot_id` on a submission — each
    referenced resource must exist, and a dangling reference is rejected with
    `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/reference_not_found_submit_nonexistent_slot
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 5}])
    customer = base["customer"]
    order = fx.create_draft_order(customer["id"], base["store"]["id"])
    fx.add_line(order["id"], customer["id"], base["products"][0]["id"], 1)
    resp = api.submit_order(order["id"], f.submit_order_payload(NON_EXISTENT_UUID, 1),
                            make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# --- endpoints: listing / pagination / filter / ledger ---------------------

def test_list_customer_orders_pagination(api):
    """PRD §2.3: "The `limit` parameter defaults to 10, must be at least 1, and may be
    at most 100."
    PRD §2.3: "where `total_count` is the total number of matching records before
    pagination and `has_more` is true when records remain beyond the current page."

    Design: Corner/endpoints/list_customer_orders_pagination
    """
    store = fx.create_store()
    customer = fx.create_customer()
    fx.create_draft_order(customer["id"], store["id"])
    fx.create_draft_order(customer["id"], store["id"])
    data, meta = validate_paginated(api.list_customer_orders(
        customer["id"], make_customer_headers(customer["id"]), params={"limit": 1, "offset": 0}))
    assert len(data) == 1, data
    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta


def test_filtered_list_orders_by_store(api):
    """PRD §3.10: "several flat lists accept filter query parameters such as `store_id`,
    `product_id`, `slot_id`, `customer_id`, and `order_id` alongside the standard
    `limit` and `offset`."

    Design: Corner/endpoints/filtered_list_orders_by_store
    """
    s1 = fx.create_store()
    s2 = fx.create_store()
    customer = fx.create_customer()
    fx.create_draft_order(customer["id"], s1["id"])
    fx.create_draft_order(customer["id"], s2["id"])
    data, meta = validate_paginated(api.list_orders(make_manager_headers(), params={"store_id": s1["id"]}))
    assert meta["total_count"] == 1, meta
    assert all(o["store_id"] == s1["id"] for o in data), data


def test_inventory_movements_ledger_listed(api):
    """PRD §2.6: "Every inventory mutation is journaled. An `InventoryMovement` row
    records the affected `store_inventory_id`, a `movement_type` that is one of
    `RESTOCK`, `RESERVE`, `RELEASE`, or `PICK_REMOVE`"
    PRD §3.1: "an initial `RESTOCK` `InventoryMovement` is appended to the ledger."

    Design: Corner/endpoints/inventory_movements_ledger_listed
    """
    store = fx.create_store()
    product = fx.create_product()
    inv = fx.create_inventory(store["id"], product["id"], on_hand=5)
    validate_success(api.restock_inventory(inv["id"], f.restock_payload(3, inv["version"]),
                                           make_manager_headers()))
    data, meta = validate_paginated(api.list_inventory_movements(inv["id"], make_manager_headers()))
    assert meta["total_count"] >= 2, meta
    for mv in data:
        assert_inventory_movement(mv)


# --- rbac ------------------------------------------------------------------

def test_picker_cannot_create_store(api):
    """PRD §2.1: "If both headers are present but the supplied role is not permitted to
    invoke the endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 endpoint table: "POST | /stores | Create a store | PlatformAdmin"

    Design: Corner/rbac/picker_cannot_register_store
    """
    resp = api.create_store(f.create_store_payload(), fx.make_picker_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_customer_cannot_pick_line(api):
    """PRD §2.1: "If both headers are present but the supplied role is not permitted to
    invoke the endpoint, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 endpoint table: "POST | /order-lines/{id}/pick | Physically pick a line |
    StorePicker"

    Design: Corner/rbac/customer_cannot_pick_line
    """
    s = fx.setup_picking_order([{"price": 1000, "qty": 1}])
    line, customer = s["lines"][0], s["customer"]
    resp = api.pick_line(line["id"], {"qty_picked": 1}, make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_customer_cannot_submit_other_customers_order(api):
    """PRD §2.1: "when a customer acts on an order or on a substitution, the order's
    `customer_id` (for a substitution, the `customer_id` of the order that owns the
    substituted line) must equal `X-User-ID`; if it does not, the request is rejected
    with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/customer_cannot_act_on_other_customers_order
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 5}])
    c1 = base["customer"]
    c2 = fx.create_customer()
    order = fx.create_draft_order(c1["id"], base["store"]["id"])
    fx.add_line(order["id"], c1["id"], base["products"][0]["id"], 1)
    resp = api.submit_order(order["id"], f.submit_order_payload(base["slot"]["id"], base["slot_version"]),
                            make_customer_headers(c2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing on a protected endpoint, the request is
    rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_header_returns_unauthenticated
    """
    store = fx.create_store()
    resp = api.get_store(store["id"], headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# --- cross_cutting_concerns: OCC -------------------------------------------

def test_stale_inventory_version_on_restock_rejected(api):
    """PRD §2.11: "Restocking an inventory row adjusts `on_hand` against the prior
    availability snapshot, and the restock request must carry
    `expected_inventory_version` matching the target inventory row's current `version`."
    PRD §2.11: "If the inventory version has advanced since the client read it — because
    a reservation, a pick, or a prior restock already moved `on_hand` or `reserved` —
    the restock is rejected with `ERR_STALE_INVENTORY_VERSION` (HTTP 412) rather than
    being applied on top of an outdated baseline."

    Design: Corner/cross_cutting_concerns/occ_stale_inventory_version_on_restock
    """
    store = fx.create_store()
    product = fx.create_product()
    inv = fx.create_inventory(store["id"], product["id"], on_hand=5)
    v1 = inv["version"]
    v2_obj = validate_success(api.restock_inventory(inv["id"], f.restock_payload(1, v1),
                                                    make_manager_headers()))
    assert v2_obj["version"] == v1 + 1
    # retry with the now-stale v1
    resp = api.restock_inventory(inv["id"], f.restock_payload(1, v1), make_manager_headers())
    validate_error(resp, ApiErrorId.ERR_STALE_INVENTORY_VERSION.value)


def test_stale_slot_version_on_submit_rejected(api):
    """PRD §2.11: "Submitting an order books one unit of a pickup slot's capacity, and
    the submission must carry `expected_slot_version` matching the target slot's current
    `version`."
    PRD §2.11: "If the slot's version has advanced since the client last observed it —
    because another submission has already booked a unit and consumed capacity — the
    submission is rejected with `ERR_STALE_SLOT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_concerns/occ_stale_slot_version_on_submit
    """
    base = fx.seed_base_scenario(products=[{"price": 1000, "on_hand": 10}], capacity=5)
    store_id, slot_id, product_id = base["store"]["id"], base["slot"]["id"], base["products"][0]["id"]
    sv_pre = base["slot_version"]
    c1 = base["customer"]
    c2 = fx.create_customer()
    o1 = fx.create_draft_order(c1["id"], store_id)
    fx.add_line(o1["id"], c1["id"], product_id, 1)
    o2 = fx.create_draft_order(c2["id"], store_id)
    fx.add_line(o2["id"], c2["id"], product_id, 1)
    # O1 books with the fresh version -> slot version advances past sv_pre
    fx.submit_order(o1["id"], c1["id"], slot_id, sv_pre)
    # O2 submits with the now-stale sv_pre
    resp = api.submit_order(o2["id"], f.submit_order_payload(slot_id, sv_pre),
                            make_customer_headers(c2["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_SLOT_VERSION.value)
