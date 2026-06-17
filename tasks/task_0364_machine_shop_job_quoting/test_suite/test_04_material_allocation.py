"""FIFO material waterfall allocation, insufficiency rollback, and conservation.

Translates queue A combinatorial_formula (lot_waterfall mode_a),
compensating_invariant (material conservation via cancel), and queue B
calculations (insufficient_material_rolls_back_allocation).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_approved_quote, create_allocated_work_order, receive_lot,
    create_planned_work_order,
    assert_material_conservation,
    TEST_USERS,
)

ADMIN = TEST_USERS["shop_admin_headers"]
MAT = TEST_USERS["material_controller_headers"]


def test_lot_waterfall_fifo_depletes_earliest_lot_first(api):
    """PRD §3.3: "the server walks the lots in that order; from each lot it draws
    the smaller of the remaining requirement and that lot's qty_remaining. When
    that draw is positive, the server creates a LotAllocation ... it then
    subtracts the drawn amount from the lot's qty_remaining, flipping the lot to
    DEPLETED if its remaining reaches 0."

    Need 11 from lots [4@earlier, 10@later]: draw 4 (earlier depletes) then 7.

    Design: Difficulty/combinatorial_formula/lot_waterfall_fifo_three_input_nonlinear_mode_a
    """
    rfq, pl, quote, ops, wo, lots = create_allocated_work_order(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 12.5, "setup_fee_cents": 8000}],
        qty_ordered=10, qty_started=11,
        lots=[
            {"material_spec": "AL_6061", "qty_received": 4, "unit_cost_cents": 1400,
             "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-A"},
            {"material_spec": "AL_6061", "qty_received": 10, "unit_cost_cents": 1500,
             "received_at": "2026-06-02T00:00:00Z", "heat_number": "H-B"},
        ],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 10, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1500, "scrap_allowance_pct": 5},
        customer_id="CUST-4",
    )
    lot_a = validate_success(api.get_material_lot(lots[0]["id"], MAT), 200)
    assert lot_a["qty_remaining"] == 0
    assert lot_a["status"] == "DEPLETED"


def test_lot_waterfall_fifo_partial_draw_on_later_lot(api):
    """PRD §3.3: "from each lot it draws the smaller of the remaining requirement
    and that lot's qty_remaining ... The requirement is reduced by the amount
    drawn, and the walk stops as soon as the requirement reaches 0."
    PRD §3.3: "On full success the work order's material_allocated is set true".

    After drawing 4 from the earlier lot, 7 of 10 are drawn from the later lot,
    leaving 3.

    Design: Difficulty/combinatorial_formula/lot_waterfall_fifo_three_input_nonlinear_mode_a
    """
    rfq, pl, quote, ops, wo, lots = create_allocated_work_order(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 12.5, "setup_fee_cents": 8000}],
        qty_ordered=10, qty_started=11,
        lots=[
            {"material_spec": "AL_6061", "qty_received": 4, "unit_cost_cents": 1400,
             "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-A"},
            {"material_spec": "AL_6061", "qty_received": 10, "unit_cost_cents": 1500,
             "received_at": "2026-06-02T00:00:00Z", "heat_number": "H-B"},
        ],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 10, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1500, "scrap_allowance_pct": 5},
        customer_id="CUST-4b",
    )
    lot_b = validate_success(api.get_material_lot(lots[1]["id"], MAT), 200)
    assert lot_b["qty_remaining"] == 3
    assert wo["material_allocated"] is True


def test_insufficient_material_rolls_back_allocation(api):
    """PRD §3.3: "If the walk exhausts every available lot of the spec and the
    requirement is still above 0, the entire allocation for this call is rolled
    back — no allocation rows survive and no lot quantities are changed — and the
    request is refused with ERR_INSUFFICIENT_MATERIAL."

    Design: Corner/calculations/insufficient_material_rolls_back_allocation
    """
    rfq, pl, quote, ops = create_approved_quote(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 4.0, "setup_fee_cents": 1000}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 20, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="C-24",
    )
    lot_a = receive_lot("AL_6061", 4, 1000, "2026-06-01T00:00:00Z", heat_number="H-X1")
    receive_lot("AL_6061", 10, 1000, "2026-06-02T00:00:00Z", heat_number="H-X2")
    wo = create_planned_work_order(quote["id"], pl["id"], qty_ordered=20, qty_started=20)
    res = api.allocate_material(wo["id"], MAT)
    validate_error(res, "ERR_INSUFFICIENT_MATERIAL")
    lot_a_after = validate_success(api.get_material_lot(lot_a["id"], MAT), 200)
    assert lot_a_after["qty_remaining"] == 4
    wo_after = validate_success(api.get_work_order(wo["id"], ADMIN), 200)
    assert wo_after["material_allocated"] is False


def test_material_conservation_after_allocate(api):
    """PRD §3.3: "qty_remaining is the received quantity minus the sum of all
    active allocations drawn from it".

    Invariant: sum(ACTIVE allocations) + qty_remaining == qty_received holds
    after allocation. A single lot of 10 with 6 allocated leaves 4 remaining.

    Design: Difficulty/compensating_invariant/material_conservation_allocate_then_void_via_cancel
    """
    rfq, pl, quote, ops, wo, lots = create_allocated_work_order(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 5.0, "setup_fee_cents": 2000}],
        qty_ordered=6, qty_started=6,
        lots=[{"material_spec": "AL_6061", "qty_received": 10, "unit_cost_cents": 1000,
               "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-IA"}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 6, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="CUST-17",
    )
    lot = validate_success(api.get_material_lot(lots[0]["id"], MAT), 200)
    assert lot["qty_remaining"] == 4
    assert_material_conservation(lot, active_allocations_qty=6)


def test_material_conservation_restored_after_cancel_void(api):
    """PRD §3.3: "every ACTIVE lot allocation of the work order is voided to
    VOIDED, each one restoring its qty_allocated to its source lot's
    qty_remaining ... material_allocated is reset to false."

    After release-then-cancel, the lot returns to its full received quantity and
    the WO's material_allocated is false — no unit drift.

    Design: Difficulty/compensating_invariant/material_conservation_allocate_then_void_via_cancel
    """
    from test_helpers import create_released_work_order
    rfq, pl, quote, ops, wo, lots = create_released_work_order(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 5.0, "setup_fee_cents": 2000}],
        qty_ordered=6, qty_started=6,
        lots=[{"material_spec": "AL_6061", "qty_received": 10, "unit_cost_cents": 1000,
               "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-IA2"}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 6, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="CUST-17b",
    )
    validate_success(api.cancel_work_order(wo["id"], ADMIN), 200)
    lot = validate_success(api.get_material_lot(lots[0]["id"], MAT), 200)
    assert lot["qty_remaining"] == 10
    assert lot["qty_received"] == 10
    wo_after = validate_success(api.get_work_order(wo["id"], ADMIN), 200)
    assert wo_after["material_allocated"] is False
