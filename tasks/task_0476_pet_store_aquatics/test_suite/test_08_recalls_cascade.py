"""Recall lifecycle: three-hop issuance cascade, surgical resolve compensation,
two-recall reconciliation, and resolved-recall lockdown.

Skipped here (not emitted): Difficulty/priority_pair_validation_conflict/
recall_safety_beats_inventory_fiscal_on_run_shipment. The §1.8 setup creates the
subscription BEFORE issuing the recall, so the recall cascade (§3.9 hop 3) halts
that ACTIVE subscription. At run-shipment time the subscription is HALTED, and
§3.10 pins the status==ACTIVE check FIRST in its ordered check list — a faithful
PRD-only implementer therefore returns ERR_SUBSCRIPTION_STATE_INVALID, not the
asserted ERR_PRODUCT_RECALLED. The asserted outcome is not uniquely derivable
from PRD prose, so the instance is skipped rather than weakened.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    create_recall_payload,
    make_store, make_product, make_lot,
    setup_recall_scenario, issue_recall,
)

INVMGR = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["store_clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / three-hop recall cascade
# ---------------------------------------------------------------------------
def test_recall_three_hop_lot_product_subscription(api):
    """PRD §3.9: "In the first hop, every in-scope `AVAILABLE` `InventoryLot` for
    the product ... is set to `QUARANTINED`, its `version` bumped, and the count
    of such lots is recorded in the recall's `affected_lot_count`. The second hop
    is caused by the first: the product's `recall_state` is recomputed from its
    now-quarantined coverage and becomes `RECALLED`. The third hop is caused by
    the second: every `Subscription` whose `status` is `ACTIVE` or `PAUSED`,
    whose product is now `RECALLED`, and whose store lies within the recall's
    scope is moved to `HALTED`, each such subscription's `version` bumped, and
    the count recorded in the recall's `halted_subscription_count`."

    Design: Difficulty/transitive_cascade/recall_three_hop_lot_product_subscription
    """
    ctx = setup_recall_scenario(lot_qty=50, with_subscription=True)
    lot = ctx["lot"]
    product = ctx["product"]
    sub = ctx["subscription"]
    recall = issue_recall(product["id"], severity="MANDATORY")
    lot_after = validate_success(api.get_inventory_lot(lot["id"], INVMGR), 200)
    prod_after = validate_success(api.get_product(product["id"], INVMGR), 200)
    sub_after = validate_success(api.get_subscription(sub["id"], CLERK), 200)
    assert lot_after["status"] == "QUARANTINED"
    assert prod_after["recall_state"] == "RECALLED"
    assert sub_after["status"] == "HALTED"
    assert recall["affected_lot_count"] == 1
    assert recall["halted_subscription_count"] == 1


def test_recall_cascade_counts_recorded(api):
    """PRD §3.9: "every in-scope `AVAILABLE` `InventoryLot` for the product ... is
    set to `QUARANTINED`, its `version` bumped, and the count of such lots is
    recorded in the recall's `affected_lot_count`."
    PRD §3.9: "each such subscription's `version` bumped, and the count recorded
    in the recall's `halted_subscription_count`."

    Design: Difficulty/transitive_cascade/recall_three_hop_lot_product_subscription
    """
    ctx = setup_recall_scenario(lot_qty=50, with_subscription=True)
    recall = issue_recall(ctx["product"]["id"], severity="MANDATORY")
    assert recall["affected_lot_count"] == 1
    assert recall["halted_subscription_count"] == 1
    assert recall["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Corner: state_machines / resolve compensation reactivates subscription
# ---------------------------------------------------------------------------
def test_recall_resolve_reactivates_halted_subscription(api):
    """PRD §3.9: "For every lot this recall quarantined that is not still covered
    by another `OPEN` recall, the lot's `status` returns to `AVAILABLE` and its
    `version` is bumped. Each affected product's `recall_state` is then
    recomputed and becomes `CLEAR` when no `OPEN` recall covers it any longer.
    For every subscription that this recall halted whose product is now `CLEAR`,
    the subscription returns to `ACTIVE`".

    Design: Corner/state_machines/recall_resolve_reactivates_halted_subscription
    """
    ctx = setup_recall_scenario(lot_qty=50, with_subscription=True)
    lot = ctx["lot"]
    product = ctx["product"]
    sub = ctx["subscription"]
    recall = issue_recall(product["id"], severity="MANDATORY")
    resolved = validate_success(api.resolve_recall(recall["id"], INVMGR), 200)
    assert resolved["status"] == "RESOLVED"
    lot_after = validate_success(api.get_inventory_lot(lot["id"], INVMGR), 200)
    prod_after = validate_success(api.get_product(product["id"], INVMGR), 200)
    sub_after = validate_success(api.get_subscription(sub["id"], CLERK), 200)
    assert lot_after["status"] == "AVAILABLE"
    assert prod_after["recall_state"] == "CLEAR"
    assert sub_after["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner: state_machines / resolve already-resolved recall rejected
# ---------------------------------------------------------------------------
def test_resolve_already_resolved_recall_rejected(api):
    """PRD §3.9: "resolution is an `InventoryManager` action, permitted only
    while the recall is `OPEN` (otherwise `ERR_RECALL_STATE_INVALID`)."

    Design: Corner/state_machines/resolve_already_resolved_recall_rejected
    """
    product = make_product()
    recall = validate_success(
        api.create_recall(
            create_recall_payload(product["id"], severity="ADVISORY"), INVMGR
        ), 201,
    )
    validate_success(api.resolve_recall(recall["id"], INVMGR), 200)
    res = api.resolve_recall(recall["id"], INVMGR)
    validate_error(res, ApiErrorId.ERR_RECALL_STATE_INVALID)


# ---------------------------------------------------------------------------
# Corner: cross_cutting / two-recall derived-field reconciliation
# ---------------------------------------------------------------------------
def test_derived_recall_state_two_open_recalls_resolve_one_stays_recalled(api):
    """PRD §3.9: "Resolving a recall is the compensating operation, reversing only
    the effects that this particular recall caused, and only where no other open
    recall still demands them. For every lot this recall quarantined that is not
    still covered by another `OPEN` recall, the lot's `status` returns to
    `AVAILABLE`".
    PRD §3.1: "A product is `RECALLED` whenever at least one `OPEN` `Recall`
    covers it".

    Design: Corner/cross_cutting_complexity_layers/derived_recall_state_two_open_recalls_resolve_one_stays_recalled
    """
    store = make_store()
    product = make_product()
    lot = make_lot(store["id"], product["id"], quantity_on_hand=10)
    r1 = validate_success(
        api.create_recall(
            create_recall_payload(product["id"], severity="ADVISORY"), INVMGR
        ), 201,
    )
    validate_success(
        api.create_recall(
            create_recall_payload(product["id"], severity="MANDATORY"), INVMGR
        ), 201,
    )
    # Resolve only the first recall; the second still covers the product.
    resolved = validate_success(api.resolve_recall(r1["id"], INVMGR), 200)
    assert resolved["status"] == "RESOLVED"
    prod_after = validate_success(api.get_product(product["id"], INVMGR), 200)
    lot_after = validate_success(api.get_inventory_lot(lot["id"], INVMGR), 200)
    assert prod_after["recall_state"] == "RECALLED", "second recall still covers it"
    assert lot_after["status"] == "QUARANTINED", "lot still covered, stays quarantined"
