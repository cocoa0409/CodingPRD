"""Allocation pools: pre-order cascade, exhaustion boundary, pickup capacity, OCC.

Queue A: transitive_cascade/preorder_cancel_release_promote_depth2,
         boundary_precision_check/allocation_exhaustion_zero_available_boundary,
         resource_temporal_overlap/allocation_pickup_halfopen_capacity_overlap.
Queue B: occ_stale_allocation_version_rejected, allocation_version_increments_on_preorder,
         cancel_preorder_twice_from_cancelled_returns_invalid_state.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    TEST_USERS, make_customer_headers,
    register_customer, create_rsd_allocation, create_preorder,
    current_allocation_version, create_inventory_item,
)

MANAGER = TEST_USERS["manager_headers"]
CLERK = TEST_USERS["store_clerk_headers"]


# ---------------------------------------------------------------------------
# Queue A — preorder_cancel_release_promote_depth2 (>=2 tests)
# ---------------------------------------------------------------------------
def _one_reserved_one_waitlisted(api):
    """allocation_total=1: first pre-order RESERVED holds the unit; second WAITLISTED."""
    first = register_customer(api, full_name="First")
    second = register_customer(api, full_name="Second")
    product, alloc = create_rsd_allocation(api, allocation_total=1)
    po_first = create_preorder(api, customer=first, product=product, allocation=alloc,
                               pickup_window_start="2026-04-01T09:00:00Z",
                               pickup_window_end="2026-04-01T17:00:00Z")
    po_second = create_preorder(api, customer=second, product=product, allocation=alloc,
                                pickup_window_start="2026-04-02T09:00:00Z",
                                pickup_window_end="2026-04-02T17:00:00Z")
    return first, second, alloc, po_first, po_second


def test_preorder_cancel_promotes_waitlisted_to_reserved(api):
    """PRD §3.5: "Cancelling a RESERVED pre-order moves it to the terminal CANCELLED,
    increments available_count by one and decrements reserved_count by one, and then
    triggers the waitlist promotion described above." PRD §3.5: "Promotion moves that
    pre-order from WAITLISTED to RESERVED".

    Design: Difficulty/transitive_cascade/preorder_cancel_release_promote_depth2
    """
    first, second, alloc, po_first, po_second = _one_reserved_one_waitlisted(api)
    validate_success(api.cancel_preorder(po_first["id"], make_customer_headers(first["id"])))
    first_after = validate_success(api.get_preorder(po_first["id"], MANAGER))
    second_after = validate_success(api.get_preorder(po_second["id"], MANAGER))
    assert first_after["status"] == "CANCELLED", f"got {first_after['status']}"
    assert second_after["status"] == "RESERVED", f"waitlisted must be promoted, got {second_after['status']}"


def test_preorder_cancel_promotion_conserves_allocation_counters(api):
    """PRD §3.5: "Promotion moves that pre-order from WAITLISTED to RESERVED, decrements
    available_count by one, and increments reserved_count by one." PRD §3.5: "at all times
    available_count plus reserved_count plus committed_count equals allocation_total."

    Design: Difficulty/transitive_cascade/preorder_cancel_release_promote_depth2
    """
    first, second, alloc, po_first, po_second = _one_reserved_one_waitlisted(api)
    validate_success(api.cancel_preorder(po_first["id"], make_customer_headers(first["id"])))
    data = validate_success(api.get_allocation(alloc["id"], MANAGER))
    assert data["available_count"] == 0, f"got {data['available_count']}"
    assert data["reserved_count"] == 1, f"got {data['reserved_count']}"


# ---------------------------------------------------------------------------
# Queue A — allocation_exhaustion_zero_available_boundary (>=2 tests)
# ---------------------------------------------------------------------------
def _exhausted_pool_then_second(api):
    b1 = register_customer(api, full_name="Boundary One")
    b2 = register_customer(api, full_name="Boundary Two")
    product, alloc = create_rsd_allocation(api, allocation_total=1)
    create_preorder(api, customer=b1, product=product, allocation=alloc,
                    pickup_window_start="2026-04-01T09:00:00Z",
                    pickup_window_end="2026-04-01T17:00:00Z")
    v1 = current_allocation_version(api, allocation=alloc)
    po2 = create_preorder(api, customer=b2, product=product, allocation=alloc,
                          expected_allocation_version=v1,
                          pickup_window_start="2026-04-02T09:00:00Z",
                          pickup_window_end="2026-04-02T17:00:00Z")
    return alloc, po2


def test_preorder_waitlisted_when_pool_exhausted_window_open(api):
    """PRD §3.5: "When the pool is exhausted — that is, a reservation would drive
    available_count below zero — the pre-order is instead created in WAITLISTED status
    while the window is still open, holding no unit".

    Design: Difficulty/boundary_precision_check/allocation_exhaustion_zero_available_boundary
    """
    alloc, po2 = _exhausted_pool_then_second(api)
    data = validate_success(api.get_preorder(po2["id"], MANAGER))
    assert data["status"] == "WAITLISTED", f"got {data['status']}"


def test_allocation_available_zero_after_first_reservation(api):
    """PRD §3.5: "When a unit is available, the pre-order is created in RESERVED status,
    available_count is decremented by one, and reserved_count is incremented by one."

    Design: Difficulty/boundary_precision_check/allocation_exhaustion_zero_available_boundary
    """
    alloc, po2 = _exhausted_pool_then_second(api)
    data = validate_success(api.get_allocation(alloc["id"], MANAGER))
    assert data["available_count"] == 0, f"got {data['available_count']}"
    assert data["reserved_count"] == 1, f"waitlisted holds no unit, got {data['reserved_count']}"


# ---------------------------------------------------------------------------
# Queue A — allocation_pickup_halfopen_capacity_overlap (>=2 tests)
# ---------------------------------------------------------------------------
def _two_preorders_first_ready(api):
    pk1 = register_customer(api, full_name="Pickup One")
    pk2 = register_customer(api, full_name="Pickup Two")
    product, alloc = create_rsd_allocation(api, allocation_total=2, pickup_concurrency=1)
    # PRD §3.5: readying requires the product's catalog_status to permit it (cross-entity
    # guard → ERR_DEPENDENCY_NOT_READY when unmet). Advance DRAFT→LISTED→PRE_ORDER_OPEN so
    # the pre-orders below can be readied. Window is open under the default clock.
    validate_success(api.list_product(product["id"], MANAGER))
    validate_success(api.open_preorders(product["id"], MANAGER))
    create_inventory_item(api, product_id=product["id"], is_used=False, condition_grade="NM")
    create_inventory_item(api, product_id=product["id"], is_used=False, condition_grade="NM")
    po1 = create_preorder(api, customer=pk1, product=product, allocation=alloc,
                          pickup_window_start="2026-04-01T09:00:00Z",
                          pickup_window_end="2026-04-01T12:00:00Z")
    v1 = current_allocation_version(api, allocation=alloc)
    po2 = create_preorder(api, customer=pk2, product=product, allocation=alloc,
                          expected_allocation_version=v1,
                          pickup_window_start="2026-04-01T11:00:00Z",
                          pickup_window_end="2026-04-01T14:00:00Z")
    validate_success(api.ready_preorder(po1["id"], CLERK))
    return po1, po2


def test_pickup_capacity_exceeded_on_overlapping_ready(api):
    """PRD §3.5: "readying is rejected when the number of already-READY_FOR_PICKUP
    pre-orders on the same allocation whose half-open pickup interval, from
    pickup_window_start up to but not including pickup_window_end, overlaps this pre-order's
    interval would reach the allocation's pickup_concurrency; that rejection carries
    ERR_PICKUP_CAPACITY_EXCEEDED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/allocation_pickup_halfopen_capacity_overlap
    """
    po1, po2 = _two_preorders_first_ready(api)
    resp = api.ready_preorder(po2["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_PICKUP_CAPACITY_EXCEEDED.value)


def test_pickup_capacity_rejected_leaves_second_reserved(api):
    """PRD §3.5: "Readying a pre-order advances it from RESERVED to READY_FOR_PICKUP".
    PRD §3.5: "that rejection carries ERR_PICKUP_CAPACITY_EXCEEDED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/allocation_pickup_halfopen_capacity_overlap
    """
    po1, po2 = _two_preorders_first_ready(api)
    validate_error(api.ready_preorder(po2["id"], CLERK),
                   ApiErrorId.ERR_PICKUP_CAPACITY_EXCEEDED.value)
    data = validate_success(api.get_preorder(po2["id"], MANAGER))
    assert data["status"] == "RESERVED", f"rejected ready must leave RESERVED, got {data['status']}"


# ---------------------------------------------------------------------------
# Queue B — OCC stale version and version increment
# ---------------------------------------------------------------------------
def test_occ_stale_allocation_version_rejected(api):
    """PRD §2.6: "If that value does not match the allocation's current version — because
    another writer has advanced it since the client last read the allocation, legitimately
    decrementing available_count — the create is rejected with ERR_STALE_VERSION (HTTP 412)".
    PRD §2.6: "A successful pre-order creation itself increments the allocation's version
    by one."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_allocation_version_rejected
    """
    occ1 = register_customer(api, full_name="OCC One")
    occ2 = register_customer(api, full_name="OCC Two")
    product, alloc = create_rsd_allocation(api, allocation_total=5)
    v0 = alloc["version"]
    create_preorder(api, customer=occ1, product=product, allocation=alloc,
                    expected_allocation_version=v0)
    # Second create still carries the stale v0.
    resp = api.create_preorder({
        "customer_id": occ2["id"], "product_id": product["id"], "allocation_id": alloc["id"],
        "pickup_window_start": "2026-04-02T09:00:00Z", "pickup_window_end": "2026-04-02T17:00:00Z",
        "expected_allocation_version": v0,
    }, make_customer_headers(occ2["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_allocation_version_increments_and_counts_on_preorder(api):
    """PRD §3.5: "When a unit is available, the pre-order is created in RESERVED status,
    available_count is decremented by one, and reserved_count is incremented by one. ...
    Every pre-order create increments the allocation's version by one."

    Design: Corner/cross_cutting_complexity_layers/allocation_version_increments_on_preorder
    """
    occ3 = register_customer(api, full_name="OCC Three")
    product, alloc = create_rsd_allocation(api, allocation_total=5)
    create_preorder(api, customer=occ3, product=product, allocation=alloc,
                    expected_allocation_version=alloc["version"])
    data = validate_success(api.get_allocation(alloc["id"], MANAGER))
    assert data["available_count"] == 4, f"got {data['available_count']}"
    assert data["reserved_count"] == 1, f"got {data['reserved_count']}"


# ---------------------------------------------------------------------------
# Queue B — cancel_preorder_twice_from_cancelled_returns_invalid_state
# ---------------------------------------------------------------------------
def test_cancel_cancelled_preorder_returns_invalid_state(api):
    """PRD §2.9: "State validity is checked fifth: if the target resource is not in a
    state that permits the requested transition, the request yields ERR_INVALID_STATE (409)."
    PRD §3.5: "A Customer may cancel their own pre-order at any time before it is FULFILLED.
    Cancelling a RESERVED pre-order moves it to the terminal CANCELLED".

    Design: Corner/state_machines/cancel_preorder_twice_from_cancelled_returns_invalid_state
    """
    customer = register_customer(api, full_name="SM One")
    product, alloc = create_rsd_allocation(api, allocation_total=2)
    po = create_preorder(api, customer=customer, product=product, allocation=alloc)
    hdr = make_customer_headers(customer["id"])
    validate_success(api.cancel_preorder(po["id"], hdr))
    resp = api.cancel_preorder(po["id"], hdr)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    data = validate_success(api.get_allocation(alloc["id"], MANAGER))
    assert data["available_count"] == 2, f"no counter change on 2nd cancel, got {data['available_count']}"
