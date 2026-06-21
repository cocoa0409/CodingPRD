"""Shipping-wave lifecycle and cascades: the depth-3 immediate-cancel cascade,
the depth-2 wave-cancel cascade, the strict cutoff boundary on reservation, the
empty-wave ship guard, lock-before-cutoff, and the shipment terminal lockdown.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId, TEST_USERS, make_subscriber_headers,
    cancel_payload, create_allocation_payload,
    set_clock, get_product, get_wave, get_allocation, get_box_selection,
    get_subscription,
    create_plan, create_product, create_subscriber, create_subscription,
    create_wave, curate_box, reserve_box_into_wave,
    setup_reserved_allocation, lock_wave, ship_wave,
    list_shipments_for_allocation,
)

ADMIN = TEST_USERS["curation_admin_headers"]


# ─── transitive_cascade: immediate cancel depth-3 (queue A, >=2 tests) ──────

def test_immediate_cancel_cascade_releases_allocation_and_restocks(api):
    """PRD §3.3: "any box selection for an upcoming period that is finalized into
    an `OPEN` or `LOCKED` wave is reverted from `FINALIZED` to `SKIPPED`, which
    releases its allocation (the allocation moves `RESERVED` → `RELEASED`), the
    release restocks each line item back to the product's free pool and decrements
    the holding wave's `reserved_count`."

    Design: Difficulty/transitive_cascade/immediate_cancel_depth3_box_revert_release_restock
    """
    ctx = setup_reserved_allocation(product_on_hand=5, box_item_count=1, wave_capacity=10)
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    res = api.cancel_subscription(ctx["subscription"]["id"], cancel_payload("IMMEDIATE"), headers)
    cancelled = validate_success(res, 200)
    assert cancelled["lifecycle_status"] == "CANCELLED"

    assert get_allocation(ctx["allocation"]["id"])["status"] == "RELEASED"
    product = get_product(ctx["product"]["id"])
    assert product["allocated_qty"] == 0, "restocked to free pool"
    assert product["on_hand_qty"] == 5, "units never left the warehouse"
    assert get_wave(ctx["wave"]["id"])["reserved_count"] == 0


def test_immediate_cancel_cascade_reverts_box_to_skipped(api):
    """PRD §3.3: "any box selection for an upcoming period that is finalized into
    an `OPEN` or `LOCKED` wave is reverted from `FINALIZED` to `SKIPPED`".

    The box-selection hop of the depth-3 chain: the finalized box becomes SKIPPED.

    Design: Difficulty/transitive_cascade/immediate_cancel_depth3_box_revert_release_restock
    """
    ctx = setup_reserved_allocation(product_on_hand=5, box_item_count=1, wave_capacity=10)
    assert get_box_selection(ctx["box"]["id"])["decision"] == "FINALIZED"
    headers = make_subscriber_headers(ctx["subscriber"]["id"])
    validate_success(
        api.cancel_subscription(ctx["subscription"]["id"], cancel_payload("IMMEDIATE"), headers), 200)
    assert get_box_selection(ctx["box"]["id"])["decision"] == "SKIPPED"


# ─── transitive_cascade: wave cancel depth-2 (queue A, >=2 tests) ───────────

def _setup_two_reservations_one_wave():
    """Two subscribers each reserve one box of the same product into one OPEN wave."""
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="WC", period_price_cents=6000, box_item_count=1)
    product = create_product(sku="WCP", name="WC Prod", on_hand_qty=8)
    s1 = create_subscriber(email="wc1@x.com", full_name="WC One")
    sub1 = create_subscription(s1, plan)
    box1 = curate_box(sub1, s1, [product["id"]])
    s2 = create_subscriber(email="wc2@x.com", full_name="WC Two")
    sub2 = create_subscription(s2, plan)
    box2 = curate_box(sub2, s2, [product["id"]])
    wave = create_wave("2026-06-15T00:00:00Z", "2026-06-16T00:00:00Z", capacity=10)
    alloc1 = reserve_box_into_wave(sub1, box1, wave, wave["version"])
    w1 = get_wave(wave["id"])
    alloc2 = reserve_box_into_wave(sub2, box2, wave, w1["version"])
    return {"product": product, "wave": wave, "box1": box1, "box2": box2,
            "alloc1": alloc1, "alloc2": alloc2}


def test_wave_cancel_releases_all_reservations_and_restocks(api):
    """PRD §3.9: "An admin may **cancel** an `OPEN` wave. Cancellation cascades:
    every `RESERVED` allocation on the wave is released, restocking each line item
    to the product's free pool (decrementing `allocated_qty`) and reverting its box
    selection's `decision` from `FINALIZED` back to `CURATED`; the wave's
    `reserved_count` is reset to 0; and the wave moves `OPEN` → `CANCELLED`."

    Design: Difficulty/transitive_cascade/wave_cancel_depth2_release_restock_box_revert
    """
    ctx = _setup_two_reservations_one_wave()
    assert get_product(ctx["product"]["id"])["allocated_qty"] == 2
    res = api.cancel_wave(ctx["wave"]["id"], ADMIN)
    wave = validate_success(res, 200)
    assert wave["status"] == "CANCELLED"
    assert get_allocation(ctx["alloc1"]["id"])["status"] == "RELEASED"
    assert get_allocation(ctx["alloc2"]["id"])["status"] == "RELEASED"
    product = get_product(ctx["product"]["id"])
    assert product["allocated_qty"] == 0, "both reservations restocked"
    assert product["on_hand_qty"] == 8


def test_wave_cancel_reverts_boxes_to_curated(api):
    """PRD §3.9: "reverting its box selection's `decision` from `FINALIZED` back to
    `CURATED`".

    Wave cancel reverts each box to CURATED (distinct from immediate-cancel which
    reverts to SKIPPED).

    Design: Difficulty/transitive_cascade/wave_cancel_depth2_release_restock_box_revert
    """
    ctx = _setup_two_reservations_one_wave()
    validate_success(api.cancel_wave(ctx["wave"]["id"], ADMIN), 200)
    assert get_box_selection(ctx["box1"]["id"])["decision"] == "CURATED"
    assert get_box_selection(ctx["box2"]["id"])["decision"] == "CURATED"


# ─── boundary_precision: strict cutoff on reservation (queue A, >=2 tests) ──

def _setup_curated_box_and_wave(cutoff, ship, capacity=10):
    set_clock("2026-06-01T00:00:00Z")
    plan = create_plan(name="BP1", period_price_cents=6000, box_item_count=1)
    product = create_product(sku="BP1P", name="BP1 P", on_hand_qty=5)
    subscriber = create_subscriber(email="bp1@x.com", full_name="BP1 S")
    sub = create_subscription(subscriber, plan)
    box = curate_box(sub, subscriber, [product["id"]])
    wave = create_wave(cutoff, ship, capacity=capacity)
    return {"sub": sub, "box": box, "wave": wave, "product": product}


def test_reservation_at_exact_cutoff_instant_rejected(api):
    """PRD §3.9: "a box may *join* a wave by reservation only while the clock is
    strictly before `cutoff_at`, so a reservation attempt at or after the cutoff is
    rejected with `ERR_CUTOFF_PASSED`".

    Clock == cutoff_at exactly -> rejected (strict <).

    Design: Difficulty/boundary_precision_check/wave_cutoff_strict_less_than_at_exact_instant_rejected
    """
    ctx = _setup_curated_box_and_wave("2026-06-10T00:00:00Z", "2026-06-16T00:00:00Z")
    set_clock("2026-06-10T00:00:00Z")  # exactly at cutoff
    res = api.create_allocation(
        create_allocation_payload(ctx["sub"]["id"], ctx["wave"]["id"], ctx["box"]["id"],
                                  ctx["wave"]["version"]), ADMIN)
    validate_error(res, ApiErrorId.ERR_CUTOFF_PASSED.value, expected_status=422)


def test_reservation_at_exact_cutoff_reserves_nothing(api):
    """PRD §3.9: "a reservation attempt at or after the cutoff is rejected with
    `ERR_CUTOFF_PASSED`".
    PRD §3.8: "A wave opens in `OPEN` `status` with `reserved_count` 0".

    The rejected reservation leaves reserved_count at 0.

    Design: Difficulty/boundary_precision_check/wave_cutoff_strict_less_than_at_exact_instant_rejected
    """
    ctx = _setup_curated_box_and_wave("2026-06-10T00:00:00Z", "2026-06-16T00:00:00Z")
    set_clock("2026-06-10T00:00:00Z")
    api.create_allocation(
        create_allocation_payload(ctx["sub"]["id"], ctx["wave"]["id"], ctx["box"]["id"],
                                  ctx["wave"]["version"]), ADMIN)
    assert get_wave(ctx["wave"]["id"])["reserved_count"] == 0


# ─── boundary_precision: ship empty wave (queue A, >=2 tests) ───────────────

def test_ship_empty_wave_zero_reserved_rejected(api):
    """PRD §3.9: "Shipping requires the wave to be `LOCKED` and to hold at least
    one `RESERVED` allocation; shipping a wave with zero reserved allocations is
    rejected with `ERR_EMPTY_WAVE`."

    Design: Difficulty/boundary_precision_check/ship_empty_wave_zero_reserved_allocations_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    wave = create_wave("2026-06-10T00:00:00Z", "2026-06-16T00:00:00Z", capacity=10)
    set_clock("2026-06-10T00:00:00Z")
    lock_wave(wave["id"])
    res = api.ship_wave(wave["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_EMPTY_WAVE.value, expected_status=422)


def test_ship_empty_wave_leaves_wave_locked(api):
    """PRD §3.9: "shipping a wave with zero reserved allocations is rejected with
    `ERR_EMPTY_WAVE`."
    PRD §3.9: "Locking moves the wave `OPEN` → `LOCKED`".

    A rejected ship does not advance the wave; it stays LOCKED.

    Design: Difficulty/boundary_precision_check/ship_empty_wave_zero_reserved_allocations_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    wave = create_wave("2026-06-10T00:00:00Z", "2026-06-16T00:00:00Z", capacity=10)
    set_clock("2026-06-10T00:00:00Z")
    lock_wave(wave["id"])
    api.ship_wave(wave["id"], ADMIN)
    assert get_wave(wave["id"])["status"] == "LOCKED", "ship did not fire; wave stays LOCKED"


# ─── state_machines corner: lock before cutoff, shipment terminal lockdown ──

def test_wave_lock_before_cutoff_rejected(api):
    """PRD §3.9: "locking is permitted only when the wave is `OPEN` and the current
    clock is at or after `cutoff_at`; an attempt to lock before the cutoff is
    rejected with `ERR_CUTOFF_NOT_REACHED`."

    Design: Corner/state_machines/wave_lock_before_cutoff_rejected
    """
    set_clock("2026-06-05T00:00:00Z")
    wave = create_wave("2026-06-10T00:00:00Z", "2026-06-16T00:00:00Z", capacity=5)
    res = api.lock_wave(wave["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_CUTOFF_NOT_REACHED.value, expected_status=422)
    assert get_wave(wave["id"])["status"] == "OPEN", "wave unchanged after rejected lock"


def test_dispatch_after_delivered_terminal_rejected(api):
    """PRD §3.10: "delivering moves a `DISPATCHED` shipment to `DELIVERED`.
    `DELIVERED` is terminal."
    PRD §2.8: "the target resource is in a state from which the requested
    transition is defined; for a reservation, the referenced `ShippingWave` must be
    `OPEN`. A violation yields `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/dispatch_shipment_before_packed_irrelevant_terminal_delivered_lockdown
    """
    ctx = setup_reserved_allocation(product_on_hand=5, box_item_count=1, wave_capacity=10,
                                    cutoff_at="2026-06-10T00:00:00Z",
                                    ship_date="2026-06-16T00:00:00Z")
    set_clock("2026-06-10T00:00:00Z")
    lock_wave(ctx["wave"]["id"])
    ship_wave(ctx["wave"]["id"])
    shipment = list_shipments_for_allocation(ctx["allocation"]["id"])[0]
    validate_success(api.dispatch_shipment(shipment["id"], ADMIN), 200)
    validate_success(api.deliver_shipment(shipment["id"], ADMIN), 200)
    res = api.dispatch_shipment(shipment["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)
