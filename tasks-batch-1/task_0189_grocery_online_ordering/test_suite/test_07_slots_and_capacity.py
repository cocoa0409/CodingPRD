"""Slot capacity, window overlap, picker cooldown, OCC, and conservation.

Difficulty queue A: slot-capacity strict-less-than boundary, slot/picker window
overlap arithmetic, slot-count conservation. Corner queue B: OCC stale version,
per-placement version increment, list pagination envelope.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    assert_slot,
    make_customer_headers,
    make_picker_headers,
    create_store,
    create_customer,
    create_picker,
    create_product,
    create_slot,
    place_order,
    get_slot_version,
    claim_order,
    ADMIN,
    OPS,
)


def test_slot_capacity_strict_less_than_boundary(api):
    """PRD §2.6: "a new order is admitted only when the slot's `booked_count` is strictly less than `capacity` before the booking is recorded; otherwise the placement is refused with `ERR_SLOT_FULL`."
    PRD §2.6: "A successful placement increases `booked_count` by one, and if that brings `booked_count` up to `capacity` the slot transitions `OPEN → FULL`."

    Design: Difficulty/boundary_precision_check/bpc_slot_capacity_strict_less_than
    """
    store = create_store(ebt_enabled=True)
    c1 = create_customer(email="c11a@x.com")
    c2 = create_customer(email="c11b@x.com")
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    # First placement: booked_count 0 < 1 -> succeeds, slot FULL, version bumped.
    place_order(store["id"], c1["id"], slot["id"], slot["version"],
                [{"product_id": a["id"], "requested_qty": 1}])
    refreshed = validate_success(api.get_slot(slot["id"], OPS))
    assert refreshed["status"] == "FULL"

    resp = api.create_order(
        {"store_id": store["id"], "customer_id": c2["id"], "slot_id": slot["id"],
         "expected_slot_version": refreshed["version"],
         "lines": [{"product_id": a["id"], "requested_qty": 1}]},
        make_customer_headers(c2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_FULL.value, 409)
    final = validate_success(api.get_slot(slot["id"], OPS))
    assert final["booked_count"] == 1
    assert final["status"] == "FULL"


def test_slot_capacity_admits_below_boundary(api):
    """PRD §2.6: "a new order is admitted only when the slot's `booked_count` is strictly less than `capacity` before the booking is recorded ... "
    PRD §2.6: "A successful placement increases `booked_count` by one, and if that brings `booked_count` up to `capacity` the slot transitions `OPEN → FULL`."

    Design: Difficulty/boundary_precision_check/bpc_slot_capacity_strict_less_than
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c11c@x.com")
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=2)
    # booked_count 0 < 2 -> admitted; count -> 1, still below capacity so stays OPEN.
    place_order(store["id"], customer["id"], slot["id"], slot["version"],
                [{"product_id": a["id"], "requested_qty": 1}])
    after = validate_success(api.get_slot(slot["id"], OPS))
    assert after["booked_count"] == 1
    assert after["status"] == "OPEN", "below capacity remains OPEN"


def test_slot_window_half_open_overlap_rejected(api):
    """PRD §2.7: "The window is treated as half-open — it includes its start instant and excludes its end instant. When a new slot is created, the system rejects it with `ERR_SLOT_WINDOW_OVERLAP` if its window overlaps that of any existing slot belonging to the same store and having the same `slot_type`."

    Design: Difficulty/resource_temporal_overlap/rto_slot_window_half_open_overlap
    """
    store = create_store(ebt_enabled=True)
    create_slot(store["id"], slot_type="PICKUP",
                window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T11:00:00Z",
                capacity=5)
    # Adjacent touching window is allowed (half-open).
    adj = api.create_slot(
        {"store_id": store["id"], "slot_type": "PICKUP",
         "window_start": "2026-06-15T11:00:00Z", "window_end": "2026-06-15T13:00:00Z",
         "capacity": 5}, OPS)
    validate_success(adj, 201)
    # Overlapping window [10:00,12:00) is rejected.
    resp = api.create_slot(
        {"store_id": store["id"], "slot_type": "PICKUP",
         "window_start": "2026-06-15T10:00:00Z", "window_end": "2026-06-15T12:00:00Z",
         "capacity": 5}, OPS)
    validate_error(resp, ApiErrorId.ERR_SLOT_WINDOW_OVERLAP.value, 409)


def test_slot_window_touching_boundary_allowed(api):
    """PRD §2.7: "The window is treated as half-open — it includes its start instant and excludes its end instant. When a new slot is created, the system rejects it with `ERR_SLOT_WINDOW_OVERLAP` if its window overlaps that of any existing slot belonging to the same store and having the same `slot_type`."

    Design: Difficulty/resource_temporal_overlap/rto_slot_window_half_open_overlap
    """
    store = create_store(ebt_enabled=True)
    create_slot(store["id"], slot_type="PICKUP",
                window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T11:00:00Z",
                capacity=5)
    # A window starting exactly at the prior window's exclusive end does not overlap.
    resp = api.create_slot(
        {"store_id": store["id"], "slot_type": "PICKUP",
         "window_start": "2026-06-15T11:00:00Z", "window_end": "2026-06-15T13:00:00Z",
         "capacity": 5}, OPS)
    data = validate_success(resp, 201)
    assert_slot(data)
    assert data["status"] == "OPEN"


def test_picker_window_buffered_overlap_rejected(api):
    """PRD §3.2: "the new pick window `[window_start, window_end)` must not overlap any window the picker already holds once each held window is extended by the picker's `window_cooldown_minutes` buffer on each side; if the new window collides with an existing window within that buffer, the claim is rejected with `ERR_PICKER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rto_picker_window_buffered_overlap
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c16@x.com")
    picker = create_picker(store["id"], window_cooldown_minutes=15)
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=2)
    o1 = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                     [{"product_id": a["id"], "requested_qty": 1}])
    o2 = place_order(store["id"], customer["id"], slot["id"], get_slot_version(slot["id"]),
                     [{"product_id": a["id"], "requested_qty": 1}])
    ph = make_picker_headers(picker["id"])
    validate_success(
        api.claim_order(o1["id"],
                        {"window_start": "2026-06-15T07:00:00Z",
                         "window_end": "2026-06-15T07:45:00Z"}, ph))
    # Second claim 5 minutes after first window end -> within 15-min cooldown.
    resp = api.claim_order(
        o2["id"], {"window_start": "2026-06-15T07:50:00Z",
                   "window_end": "2026-06-15T08:30:00Z"}, ph)
    validate_error(resp, ApiErrorId.ERR_PICKER_WINDOW_CONFLICT.value, 409)


def test_picker_window_outside_cooldown_allowed(api):
    """PRD §3.2: "the new pick window `[window_start, window_end)` must not overlap any window the picker already holds once each held window is extended by the picker's `window_cooldown_minutes` buffer on each side; if the new window collides with an existing window within that buffer, the claim is rejected with `ERR_PICKER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/rto_picker_window_buffered_overlap
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c16b@x.com")
    picker = create_picker(store["id"], window_cooldown_minutes=15)
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=2)
    o1 = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                     [{"product_id": a["id"], "requested_qty": 1}])
    o2 = place_order(store["id"], customer["id"], slot["id"], get_slot_version(slot["id"]),
                     [{"product_id": a["id"], "requested_qty": 1}])
    ph = make_picker_headers(picker["id"])
    validate_success(
        api.claim_order(o1["id"],
                        {"window_start": "2026-06-15T07:00:00Z",
                         "window_end": "2026-06-15T07:45:00Z"}, ph))
    # Second window starts 30 min after the first ends -> well beyond the 15-min buffer.
    data = validate_success(
        api.claim_order(o2["id"],
                        {"window_start": "2026-06-15T08:15:00Z",
                         "window_end": "2026-06-15T09:00:00Z"}, ph))
    assert data["fulfillment_status"] == "PICKING"


def test_slot_count_conservation_place_then_cancel(api):
    """PRD §2.6: "When an order against the slot is cancelled, `booked_count` decreases by one, and if the slot was `FULL` and `booked_count` is now below `capacity` it transitions `FULL → OPEN`."
    PRD §3.8: "the slot's `booked_count` decreases by one and the slot's `version` increases by one, and if the slot was `FULL` it returns to `OPEN`."

    Design: Difficulty/compensating_invariant/ci_slot_capacity_conservation
    """
    store = create_store(ebt_enabled=True)
    customer = create_customer(email="c17@x.com")
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    order = place_order(store["id"], customer["id"], slot["id"], slot["version"],
                        [{"product_id": a["id"], "requested_qty": 1}])  # booked 1, FULL
    cancelled = validate_success(api.cancel_order(order["id"], make_customer_headers(customer["id"])))
    assert cancelled["fulfillment_status"] == "CANCELLED"

    slot_after = validate_success(api.get_slot(slot["id"], OPS))
    assert slot_after["booked_count"] == 0, "compensating cancel restores count"
    assert slot_after["status"] == "OPEN"


def test_slot_count_conservation_freed_capacity_reusable(api):
    """PRD §2.6: "Its `booked_count` is the number of orders referencing the slot whose `fulfillment_status` is one of `PLACED`, `PICKING`, `STAGED`, or `HANDED_OFF`; cancelled orders do not count toward it."
    PRD §2.6: "When an order against the slot is cancelled, `booked_count` decreases by one, and if the slot was `FULL` and `booked_count` is now below `capacity` it transitions `FULL → OPEN`."

    Design: Difficulty/compensating_invariant/ci_slot_capacity_conservation
    """
    store = create_store(ebt_enabled=True)
    c1 = create_customer(email="c17b1@x.com")
    c2 = create_customer(email="c17b2@x.com")
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    o1 = place_order(store["id"], c1["id"], slot["id"], slot["version"],
                     [{"product_id": a["id"], "requested_qty": 1}])  # FULL
    validate_success(api.cancel_order(o1["id"], make_customer_headers(c1["id"])))

    freed = validate_success(api.get_slot(slot["id"], OPS))
    assert freed["booked_count"] == 0, "cancelled order does not count"
    assert freed["status"] == "OPEN"
    # The freed unit of capacity is reusable by a fresh placement.
    o2 = place_order(store["id"], c2["id"], slot["id"], freed["version"],
                     [{"product_id": a["id"], "requested_qty": 1}])
    assert o2["fulfillment_status"] == "PLACED"
    reused = validate_success(api.get_slot(slot["id"], OPS))
    assert reused["booked_count"] == 1, "exactly the count of non-cancelled orders"


def test_slot_rebook_stale_version_rejected(api):
    """PRD §2.8: "The server compares it against the slot's current `version`; if they do not match, the placement is rejected with `ERR_SLOT_VERSION_STALE` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_slot_rebook_stale_version
    """
    store = create_store()
    c1 = create_customer(email="cc27a@x.com")
    c2 = create_customer(email="cc27b@x.com")
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=2)
    v0 = slot["version"]
    place_order(store["id"], c1["id"], slot["id"], v0,
                [{"product_id": a["id"], "requested_qty": 1}])  # slot.version -> v0+1

    # Second placement still carrying the pre-booking version v0 is stale.
    resp = api.create_order(
        {"store_id": store["id"], "customer_id": c2["id"], "slot_id": slot["id"],
         "expected_slot_version": v0,
         "lines": [{"product_id": a["id"], "requested_qty": 1}]},
        make_customer_headers(c2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SLOT_VERSION_STALE.value, 412)


def test_slot_version_increments_each_placement(api):
    """PRD §3.2: "increases the slot's `booked_count` by one and increments the slot's `version` by one (flipping the slot to `FULL` if `booked_count` now equals `capacity`)."

    Design: Corner/cross_cutting_complexity_layers/occ_slot_version_increments_each_placement
    """
    store = create_store()
    c1 = create_customer(email="cc28a@x.com")
    c2 = create_customer(email="cc28b@x.com")
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=3)  # version 1
    place_order(store["id"], c1["id"], slot["id"], slot["version"],
                [{"product_id": a["id"], "requested_qty": 1}])  # version -> 2
    v1 = get_slot_version(slot["id"])
    assert v1 == 2

    resp = api.create_order(
        {"store_id": store["id"], "customer_id": c2["id"], "slot_id": slot["id"],
         "expected_slot_version": v1,
         "lines": [{"product_id": a["id"], "requested_qty": 1}]},
        make_customer_headers(c2["id"]),
    )
    validate_success(resp, 201)
    slot_after = validate_success(api.get_slot(slot["id"], OPS))
    assert slot_after["booked_count"] == 2
    assert slot_after["version"] == 3


def test_list_orders_pagination_envelope(api):
    """PRD §2.3: "Each list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more` inside the envelope's `meta` object, where `total_count` is the number of matching resources before pagination and `has_more` indicates whether further pages remain."

    Design: Corner/endpoints/ep_list_orders_pagination_envelope
    """
    store = create_store()
    customer = create_customer(email="cc17@x.com")
    a = create_product(store["id"], sku="A", name="A", unit_price_cents=349)
    slot = create_slot(store["id"], capacity=1)
    place_order(store["id"], customer["id"], slot["id"], slot["version"],
                [{"product_id": a["id"], "requested_qty": 1}])

    data, meta = validate_paginated(api.list_orders(OPS, params={"store_id": store["id"]}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
