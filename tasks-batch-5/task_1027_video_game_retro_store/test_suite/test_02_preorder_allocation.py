"""Pre-order creation, allocation resolution, embargo gate, and OCC.

Difficulty: boundary_precision_check (empty pool), cross_entity_state_dependency
(release gate). Corner: validations, endpoints, cross_cutting_complexity_layers.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_pre_order, assert_product_stock,
    create_pre_order_payload, TEST_USERS,
    create_member, setup_released_pool, setup_embargoed_pool,
    place_pre_order, get_stock_version, create_product, create_stock, release_stock,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── Difficulty: preorder_on_empty_pool_is_waitlisted ─────────────────────
def test_empty_pool_new_preorder_is_waitlisted(api):
    """PRD §3.3: "if the referenced pool is RELEASED and its available_count is at least
    1, the pre-order is resolved to ALLOCATED (PENDING → ALLOCATED); otherwise — if the
    pool is still EMBARGOED or its available_count is zero — it is resolved to WAITLISTED
    (PENDING → WAITLISTED)."

    Design: Difficulty/boundary_precision_check/preorder_on_empty_pool_is_waitlisted
    """
    member_a = create_member(full_name="Ann")
    member_c = create_member(full_name="Cam")
    product, stock = setup_released_pool(unit_price_cents=8000, deposit_cents=2000, total_count=1)
    po_a = place_pre_order(member_a["id"], stock["id"])
    assert po_a["allocation_status"] == "ALLOCATED"

    po_c = place_pre_order(member_c["id"], stock["id"])
    assert po_c["allocation_status"] == "WAITLISTED"


def test_empty_pool_holder_allocated_available_zero(api):
    """PRD §3.3: "Resolving to ALLOCATED creates a companion Allocation resource in the
    HELD state ... it decrements the pool's available_count by one and increments
    allocated_count by one."

    Design: Difficulty/boundary_precision_check/preorder_on_empty_pool_is_waitlisted
    """
    member_a = create_member(full_name="Ann")
    member_c = create_member(full_name="Cam")
    product, stock = setup_released_pool(unit_price_cents=8000, deposit_cents=2000, total_count=1)
    po_a = place_pre_order(member_a["id"], stock["id"])
    place_pre_order(member_c["id"], stock["id"])

    assert po_a["allocation_status"] == "ALLOCATED"
    fresh = validate_success(api.get_product_stock(stock["id"], CLERK), 200)
    assert fresh["available_count"] == 0
    assert_product_stock(fresh)


# ─── Difficulty: preorder_allocation_gated_by_stock_release_state ──────────
def test_embargoed_pool_preorder_waitlisted(api):
    """PRD §3.2: "only a RELEASED pool may grant an ALLOCATED unit, whereas while a pool
    is EMBARGOED every new pre-order is placed on the waitlist."
    PRD §3.3: "otherwise — if the pool is still EMBARGOED or its available_count is zero
    — it is resolved to WAITLISTED (PENDING → WAITLISTED)."

    Design: Difficulty/cross_entity_state_dependency/preorder_allocation_gated_by_stock_release_state
    """
    member = create_member(full_name="Emb")
    product, stock = setup_embargoed_pool(unit_price_cents=6000, deposit_cents=1500, total_count=2)
    po = place_pre_order(member["id"], stock["id"])
    assert po["allocation_status"] == "WAITLISTED"


def test_embargoed_pool_units_stay_available(api):
    """PRD §3.3: "Resolving to WAITLISTED grants no unit and moves no counts, but still
    increments the pool's version by one."
    PRD §3.2: "On creation, available_count equals total_count, allocated_count and
    fulfilled_count are zero, and the pool's release_state begins at EMBARGOED."

    Design: Difficulty/cross_entity_state_dependency/preorder_allocation_gated_by_stock_release_state
    """
    member = create_member(full_name="Emb")
    product, stock = setup_embargoed_pool(unit_price_cents=6000, deposit_cents=1500, total_count=2)
    place_pre_order(member["id"], stock["id"])
    fresh = validate_success(api.get_product_stock(stock["id"], CLERK), 200)
    assert fresh["available_count"] == 2
    assert fresh["release_state"] == "EMBARGOED"


# ─── Corner: validations / second active pre-order ────────────────────────
def test_second_active_preorder_same_pool_rejected(api):
    """PRD §3.3: "if the member already has a non-terminal pre-order — one whose
    allocation_status is PENDING, WAITLISTED, or ALLOCATED — for the same
    product_stock_id, the request is rejected with ERR_ONE_ACTIVE_PREORDER (HTTP 409)."

    Design: Corner/validations/second_active_preorder_same_pool_returns_409
    """
    member = create_member(full_name="Dup")
    product, stock = setup_embargoed_pool(unit_price_cents=6000, deposit_cents=1000, total_count=3)
    place_pre_order(member["id"], stock["id"])

    stale_free_version = get_stock_version(stock["id"])
    payload = create_pre_order_payload(member["id"], stock["id"], stale_free_version)
    res = api.create_pre_order(payload, CLERK)
    validate_error(res, "ERR_ONE_ACTIVE_PREORDER", expected_status=409)


# ─── Corner: endpoints / list by member ───────────────────────────────────
def test_list_preorders_filtered_by_member(api):
    """PRD §2.5: "Filtered list endpoints additionally accept optional query parameters
    that narrow the result set: pre-orders may be filtered by member_id or
    product_stock_id."

    Design: Corner/endpoints/list_preorders_filtered_by_member
    """
    member = create_member(full_name="Lst")
    product, stock = setup_embargoed_pool(unit_price_cents=6000, deposit_cents=1000, total_count=2)
    po = place_pre_order(member["id"], stock["id"])

    res = api.list_pre_orders(CLERK, params={"member_id": member["id"]})
    data, meta = validate_paginated(res)
    assert any(p["id"] == po["id"] for p in data)


# ─── Corner: cross_cutting / OCC stale version ────────────────────────────
def test_preorder_create_stale_stock_version_rejected(api):
    """PRD §2.7: "If expected_product_stock_version does not match the pool's current
    version, the create is rejected with ERR_STALE_VERSION (HTTP 412), preventing the
    client from resolving a pre-order against stock it has not actually observed."

    Design: Corner/cross_cutting_complexity_layers/preorder_create_stale_stock_version_returns_412
    """
    member_a = create_member(full_name="Occ1")
    member_b = create_member(full_name="Occ2")
    product, stock = setup_released_pool(unit_price_cents=6000, deposit_cents=1000, total_count=3)
    v1 = stock["version"]
    place_pre_order(member_a["id"], stock["id"], expected_version=v1)  # bumps version

    payload = create_pre_order_payload(member_b["id"], stock["id"], v1)
    res = api.create_pre_order(payload, CLERK)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_stock_version_increments_on_release(api):
    """PRD §2.4: "version: an integer that starts at its initial value on creation and
    increments by exactly one on every mutation."
    PRD §3.2: "transitioning the pool EMBARGOED → RELEASED; this action increments the
    pool's version by one."

    Design: Corner/cross_cutting_complexity_layers/stock_version_increments_on_release
    """
    product = create_product()
    stock = create_stock(product["id"], unit_price_cents=3000, deposit_cents=500, total_count=2)
    v1 = stock["version"]
    released = release_stock(stock["id"])
    assert released["version"] == v1 + 1
    assert released["release_state"] == "RELEASED"
