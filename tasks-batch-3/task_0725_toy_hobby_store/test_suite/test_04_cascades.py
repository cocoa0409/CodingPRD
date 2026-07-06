"""Recall and order-cancel cascade chains."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_customer_headers,
    create_active_product, create_store, create_inventory, create_customer,
    create_open_order, add_line,
)

ADMIN = TEST_USERS["catalog_admin_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
ANY = TEST_USERS["any_headers"]


def test_recall_issue_quarantines_inventory(api):
    """PRD §3.2: "For every `InventoryItem` whose `product_id` matches the recalled
    product, the currently available and reserved units are frozen: `quarantined_qty`
    increases by the sum of that item's `available_qty` and `reserved_qty`, and both
    `available_qty` and `reserved_qty` are set to 0."

    Design: Difficulty/transitive_cascade/recall_issue_depth3_cascade
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH", safety_labels=["SMALL_PARTS"])
    store = create_store()
    inv = create_inventory(product["id"], store["id"], on_hand_qty=10)
    customer = create_customer()
    cid = customer["id"]
    order = create_open_order(cid, store["id"])
    add_line(order["id"], cid, product["id"], qty=3, recipient_age_months=60)

    recall = get_success_data(api.create_recall(
        {"product_id": product["id"], "severity": "MANDATORY", "reason": "hazard"}, ADMIN))
    validate_success(api.issue_recall(recall["id"], ADMIN))

    prod = validate_success(api.get_product(product["id"], ANY))
    assert prod["recall_status"] == "RECALLED"
    item = validate_success(api.get_inventory(inv["id"], ANY))
    assert item["quarantined_qty"] == 10
    assert item["available_qty"] == 0
    assert item["reserved_qty"] == 0


def test_recall_issue_voids_lines_and_cancels_order(api):
    """PRD §3.2: "Quarantining reserved units in turn voids the order lines that were
    holding them: every `ACTIVE` line on the recalled product transitions to `VOIDED` by
    system action. Each such void triggers a recompute of its parent order's
    `subtotal_cents`, `discount_cents`, and `total_cents` excluding voided lines, and if
    every `ACTIVE` line of an order has become `VOIDED`, that order's `fulfillment_status`
    moves to `CANCELLED`."

    Design: Difficulty/transitive_cascade/recall_issue_depth3_cascade
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH", safety_labels=["SMALL_PARTS"])
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=10)
    customer = create_customer()
    cid = customer["id"]
    order = create_open_order(cid, store["id"])
    line = add_line(order["id"], cid, product["id"], qty=3, recipient_age_months=60)

    recall = get_success_data(api.create_recall(
        {"product_id": product["id"], "severity": "MANDATORY", "reason": "hazard"}, ADMIN))
    validate_success(api.issue_recall(recall["id"], ADMIN))

    ln = validate_success(api.get_order_line(line["id"], ANY))
    assert ln["status"] == "VOIDED"
    ord_ = validate_success(api.get_order(order["id"], ANY))
    assert ord_["fulfillment_status"] == "CANCELLED"


def test_order_cancel_voids_line_and_releases_reservation(api):
    """PRD §3.11: "Cancellation cascades: every `ACTIVE` line becomes `VOIDED`. Each voided
    line releases its reservation on the matching inventory item — `reserved_qty` decreases
    by the line's `qty` and `available_qty` increases by the same `qty`."

    Design: Difficulty/transitive_cascade/order_cancel_depth2_cascade
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    inv = create_inventory(product["id"], store["id"], on_hand_qty=10)
    customer = create_customer()
    cid = customer["id"]
    order = create_open_order(cid, store["id"])
    line = add_line(order["id"], cid, product["id"], qty=4, recipient_age_months=60)

    validate_success(api.cancel_order(order["id"], make_customer_headers(cid)))

    ln = validate_success(api.get_order_line(line["id"], ANY))
    assert ln["status"] == "VOIDED"
    item = validate_success(api.get_inventory(inv["id"], ANY))
    assert item["reserved_qty"] == 0
    assert item["available_qty"] == 10


def test_order_cancel_moves_order_to_cancelled(api):
    """PRD §3.11: "An order may be cancelled by the owning `Customer` or a `StoreAssociate`
    while its `fulfillment_status` is `OPEN`, `SUBMITTED`, or `READY`, moving it to
    `CANCELLED` (terminal)."

    Design: Difficulty/transitive_cascade/order_cancel_depth2_cascade
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    create_inventory(product["id"], store["id"], on_hand_qty=10)
    customer = create_customer()
    cid = customer["id"]
    order = create_open_order(cid, store["id"])
    add_line(order["id"], cid, product["id"], qty=4, recipient_age_months=60)

    data = validate_success(api.cancel_order(order["id"], make_customer_headers(cid)))
    assert data["fulfillment_status"] == "CANCELLED"


def test_recall_resolution_clears_quarantine(api):
    """PRD §3.2: "On clearing, each affected inventory item keeps its `on_hand_qty`, sets
    `quarantined_qty` to 0, and recomputes `available_qty` as `on_hand_qty` minus
    `reserved_qty`."

    Design: Corner/calculations/recall_resolve_restores_availability
    """
    product = create_active_product(msrp_cents=1000, category="PLUSH")
    store = create_store()
    inv = create_inventory(product["id"], store["id"], on_hand_qty=10)

    recall = get_success_data(api.create_recall(
        {"product_id": product["id"], "severity": "MANDATORY", "reason": "hazard"}, ADMIN))
    validate_success(api.issue_recall(recall["id"], ADMIN))
    validate_success(api.issue_recall(recall["id"], ADMIN, {"resolve": True}))

    prod = validate_success(api.get_product(product["id"], ANY))
    assert prod["recall_status"] == "CLEARED"
    item = validate_success(api.get_inventory(inv["id"], ANY))
    assert item["quarantined_qty"] == 0
    assert item["available_qty"] == 10
