"""Lot allocation: READY precondition, priority-ordered dual failure, insufficient weight,
and optimistic concurrency on Lot.version."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    set_clock, create_customer, create_product, create_cave, receive_lot,
    create_ready_lot, create_order, add_weight_line, allocate_line, TEST_USERS,
)

SM = TEST_USERS["shop_manager_headers"]
CS = TEST_USERS["counter_staff_headers"]


# ─── cross_entity_state_dependency / allocate_requires_lot_ready ───────────
class TestAllocateRequiresLotReady:
    def _aging_lot_order(self, api):
        set_clock("2026-07-01T00:00:00Z")
        customer = create_customer()
        product = create_product(name="Young Wheel", min_aging_days=120, target_aging_days=180)
        cave = create_cave(name="Cave 13")
        lot = receive_lot(product["id"], cave["id"], 1000)
        set_clock("2026-07-11T00:00:00Z")   # +10 days, still < 120 -> stays AGING
        api.rotate_cave(cave["id"], SM)
        order = create_order(customer["id"], "RETAIL")
        line = add_weight_line(order["id"], product["id"], 100)
        return lot, line

    def test_allocate_aging_lot_rejected(self, api):
        """PRD §3.4: "Allocation requires the owning order to still be `DRAFT` (else
        `ERR_ORDER_NOT_DRAFT`), the target lot to be in `READY` status (else
        `ERR_LOT_NOT_READY`), and the lot's `available_weight_g` to be at least the line's
        `requested_weight_g` (else `ERR_INSUFFICIENT_LOT_WEIGHT`)."

        Design: Difficulty/cross_entity_state_dependency/allocate_requires_lot_ready
        """
        lot, line = self._aging_lot_order(api)
        res = allocate_line(line["id"], lot["id"])
        validate_error(res, "ERR_LOT_NOT_READY")

    def test_line_not_allocated_after_rejection(self, api):
        """PRD §3.4: "On success the line's `lot_id` is set, the line's `reserved_weight_g`
        becomes its requested weight, the lot's `reserved_weight_g` and `available_weight_g`
        are recomputed, and the lot's `version` increments by one."

        Design: Difficulty/cross_entity_state_dependency/allocate_requires_lot_ready
        """
        lot, line = self._aging_lot_order(api)
        allocate_line(line["id"], lot["id"])
        reread = get_success_data(api.get_order_line(line["id"], CS))
        assert reread["lot_id"] is None


# ─── priority_pair_validation_conflict / allocate_cancelled_order_beats_insufficient_weight ──
class TestAllocateCancelledBeatsWeight:
    def _cancelled_order_small_lot(self, api):
        customer = create_customer()
        product = create_product(name="Small Cheese", form="WEDGE")
        cave = create_cave(name="Cave 9")
        lot = create_ready_lot(product["id"], cave["id"], 100)
        order = create_order(customer["id"], "RETAIL")
        line = add_weight_line(order["id"], product["id"], 500)
        api.cancel_order(order["id"], CS)
        return lot, line

    def test_state_error_wins_over_weight_error(self, api):
        """PRD §3.4: "Allocation requires the owning order to still be `DRAFT` (else
        `ERR_ORDER_NOT_DRAFT`), the target lot to be in `READY` status (else
        `ERR_LOT_NOT_READY`), and the lot's `available_weight_g` to be at least the line's
        `requested_weight_g` (else `ERR_INSUFFICIENT_LOT_WEIGHT`)."

        Design: Difficulty/priority_pair_validation_conflict/allocate_cancelled_order_beats_insufficient_weight
        """
        lot, line = self._cancelled_order_small_lot(api)
        res = allocate_line(line["id"], lot["id"])
        validate_error(res, "ERR_ORDER_NOT_DRAFT")

    def test_line_remains_unallocated(self, api):
        """PRD §3.4: "Lines are added to a `DRAFT` order; adding a line to an order that is not
        `DRAFT` is rejected with `ERR_ORDER_NOT_DRAFT`."

        Design: Difficulty/priority_pair_validation_conflict/allocate_cancelled_order_beats_insufficient_weight
        """
        lot, line = self._cancelled_order_small_lot(api)
        allocate_line(line["id"], lot["id"])
        reread = get_success_data(api.get_order_line(line["id"], CS))
        assert reread["lot_id"] is None


# ─── Corner: validations / corner_allocate_insufficient_weight_standalone ──
def test_allocate_insufficient_weight(api):
    """PRD §3.4: "Allocation requires the owning order to still be `DRAFT` (else
    `ERR_ORDER_NOT_DRAFT`), the target lot to be in `READY` status (else `ERR_LOT_NOT_READY`),
    and the lot's `available_weight_g` to be at least the line's `requested_weight_g` (else
    `ERR_INSUFFICIENT_LOT_WEIGHT`)."

    Design: Corner/validations/corner_allocate_insufficient_weight_standalone
    """
    customer = create_customer()
    product = create_product(name="IW Cheese", form="WEDGE")
    cave = create_cave(name="Cave IW")
    lot = create_ready_lot(product["id"], cave["id"], 100)
    order = create_order(customer["id"], "RETAIL")
    line = add_weight_line(order["id"], product["id"], 500)
    res = allocate_line(line["id"], lot["id"])
    validate_error(res, "ERR_INSUFFICIENT_LOT_WEIGHT")


# ─── Corner: cross_cutting / corner_allocate_stale_lot_version_occ ─────────
def test_allocate_stale_lot_version(api):
    """PRD §2.7: "Two strictly sequential allocation calls that reuse the same
    `expected_lot_version` reproduce this rejection deterministically: the first succeeds and
    bumps the version, the second fails the version check."

    Design: Corner/cross_cutting/corner_allocate_stale_lot_version_occ
    """
    customer = create_customer()
    product = create_product(name="OCC Cheese", form="BLOCK")
    cave = create_cave(name="Cave OCC")
    lot = create_ready_lot(product["id"], cave["id"], 1000)
    order = create_order(customer["id"], "RETAIL")
    line1 = add_weight_line(order["id"], product["id"], 300)
    line2 = add_weight_line(order["id"], product["id"], 300)
    stale_version = get_success_data(api.get_lot(lot["id"], CS))["version"]

    first = api.allocate_order_line(
        line1["id"], {"lot_id": lot["id"], "expected_lot_version": stale_version}, CS)
    validate_success(first, 200)

    second = api.allocate_order_line(
        line2["id"], {"lot_id": lot["id"], "expected_lot_version": stale_version}, CS)
    validate_error(second, "ERR_STALE_LOT_VERSION")
    reread = get_success_data(api.get_order_line(line2["id"], CS))
    assert reread["lot_id"] is None


# ─── Corner: cross_cutting / corner_allocate_correct_version_increments ────
def test_allocate_correct_version_reserves_and_increments(api):
    """PRD §3.4: "On success the line's `lot_id` is set, the line's `reserved_weight_g` becomes
    its requested weight, the lot's `reserved_weight_g` and `available_weight_g` are recomputed,
    and the lot's `version` increments by one."

    Design: Corner/cross_cutting/corner_allocate_correct_version_increments
    """
    customer = create_customer()
    product = create_product(name="OK Cheese", form="BLOCK")
    cave = create_cave(name="Cave OK")
    lot = create_ready_lot(product["id"], cave["id"], 1000)
    order = create_order(customer["id"], "RETAIL")
    line = add_weight_line(order["id"], product["id"], 300)

    res = allocate_line(line["id"], lot["id"])
    allocated = validate_success(res, 200)
    assert allocated["lot_id"] == lot["id"]
    assert allocated["reserved_weight_g"] == 300
    lot_after = get_success_data(api.get_lot(lot["id"], CS))
    assert lot_after["reserved_weight_g"] == 300
