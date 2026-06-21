"""Kitting: requirement computation, shortage gating, the cancel compensation
invariant, and FIFO consumed-material costing.

Covers queue-B corner instances on kit-required-qty, kit shortage, FK resolution,
and queue-A difficulty instances on dual-variant material cost, FIFO straddle
ordering, the kit-zero-shortage boundary, and the kit-then-cancel conservation
invariant.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
)
import test_helpers.fixtures as fx
import test_helpers.factories as f

PE = TEST_USERS["process_engineer_headers"]
PP = TEST_USERS["production_planner_headers"]


# ---------------------------------------------------------------------------
# Required-qty computation (queue B)
# ---------------------------------------------------------------------------

def test_kit_required_qty_sums_multi_line_same_part(api):
    """PRD §3.5: "the `required_qty` is computed by summing `qty_per_assembly` across
    every non-do-not-place line carrying that part (a part may appear on more than one
    line) to obtain the per-assembly placement count, then multiplying that
    per-assembly count by the work order's `planned_qty`. Do-not-place lines
    contribute nothing and create no kit requirement."

    Design: Corner/calculations/kit_required_qty_multi_line_same_part_summed
    """
    part = fx.create_part(standard_cost_cents=10)
    avl = fx.create_approved_avl(part["id"])
    fx.receive_one_lot(avl["id"], avl["version"], received_qty=100, unit_cost_cents=10)

    bom = fx.create_draft_bom()
    fx.add_line(bom["id"], part["id"], ref_designators=["R1", "R2"], qty_per_assembly=2)
    fx.add_line(bom["id"], part["id"], ref_designators=["R3", "R4", "R5"], qty_per_assembly=3)
    fx.add_line(bom["id"], part["id"], ref_designators=["R9"], qty_per_assembly=1, is_dnp=True)
    get_success_data(api.release_bom(bom["id"], PE))

    wo = fx.create_work_order(bom["id"], planned_qty=4)
    kitted = validate_success(api.kit_work_order(wo["id"], PP))
    assert kitted["kit_shortage_count"] == 0, kitted

    reqs, _meta = validate_paginated(
        api.list_all_kit_requirements(PP, params={"work_order_id": wo["id"]}))
    matching = [r for r in reqs if r["part_id"] == part["id"]]
    assert len(matching) == 1, f"expected one merged KitRequirement, got {matching}"
    assert matching[0]["required_qty"] == 20, matching[0]


# ---------------------------------------------------------------------------
# Shortage gating boundary (queue B + queue A)
# ---------------------------------------------------------------------------

def test_kit_shortage_when_available_below_required(api):
    """PRD §3.5: "If any requirement cannot be fully reserved — that is, if
    `kit_shortage_count` is greater than zero — the work order remains `PLANNED` and
    the request is rejected with `ERR_KIT_SHORTAGE` (HTTP 409); only when no
    requirement is short does the work order transition from `PLANNED` to `KITTED`."

    Design: Corner/validations/kit_shortage_when_available_below_required
    """
    part, _v, _a, _lot = fx.setup_part_with_stock(received_qty=1, unit_cost_cents=10,
                                                  standard_cost_cents=10)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=1)
    wo = fx.create_work_order(bom["id"], planned_qty=2)  # required 2 > available 1
    validate_error(api.kit_work_order(wo["id"], PP), ApiErrorId.ERR_KIT_SHORTAGE.value)
    fetched = validate_success(api.get_work_order(wo["id"], PP))
    assert fetched["status"] == "PLANNED", fetched


def test_kit_exactly_at_required_succeeds(api):
    """PRD §3.5: "only when no requirement is short does the work order transition
    from `PLANNED` to `KITTED`."
    PRD §3.5: "setting its `status` to `RESERVED` when the requirement is fully covered
    or `SHORT` when the available stock is less than the `required_qty`."

    Boundary: available exactly equal to required (4 == 4) leaves the SHORT set empty.

    Design: Difficulty/boundary_precision_check/kit_zero_shortage_empty_short_set_succeeds
    """
    part, _v, _a, _lot = fx.setup_part_with_stock(received_qty=4, unit_cost_cents=20,
                                                  standard_cost_cents=20)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=2,
                                             ref_designators=["R1", "R2"])
    wo = fx.create_work_order(bom["id"], planned_qty=2)  # required exactly 4
    kitted = validate_success(api.kit_work_order(wo["id"], PP))
    assert kitted["kit_shortage_count"] == 0, kitted
    assert kitted["status"] == "KITTED", kitted


def test_kit_one_unit_short_rejected(api):
    """PRD §3.5: "If any requirement cannot be fully reserved — that is, if
    `kit_shortage_count` is greater than zero — the work order remains `PLANNED` and
    the request is rejected with `ERR_KIT_SHORTAGE` (HTTP 409); only when no
    requirement is short does the work order transition from `PLANNED` to `KITTED`."

    Boundary: available one unit below required (4 needed, 3 stocked) is rejected.

    Design: Difficulty/boundary_precision_check/kit_zero_shortage_empty_short_set_succeeds
    """
    part, _v, _a, _lot = fx.setup_part_with_stock(received_qty=3, unit_cost_cents=20,
                                                  standard_cost_cents=20)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=2,
                                             ref_designators=["R1", "R2"])
    wo = fx.create_work_order(bom["id"], planned_qty=2)  # required 4 > available 3
    validate_error(api.kit_work_order(wo["id"], PP), ApiErrorId.ERR_KIT_SHORTAGE.value)


# ---------------------------------------------------------------------------
# Dual-variant material cost: consumed-actual vs planned-standard (queue A)
# ---------------------------------------------------------------------------

def test_consumed_actual_cost_differs_from_standard(api):
    """PRD §3.6: "The work order's `material_cost_cents` is the sum, over every lot
    draw, of the quantity drawn in that segment multiplied by that lot's
    `unit_cost_cents`; because every term is an integer-cent product, the sum is exact
    and no rounding is applied. This consumed-actual cost is distinct from the planning
    estimate that could be formed at kitting time, which would instead value each
    requirement's `required_qty` at the part's `standard_cost_cents`".

    Design: Difficulty/dual_variant_calc/work_order_planned_vs_consumed_material_cost
    """
    # Part std cost 50, lot of 100 @ 40; BOM qty_per_assembly 2, planned 2 -> required 4.
    part = fx.create_part(standard_cost_cents=50)
    avl = fx.create_approved_avl(part["id"])
    lot = fx.receive_one_lot(avl["id"], avl["version"], received_qty=100, unit_cost_cents=40)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=2,
                                             ref_designators=["R1", "R2"])
    wo = fx.create_kitted_work_order(part["id"], bom["id"], planned_qty=2)
    fx.setup_kitted_for_start(bom["id"], wo["id"])
    started = validate_success(api.start_work_order(wo["id"], PP))
    assert started["material_cost_cents"] == 160, started  # 4 * 40 (actual)
    assert started["material_cost_cents"] != 200, started  # 4 * 50 (standard)


def test_consumed_actual_cost_depletes_lot_correctly(api):
    """PRD §3.6: "Starting charges each kit requirement's `consumed_qty` against the
    part's lots in first-in-first-out order ... decrementing each drawn lot's
    `remaining_qty`".

    Design: Difficulty/dual_variant_calc/work_order_planned_vs_consumed_material_cost
    """
    part = fx.create_part(standard_cost_cents=50)
    avl = fx.create_approved_avl(part["id"])
    lot = fx.receive_one_lot(avl["id"], avl["version"], received_qty=100, unit_cost_cents=40)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=2,
                                             ref_designators=["R1", "R2"])
    wo = fx.create_kitted_work_order(part["id"], bom["id"], planned_qty=2)
    fx.setup_kitted_for_start(bom["id"], wo["id"])
    get_success_data(api.start_work_order(wo["id"], PP))
    fetched_lot = validate_success(api.get_inventory_lot(lot["id"], PP))
    assert fetched_lot["remaining_qty"] == 96, fetched_lot  # 100 - 4


# ---------------------------------------------------------------------------
# FIFO straddle ordering (queue A: combinatorial_formula mode b)
# ---------------------------------------------------------------------------

def _setup_two_lot_fifo(api):
    """Part with LOT-OLD (qty 50 @ 40, received 2026-01-02) then LOT-NEW (qty 100 @ 60,
    received 2026-01-05). BOM line qty_per_assembly 3; WO planned 30 -> required 90."""
    part = fx.create_part(standard_cost_cents=50)
    avl = fx.create_approved_avl(part["id"])
    fx.receive_one_lot(avl["id"], avl["version"], lot_code="LOT-OLD", received_qty=50,
                       unit_cost_cents=40, received_at="2026-01-02T00:00:00.000Z")
    current = validate_success(api.get_avl_entry(avl["id"], PP))
    lot_new = fx.receive_one_lot(avl["id"], current["version"], lot_code="LOT-NEW",
                                 received_qty=100, unit_cost_cents=60,
                                 received_at="2026-01-05T00:00:00.000Z")
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=3,
                                             ref_designators=["R1", "R2", "R3"])
    wo = fx.create_kitted_work_order(part["id"], bom["id"], planned_qty=30)
    fx.setup_kitted_for_start(bom["id"], wo["id"])  # PRD §3.6: start requires SETUP
    return part, lot_new, wo


def test_fifo_straddle_cost_is_order_defined(api):
    """PRD §3.6: "Lot draws are taken in the pinned order — by `received_at` ascending,
    tie-broken by `created_at` ascending — and a single requirement may straddle
    several lots, with each straddle segment treated as a separate draw. The work
    order's `material_cost_cents` is the sum, over every lot draw, of the quantity
    drawn in that segment multiplied by that lot's `unit_cost_cents`".

    Required 90 draws 50 from the older lot (@40) then 40 from the newer (@60):
    50*40 + 40*60 == 4400.

    Design: Difficulty/combinatorial_formula/material_cost_fifo_straddle_order_mode_b
    """
    _part, _lot_new, wo = _setup_two_lot_fifo(api)
    started = validate_success(api.start_work_order(wo["id"], PP))
    assert started["material_cost_cents"] == 4400, started


def test_fifo_straddle_leaves_newer_lot_remaining(api):
    """PRD §3.6: "Starting charges each kit requirement's `consumed_qty` against the
    part's lots in first-in-first-out order — lots ordered by `received_at` ascending,
    with `created_at` ascending as the tie-break — decrementing each drawn lot's
    `remaining_qty`".

    The older lot (50) is consumed first; only 40 is drawn from the newer 100-qty lot,
    leaving 60.

    Design: Difficulty/combinatorial_formula/material_cost_fifo_straddle_order_mode_b
    """
    _part, lot_new, wo = _setup_two_lot_fifo(api)
    get_success_data(api.start_work_order(wo["id"], PP))
    fetched = validate_success(api.get_inventory_lot(lot_new["id"], PP))
    assert fetched["remaining_qty"] == 60, fetched


# ---------------------------------------------------------------------------
# Kit-then-cancel conservation invariant (queue A: compensating_invariant)
# ---------------------------------------------------------------------------

def test_cancel_kitted_restores_available_qty(api):
    """PRD §3.5: "Cancelling a `KITTED` work order additionally compensates the
    reservations it holds: every kit requirement in `RESERVED` status is set to
    `RELEASED` with its `reserved_qty` returned to zero, and the affected parts'
    `available_qty` is recomputed before the work order moves to `CANCELLED`."

    Forward: kit reserves 4 of a 10-stock part (available -> 6); compensating cancel
    must restore available_qty to the pre-kit value of 10 with no drift.

    Design: Difficulty/compensating_invariant/kit_then_cancel_conserves_part_available_qty
    """
    part, _v, _a, _lot = fx.setup_part_with_stock(received_qty=10, unit_cost_cents=20,
                                                  standard_cost_cents=20)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=2,
                                             ref_designators=["R1", "R2"])
    wo = fx.create_kitted_work_order(part["id"], bom["id"], planned_qty=2)
    after_kit = validate_success(api.get_part(part["id"], PP))
    assert after_kit["available_qty"] == 6, after_kit  # 10 - reserved 4

    cancelled = validate_success(api.cancel_work_order(wo["id"], PP))
    assert cancelled["status"] == "CANCELLED", cancelled
    after_cancel = validate_success(api.get_part(part["id"], PP))
    assert after_cancel["available_qty"] == 10, after_cancel


def test_cancel_kitted_releases_requirement(api):
    """PRD §3.5: "every kit requirement in `RESERVED` status is set to `RELEASED` with
    its `reserved_qty` returned to zero, and the affected parts' `available_qty` is
    recomputed before the work order moves to `CANCELLED`."

    Design: Difficulty/compensating_invariant/kit_then_cancel_conserves_part_available_qty
    """
    part, _v, _a, _lot = fx.setup_part_with_stock(received_qty=10, unit_cost_cents=20,
                                                  standard_cost_cents=20)
    bom = fx.create_released_bom_single_line(part["id"], qty_per_assembly=2,
                                             ref_designators=["R1", "R2"])
    wo = fx.create_kitted_work_order(part["id"], bom["id"], planned_qty=2)
    get_success_data(api.cancel_work_order(wo["id"], PP))
    reqs, _meta = validate_paginated(
        api.list_all_kit_requirements(PP, params={"work_order_id": wo["id"]}))
    matching = [r for r in reqs if r["part_id"] == part["id"]]
    assert len(matching) == 1, matching
    assert matching[0]["status"] == "RELEASED", matching[0]
    assert matching[0]["reserved_qty"] == 0, matching[0]


# ---------------------------------------------------------------------------
# FK resolution on work-order creation (queue B)
# ---------------------------------------------------------------------------

def test_create_work_order_unknown_bom_rejected(api):
    """PRD §2.7: "every foreign-key reference supplied in the request body must
    resolve to an existing record; an unresolved body reference fails with
    `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/fk_not_found_workorder_bad_bom
    """
    payload = f.create_work_order_payload(NON_EXISTENT_UUID, planned_qty=1)
    validate_error(api.create_work_order(payload, PP), ApiErrorId.ERR_FK_NOT_FOUND.value)
