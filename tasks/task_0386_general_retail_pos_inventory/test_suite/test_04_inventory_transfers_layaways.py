"""Inventory accounting (available_qty / below_reorder / reorder), count sheets,
multi-store transfers, layaway side effects, and aggregate/singleton occupation
overlaps.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    create_store, create_product, open_cash_session, create_loyalty_account,
    create_inventory_item, create_inventory_item_with_stock, seed_on_hand,
    create_layaway, get_inventory_item, get_layaway, get_transfer,
    create_transfer, dispatch_transfer,
    setup_transfer_pair, setup_dispatched_transfer, setup_layaway,
)

SM = TEST_USERS["store_manager_headers"]
CA = TEST_USERS["cashier_headers"]
IC = TEST_USERS["inventory_clerk_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Boundary precision: below_reorder inclusive via count post
# ─────────────────────────────────────────────────────────────────────────────

def test_below_reorder_inclusive_at_reorder_point_via_count_post(api):
    """PRD §2.9: "Whenever either physical or reserved stock moves — through a sale
    commitment, a return restock, a transfer leg, a layaway event, or a posted count —
    `available_qty` is recomputed as `on_hand_qty` minus `reserved_qty`, and the
    `below_reorder` flag is recomputed as true exactly when `available_qty` is at or
    below the item's `reorder_point` (the comparison is inclusive at the threshold)."
    PRD §3.11: "On a clean post the sheet moves `DRAFT → POSTED`: the signed
    `variance_qty` is recorded as `counted_qty` minus `snapshot_on_hand_qty`, the item's
    `on_hand_qty` is overwritten to `counted_qty`, and its `available_qty` and
    `below_reorder` are recomputed."

    Design: Difficulty/boundary_precision_check/below_reorder_inclusive_at_reorder_point_via_count_post
    """
    store = create_store("RP1", tax_rate_bps=0)
    product = create_product("PRP", "BRP", list_price_cents=100)
    inv = create_inventory_item(store["id"], product["id"],
                                reorder_point=5, reorder_qty=5)
    cs = get_success_data(api.create_count_sheet(
        {"inventory_item_id": inv["id"], "counted_qty": 5}, IC))
    posted = validate_success(api.post_count_sheet(cs["id"], IC))
    assert posted["variance_qty"] == 5, "5 counted - 0 snapshot"

    item = get_inventory_item(inv["id"])
    assert item["available_qty"] == 5
    assert item["below_reorder"] is True, "5 <= reorder_point 5 inclusive"


def test_count_post_above_reorder_point_clears_flag(api):
    """PRD §2.9: "the `below_reorder` flag is recomputed as true exactly when
    `available_qty` is at or below the item's `reorder_point` (the comparison is
    inclusive at the threshold)."
    PRD §3.11: "On a clean post the sheet moves `DRAFT → POSTED`: the signed
    `variance_qty` is recorded as `counted_qty` minus `snapshot_on_hand_qty`, the item's
    `on_hand_qty` is overwritten to `counted_qty`, and its `available_qty` and
    `below_reorder` are recomputed."

    Design: Difficulty/boundary_precision_check/below_reorder_inclusive_at_reorder_point_via_count_post
    """
    store = create_store("RP2", tax_rate_bps=0)
    product = create_product("PRP2", "BRP2", list_price_cents=100)
    inv = create_inventory_item(store["id"], product["id"],
                                reorder_point=5, reorder_qty=5)
    cs = get_success_data(api.create_count_sheet(
        {"inventory_item_id": inv["id"], "counted_qty": 6}, IC))
    validate_success(api.post_count_sheet(cs["id"], IC))
    item = get_inventory_item(inv["id"])
    assert item["available_qty"] == 6
    assert item["below_reorder"] is False, "6 > reorder_point 5"


# ─────────────────────────────────────────────────────────────────────────────
# Resource/temporal overlap: aggregate capacity & singleton session
# ─────────────────────────────────────────────────────────────────────────────

def test_dispatch_collides_with_layaway_reservation_aggregate(api):
    """PRD §3.10: "dispatch requires the source inventory item at (`from_store_id`,
    `product_id`) to exist with `available_qty` at least the `quantity`, failing which
    it is rejected with `ERR_INSUFFICIENT_STOCK`."
    PRD §3.9: "Creating a layaway reserves stock — the item's `reserved_qty` is
    increased by the `quantity`, and `available_qty` and `below_reorder` are recomputed
    — which requires `available_qty` to be at least the requested `quantity`;
    insufficient stock is rejected with `ERR_INSUFFICIENT_STOCK`."

    Design: Difficulty/resource_temporal_overlap/inventory_aggregate_capacity_reservation_overlap_on_inventory_item
    """
    store_a = create_store("AGA", tax_rate_bps=0, name="A")
    store_b = create_store("AGB", tax_rate_bps=0, name="B")
    product = create_product("PAG", "BAG", list_price_cents=1000)
    inv_a = create_inventory_item_with_stock(store_a["id"], product["id"], 5)
    create_inventory_item_with_stock(store_b["id"], product["id"], 0)
    account = create_loyalty_account(phone="555-0007")
    create_layaway(store_a["id"], product["id"], account["id"], 3,
                   "2026-12-31T00:00:00Z", initial_deposit_cents=0)
    transfer = create_transfer(store_a["id"], store_b["id"], product["id"], 3)

    resp = dispatch_transfer(transfer["id"], transfer["version"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)

    item = get_inventory_item(inv_a)
    assert item["available_qty"] == 2, "available unchanged after rejected dispatch"


def test_dispatch_within_available_after_reservation_succeeds(api):
    """PRD §3.10: "dispatch requires the source inventory item at (`from_store_id`,
    `product_id`) to exist with `available_qty` at least the `quantity`, failing which
    it is rejected with `ERR_INSUFFICIENT_STOCK`."
    PRD §3.10: "On dispatch the transfer moves `REQUESTED → DISPATCHED`, the source
    item's `reserved_qty` is increased by the `quantity`, and its `available_qty` and
    `below_reorder` are recomputed; the transfer's `version` increments by one."

    Design: Difficulty/resource_temporal_overlap/inventory_aggregate_capacity_reservation_overlap_on_inventory_item
    """
    store_a = create_store("AGA2", tax_rate_bps=0, name="A")
    store_b = create_store("AGB2", tax_rate_bps=0, name="B")
    product = create_product("PAG2", "BAG2", list_price_cents=1000)
    inv_a = create_inventory_item_with_stock(store_a["id"], product["id"], 5)
    create_inventory_item_with_stock(store_b["id"], product["id"], 0)
    account = create_loyalty_account(phone="555-0017")
    create_layaway(store_a["id"], product["id"], account["id"], 3,
                   "2026-12-31T00:00:00Z", initial_deposit_cents=0)
    transfer = create_transfer(store_a["id"], store_b["id"], product["id"], 2)
    dispatched = validate_success(
        dispatch_transfer(transfer["id"], transfer["version"]))
    assert dispatched["status"] == "DISPATCHED"
    item = get_inventory_item(inv_a)
    assert item["reserved_qty"] == 5, "3 layaway + 2 transfer reserved"
    assert item["available_qty"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Transfers: reject, receive-with-shrinkage
# ─────────────────────────────────────────────────────────────────────────────

def test_transfer_reject_returns_reserved_to_source_floor(api):
    """PRD §3.10: "Alternatively, an `InventoryClerk` may reject a dispatched transfer,
    moving it `DISPATCHED → REJECTED`, which returns the reserved units to the source
    floor by decrementing the source's `reserved_qty` by the `quantity` and recomputing
    `available_qty` and `below_reorder`."

    Design: Corner/errors/transfer_reject_returns_reserved_to_source_floor
    """
    s = setup_dispatched_transfer("RJA", "RJB", "PRJ", "BRJ", source_on_hand=10,
                                  quantity=3)
    rejected = validate_success(api.reject_transfer(s["transfer"]["id"], IC))
    assert rejected["status"] == "REJECTED"

    item = get_inventory_item(s["inv_a_id"])
    assert item["reserved_qty"] == 0
    assert item["available_qty"] == 10, "units returned to source floor"


def test_transfer_receive_with_shrinkage(api):
    """PRD §3.10: "On receive, the source item's `on_hand_qty` and `reserved_qty` are
    each decremented by the original `quantity` (with its `available_qty` and
    `below_reorder` recomputed), and the destination item's `on_hand_qty` is increased
    by the `received_qty` (with its `available_qty` and `below_reorder` recomputed)."

    Design: Corner/errors/transfer_receive_with_shrinkage
    """
    s = setup_dispatched_transfer("SHA", "SHB", "PSH", "BSH", source_on_hand=10,
                                  dest_on_hand=0, quantity=3)
    received = validate_success(
        api.receive_transfer(s["transfer"]["id"], {"received_qty": 2}, IC))
    assert received["status"] == "RECEIVED"
    assert received["received_qty"] == 2

    src = get_inventory_item(s["inv_a_id"])
    assert src["on_hand_qty"] == 7
    assert src["reserved_qty"] == 0
    dest = get_inventory_item(s["inv_b_id"])
    assert dest["on_hand_qty"] == 2, "1 unit shrinkage written off"


# ─────────────────────────────────────────────────────────────────────────────
# Layaway cancel / forfeit side effects
# ─────────────────────────────────────────────────────────────────────────────

def test_layaway_cancel_releases_reservation(api):
    """PRD §3.9: "A `StoreManager` may cancel a layaway only while it is `ACTIVE`,
    moving it to `CANCELLED`: the `reserved_qty` is decremented by the `quantity`,
    `available_qty` and `below_reorder` are recomputed, and the deposits paid are
    refunded to the customer (recorded, not modeled as a tender)."

    Design: Corner/errors/layaway_cancel_refunds_deposit_and_releases_reservation
    """
    s = setup_layaway("LC1", "PLC", "BLC", quantity=2, on_hand=5,
                      list_price_cents=1000, due_date="2030-12-31T00:00:00Z",
                      initial_deposit_cents=1000)
    cancelled = validate_success(api.cancel_layaway(s["layaway"]["id"], SM))
    assert cancelled["status"] == "CANCELLED"

    item = get_inventory_item(s["inventory_item_id"])
    assert item["reserved_qty"] == 0
    assert item["available_qty"] == 5, "reservation released"


def test_forfeit_non_delinquent_layaway_rejected(api):
    """PRD §3.9: "A `StoreManager` may forfeit a layaway, but only while it is
    `DELINQUENT`; a forfeit attempted on a layaway that is not `DELINQUENT` is rejected
    with `ERR_LAYAWAY_NOT_DELINQUENT`."

    Design: Corner/validations/forfeit_non_delinquent_layaway_returns_layaway_not_delinquent
    """
    s = setup_layaway("FF1", "PFF", "BFF", quantity=1, on_hand=5,
                      list_price_cents=1000, due_date="2030-12-31T00:00:00Z",
                      initial_deposit_cents=0)
    resp = api.forfeit_layaway(s["layaway"]["id"], SM)
    validate_error(resp, ApiErrorId.ERR_LAYAWAY_NOT_DELINQUENT.value)


# ─────────────────────────────────────────────────────────────────────────────
# Derived field reconciliation after sale commit
# ─────────────────────────────────────────────────────────────────────────────

def test_available_qty_reconciles_after_sale_commit(api):
    """PRD §2.9: "Whenever either physical or reserved stock moves — through a sale
    commitment, a return restock, a transfer leg, a layaway event, or a posted count —
    `available_qty` is recomputed as `on_hand_qty` minus `reserved_qty`, and the
    `below_reorder` flag is recomputed as true exactly when `available_qty` is at or
    below the item's `reorder_point` (the comparison is inclusive at the threshold)."

    Design: Corner/cross_cutting_complexity_layers/derived_field_available_qty_reconciles_after_sale_commit
    """
    store = create_store("DR1", tax_rate_bps=0)
    product = create_product("PDR", "BDR", list_price_cents=1000)
    inv_id = create_inventory_item_with_stock(store["id"], product["id"], 5,
                                              reorder_point=2, reorder_qty=5)
    open_cash_session(store["id"])
    sale = get_success_data(api.create_sale(
        {"store_id": store["id"], "kind": "SALE",
         "lines": [{"product_id": product["id"], "quantity": 2}]}, CA))
    validate_success(
        api.create_tender(sale["id"],
                          {"method": "CASH", "amount_cents": 2000,
                           "expected_sale_version": sale["version"]}, CA),
        expected_status=201)
    item = get_inventory_item(inv_id)
    assert item["on_hand_qty"] == 3
    assert item["available_qty"] == 3
    assert item["below_reorder"] is False, "3 > reorder_point 2"


# ─────────────────────────────────────────────────────────────────────────────
# Listing / read endpoints
# ─────────────────────────────────────────────────────────────────────────────

def test_list_inventory_items_filtered_by_below_reorder(api):
    """PRD §3.1: "The inventory list endpoint filters by `store_id`, `product_id`, and
    `below_reorder` so a clerk can pull every item at or below its reorder point."
    PRD §2.3: "The `meta` object of every list response carries `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/list_inventory_items_filtered_by_below_reorder
    """
    store = create_store("LI1", tax_rate_bps=0)
    p1 = create_product("PLI1", "BLI1", list_price_cents=100, name="P1")
    p2 = create_product("PLI2", "BLI2", list_price_cents=100, name="P2")
    inv1 = create_inventory_item(store["id"], p1["id"], reorder_point=5, reorder_qty=5)
    inv2 = create_inventory_item(store["id"], p2["id"], reorder_point=2, reorder_qty=5)
    seed_on_hand(inv2["id"], 10)  # available 10 > rp 2 -> not below

    resp = api.list_inventory_items(
        IC, params={"store_id": store["id"], "below_reorder": "true"})
    data, meta = validate_paginated(resp)
    ids = {row["id"] for row in data}
    assert inv1["id"] in ids, "below-reorder item present"
    assert inv2["id"] not in ids, "above-reorder item excluded"
    assert "total_count" in meta and "has_more" in meta


def test_list_sales_by_store(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or "array"
    for a list of resources."
    PRD §2.3: "Unless a specific endpoint states otherwise, all list endpoints return
    their resources sorted by creation timestamp (`created_at`) in ascending order."

    Design: Corner/endpoints/list_sales_by_store_reverse_reachability
    """
    store = create_store("LS1", tax_rate_bps=0)
    product = create_product("PLS", "BLS", list_price_cents=1000)
    open_cash_session(store["id"])
    sale = get_success_data(api.create_sale(
        {"store_id": store["id"], "kind": "SALE",
         "lines": [{"product_id": product["id"], "quantity": 1}]}, CA))

    resp = api.list_sales(SM, params={"store_id": store["id"]})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["id"] == sale["id"]
