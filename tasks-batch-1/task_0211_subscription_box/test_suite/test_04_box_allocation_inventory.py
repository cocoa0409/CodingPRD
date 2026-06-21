"""Box curation and inventory allocation: the all-or-nothing multi-product fill
check, the Allocation RESERVED->{RELEASED|COMMITTED} branch, inventory
conservation across reserve+release, line_items snapshotting, derived-field
reconciliation, and the box-item-count validation.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId, TEST_USERS, make_subscriber_headers,
    create_box_selection_payload, create_allocation_payload,
    set_clock, get_product, get_wave, get_allocation, get_box_selection,
    create_plan, create_product, create_subscriber, create_subscription,
    create_wave, curate_box, reserve_box_into_wave,
    setup_reserved_allocation, lock_wave, ship_wave,
    list_shipments_for_allocation,
)

ADMIN = TEST_USERS["curation_admin_headers"]


# ─── combinatorial_formula: all-or-nothing fill (queue A, >=2 tests) ────────

def test_allocation_fill_short_product_rejects_whole_box(api):
    """PRD §3.8: "For every distinct product in the box, its available quantity
    must be at least the requested quantity for that product; if any single product
    is short, the entire box is rejected with `ERR_INSUFFICIENT_INVENTORY` and
    nothing is reserved."

    Box [A,A,B]: A.on_hand=1 (needs 2, short), B.on_hand=5. Whole box rejected.

    Design: Difficulty/combinatorial_formula/allocation_fill_all_or_nothing_multi_product_availability
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="TRIO", period_price_cents=6000, box_item_count=3)
    pa = create_product(sku="A-trio", name="Prod A", on_hand_qty=1)
    pb = create_product(sku="B-trio", name="Prod B", on_hand_qty=5)
    subscriber = create_subscriber(email="trio@x.com", full_name="Trio S")
    sub = create_subscription(subscriber, plan)
    box = curate_box(sub, subscriber, [pa["id"], pa["id"], pb["id"]])
    wave = create_wave("2026-06-15T00:00:00Z", "2026-06-16T00:00:00Z", capacity=10)
    res = api.create_allocation(
        create_allocation_payload(sub["id"], wave["id"], box["id"], wave["version"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value, expected_status=422)


def test_allocation_fill_nothing_reserved_on_rejection(api):
    """PRD §3.8: "if any single product is short, the entire box is rejected with
    `ERR_INSUFFICIENT_INVENTORY` and nothing is reserved."
    PRD §2.5: "`allocated_qty` is the reserved pool, the number of units currently
    held by `RESERVED` allocations."

    All-or-nothing: neither the short product nor the available one is reserved,
    and the wave's reserved_count stays 0.

    Design: Difficulty/combinatorial_formula/allocation_fill_all_or_nothing_multi_product_availability
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="TRIO2", period_price_cents=6000, box_item_count=3)
    pa = create_product(sku="A-trio2", name="Prod A", on_hand_qty=1)
    pb = create_product(sku="B-trio2", name="Prod B", on_hand_qty=5)
    subscriber = create_subscriber(email="trio2@x.com", full_name="Trio S2")
    sub = create_subscription(subscriber, plan)
    box = curate_box(sub, subscriber, [pa["id"], pa["id"], pb["id"]])
    wave = create_wave("2026-06-15T00:00:00Z", "2026-06-16T00:00:00Z", capacity=10)
    api.create_allocation(
        create_allocation_payload(sub["id"], wave["id"], box["id"], wave["version"]), ADMIN)

    assert get_product(pa["id"])["allocated_qty"] == 0, "short product reserved nothing"
    assert get_product(pb["id"])["allocated_qty"] == 0, "all-or-nothing: B not reserved either"
    assert get_wave(wave["id"])["reserved_count"] == 0


# ─── non_linear_state_machine: allocation branching (queue A, >=2 tests) ────

def test_allocation_branches_to_committed_on_ship(api):
    """PRD §3.9: "On ship, every `RESERVED` allocation on the wave is committed
    (`RESERVED` → `COMMITTED`): for each committed line item the product's
    `on_hand_qty` is decremented (the units physically leave) and its
    `allocated_qty` is decremented (they are no longer merely reserved), a
    `Shipment` is created in `PACKED` status".

    Design: Difficulty/non_linear_state_machine/allocation_branching_reserved_to_released_vs_committed
    """
    ctx = setup_reserved_allocation(product_on_hand=5, box_item_count=1, wave_capacity=10)
    set_clock("2026-06-15T00:00:00Z")
    lock_wave(ctx["wave"]["id"])
    ship_wave(ctx["wave"]["id"])

    alloc = get_allocation(ctx["allocation"]["id"])
    assert alloc["status"] == "COMMITTED", "ship branch must commit the allocation"
    product = get_product(ctx["product"]["id"])
    assert product["on_hand_qty"] == 4, "one unit physically departed on commit"
    assert product["allocated_qty"] == 0
    shipments = [s for s in list_shipments_for_allocation(ctx["allocation"]["id"])
                 if s["status"] == "PACKED"]
    assert len(shipments) == 1, "a PACKED shipment must exist for the committed allocation"


def test_allocation_branches_to_released_on_manual_release(api):
    """PRD §3.8: "A release — whether triggered explicitly, by a subscription
    cancel, by a wave cancel, by a box swap, or by a charge failure — moves the
    allocation `RESERVED` → `RELEASED`, returns each line item's reserved units to
    the free pool by decrementing the product's `allocated_qty` (leaving
    `on_hand_qty` untouched, since the units never left the warehouse)".

    Design: Difficulty/non_linear_state_machine/allocation_branching_reserved_to_released_vs_committed
    """
    ctx = setup_reserved_allocation(product_on_hand=5, box_item_count=1, wave_capacity=10)
    res = api.release_allocation(ctx["allocation"]["id"], ADMIN)
    released = validate_success(res, 200)
    assert released["status"] == "RELEASED", "release branch must release the allocation"
    product = get_product(ctx["product"]["id"])
    assert product["on_hand_qty"] == 5, "release leaves on_hand untouched (units never left)"
    assert product["allocated_qty"] == 0, "reserved units returned to the free pool"


# ─── compensating_invariant: inventory conserved (queue A, >=2 tests) ───────

def test_inventory_conserved_on_hand_unchanged_across_reserve_release(api):
    """PRD §2.5: "reserving moves units from free to reserved without any units
    leaving the building".
    PRD §3.8: "leaving `on_hand_qty` untouched, since the units never left the
    warehouse".

    on_hand starts 7; reserve then release; on_hand stays 7.

    Design: Difficulty/compensating_invariant/inventory_conserved_across_reserve_then_release
    """
    ctx = setup_reserved_allocation(product_on_hand=7, box_item_count=1, wave_capacity=10)
    assert get_product(ctx["product"]["id"])["allocated_qty"] == 1, "reserve raised allocated to 1"
    api.release_allocation(ctx["allocation"]["id"], ADMIN)
    product = get_product(ctx["product"]["id"])
    assert product["on_hand_qty"] == 7, "on_hand conserved across reserve+release"


def test_inventory_conserved_allocated_returns_to_pre_reserve(api):
    """PRD §3.8: "returns each line item's reserved units to the free pool by
    decrementing the product's `allocated_qty`".

    allocated returns to its pre-reserve value of 0 after release.

    Design: Difficulty/compensating_invariant/inventory_conserved_across_reserve_then_release
    """
    ctx = setup_reserved_allocation(product_on_hand=7, box_item_count=1, wave_capacity=10)
    res = api.release_allocation(ctx["allocation"]["id"], ADMIN)
    released = validate_success(res, 200)
    assert released["status"] == "RELEASED"
    product = get_product(ctx["product"]["id"])
    assert product["allocated_qty"] == 0, "allocated_qty returned to pre-reserve value"


# ─── cross_cutting / consistency corner ─────────────────────────────────────

def test_immediate_consistency_allocation_line_items_in_same_response(api):
    """PRD §3.8: "the box's `line_items` are snapshotted as a list of
    `{ product_id, qty }` (one entry per distinct product)".
    PRD §2.9: "The system applies every cascade synchronously and immediately
    within the triggering request — there is no eventual consistency."

    Box [P,P]: one line item {product_id: P, qty: 2}.

    Design: Corner/consistency_model/immediate_consistency_allocation_visible_in_same_response
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="IM", period_price_cents=6000, box_item_count=2)
    product = create_product(sku="IMP", name="IM P", on_hand_qty=5)
    subscriber = create_subscriber(email="im@x.com", full_name="IM S")
    sub = create_subscription(subscriber, plan)
    box = curate_box(sub, subscriber, [product["id"], product["id"]])
    wave = create_wave("2026-06-15T00:00:00Z", "2026-06-16T00:00:00Z", capacity=5)
    res = api.create_allocation(
        create_allocation_payload(sub["id"], wave["id"], box["id"], wave["version"]), ADMIN)
    alloc = validate_success(res, 201)
    assert len(alloc["line_items"]) == 1, "two of the same product collapse to one line item"
    li = alloc["line_items"][0]
    assert li["product_id"] == product["id"]
    assert li["qty"] == 2, f"qty must count the repeat (2), got {li['qty']}"
    assert get_product(product["id"])["allocated_qty"] == 2, "allocated reflects the reservation immediately"


def test_derived_allocated_qty_reconciles_after_partial_release(api):
    """PRD §2.5: "`allocated_qty` is the reserved pool, the number of units
    currently held by `RESERVED` allocations".
    PRD §3.8: "returns each line item's reserved units to the free pool by
    decrementing the product's `allocated_qty`".

    Two reservations of P (allocated=2); releasing one reconciles allocated to 1.

    Design: Corner/cross_cutting_complexity_layers/cascade_partial_then_full_release_derived_field_reconciliation
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="DR", period_price_cents=6000, box_item_count=1)
    product = create_product(sku="DRP", name="DR P", on_hand_qty=9)
    s1 = create_subscriber(email="dr1@x.com", full_name="DR One")
    sub1 = create_subscription(s1, plan)
    box1 = curate_box(sub1, s1, [product["id"]])
    s2 = create_subscriber(email="dr2@x.com", full_name="DR Two")
    sub2 = create_subscription(s2, plan)
    box2 = curate_box(sub2, s2, [product["id"]])
    wave = create_wave("2026-06-15T00:00:00Z", "2026-06-16T00:00:00Z", capacity=5)
    alloc1 = reserve_box_into_wave(sub1, box1, wave, wave["version"])
    w1 = get_wave(wave["id"])
    reserve_box_into_wave(sub2, box2, wave, w1["version"])
    assert get_product(product["id"])["allocated_qty"] == 2

    api.release_allocation(alloc1["id"], ADMIN)
    assert get_product(product["id"])["allocated_qty"] == 1, "reconciled to one remaining RESERVED"
    assert get_wave(wave["id"])["reserved_count"] == 1


def test_box_item_count_mismatch_rejected(api):
    """PRD §3.6: "A curated (non-skipped) box requires its `product_ids` to have a
    length exactly equal to the plan's `box_item_count`; a mismatch is rejected
    with `ERR_BOX_ITEM_COUNT_MISMATCH`."

    Design: Corner/validations/box_item_count_mismatch_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="BM", period_price_cents=6000, box_item_count=1)
    pa = create_product(sku="BMA", name="BM A", on_hand_qty=5)
    pb = create_product(sku="BMB", name="BM B", on_hand_qty=5)
    subscriber = create_subscriber(email="bm@x.com", full_name="BM S")
    sub = create_subscription(subscriber, plan)
    headers = make_subscriber_headers(subscriber["id"])
    res = api.create_box_selection(
        sub["id"], create_box_selection_payload(2, product_ids=[pa["id"], pb["id"]]), headers)
    validate_error(res, ApiErrorId.ERR_BOX_ITEM_COUNT_MISMATCH.value, expected_status=422)
