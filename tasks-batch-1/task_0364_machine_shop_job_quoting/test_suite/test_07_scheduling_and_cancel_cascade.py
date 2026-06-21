"""Machine-slot booking (half-open overlap), op completion, and WO-cancel cascade.

Translates queue A resource_temporal_overlap (machine_slot half-open: adjacent
OK + overlap rejected) and a second buffered-station test, transitive_cascade
(wo_cancel depth-3), plus queue B validations/errors slot/op instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_released_work_order, create_in_process_work_order,
    book_slot, create_station, open_inspection,
    create_machine_slot_payload, create_inspection_payload,
    TEST_USERS,
)

SCHED = TEST_USERS["scheduler_headers"]
ADMIN = TEST_USERS["shop_admin_headers"]
INSP = TEST_USERS["inspector_headers"]


def _released_wo_two_mill_ops(customer_id):
    """RELEASED WO with two PLANNED MILL_3AX ops on the same quote. Returns
    (rfq, pl, quote, ops, wo)."""
    rfq, pl, quote, ops, wo, lots = create_released_work_order(
        routing_ops=[
            {"seq": 1, "machine_class": "MILL_3AX", "estimated_cycle_min": 5.0, "setup_fee_cents": 2000},
            {"seq": 2, "machine_class": "MILL_3AX", "estimated_cycle_min": 5.0, "setup_fee_cents": 2000},
        ],
        qty_ordered=2, qty_started=2,
        lots=[{"material_spec": "AL_6061", "qty_received": 2, "unit_cost_cents": 1000,
               "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-" + customer_id}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 2, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id=customer_id,
    )
    return rfq, pl, quote, ops, wo


def test_machine_slot_adjacent_interval_accepted(api):
    """PRD §3.4: "abutting intervals, where one ends exactly at the minute the
    next begins, do not conflict."

    Existing BOOKED [0,160) on 'VF2-X'; a new [160,200) is adjacent and accepted.

    Design: Difficulty/resource_temporal_overlap/machine_slot_half_open_overlap_vs_adjacent_ok
    """
    rfq, pl, quote, ops, wo = _released_wo_two_mill_ops("SlotAdj")
    book_slot("MILL_3AX", "VF2-X", ops[0]["id"], 0, 160)
    res = api.create_machine_slot(
        create_machine_slot_payload("MILL_3AX", "VF2-X", ops[1]["id"], 160, 200), SCHED)
    slot = validate_success(res, 201)
    assert slot["status"] == "BOOKED"


def test_machine_slot_overlap_rejected(api):
    """PRD §3.4: "A booking that would overlap any existing BOOKED slot on the
    same machine is refused with ERR_SLOT_CONFLICT."

    Existing BOOKED [0,160) on 'VF2-X'; a new [150,180) overlaps.

    Design: Difficulty/resource_temporal_overlap/machine_slot_half_open_overlap_vs_adjacent_ok
    """
    rfq, pl, quote, ops, wo = _released_wo_two_mill_ops("SlotA")
    book_slot("MILL_3AX", "VF2-X", ops[0]["id"], 0, 160)
    res = api.create_machine_slot(
        create_machine_slot_payload("MILL_3AX", "VF2-X", ops[1]["id"], 150, 180), SCHED)
    validate_error(res, "ERR_SLOT_CONFLICT")


def test_inspection_station_buffer_makes_nonadjacent_windows_conflict(api):
    """PRD §3.5: "an optional buffer_min cleanup-and-calibration buffer in minutes
    that defaults to 15 and is applied on both sides of every booking window on
    that station."
    PRD §3.5: "the requested window, expanded by the station's buffer_min on both
    sides, must not overlap any existing window ... an overlap is refused with
    ERR_STATION_CONFLICT."

    Second buffered-station illustration: existing [100,160] buffered to
    [85,175]; a new [170,190] (which would not touch the raw [100,160]) still
    collides because of the 15-minute buffer.

    Design: Difficulty/resource_temporal_overlap/inspection_station_buffered_closed_overlap
    """
    rfq, pl, quote, ops, wo, lots, slots = create_in_process_work_order(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 5.0, "setup_fee_cents": 2000}],
        qty_ordered=4, qty_started=4,
        lots=[{"material_spec": "AL_6061", "qty_received": 4, "unit_cost_cents": 1000,
               "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-StB"}],
        slot_specs=[{"machine_class": "MILL_3AX", "machine_code": "VF2-StB",
                     "start_min": 0, "end_min": 60}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 4, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="StnB",
    )
    station = create_station(name="CMM-B2", supports_mode="ALL", buffer_min=15)
    open_inspection(wo["id"], station["id"], "FINAL", 100, 160)
    res = api.create_inspection(
        create_inspection_payload(wo["id"], station["id"], "FINAL", 170, 190), INSP)
    validate_error(res, "ERR_STATION_CONFLICT")


def test_machine_slot_end_before_start_rejected(api):
    """PRD §2.9: "numeric ranges satisfied (for example ... a machine slot's end
    strictly after its start ...); otherwise ERR_INVALID_REQUEST (422)."

    Design: Corner/validations/machine_slot_end_before_start_rejected
    """
    rfq, pl, quote, ops, wo = _released_wo_two_mill_ops("BadSlot")
    res = api.create_machine_slot(
        create_machine_slot_payload("MILL_3AX", "VF2-Bad", ops[0]["id"], 100, 50), SCHED)
    validate_error(res, "ERR_INVALID_REQUEST")


def test_complete_op_without_actual_cycle_rejected(api):
    """PRD §3.4: "Completion requires the per-part actual_cycle_min to be supplied
    in the request; if it is omitted the completion is refused with
    ERR_MISSING_ACTUAL_CYCLE."

    Design: Corner/errors/invalid_request_missing_actual_cycle_on_op_complete
    """
    rfq, pl, quote, ops, wo, lots, slots = create_in_process_work_order(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 4.0, "setup_fee_cents": 1000}],
        qty_ordered=4, qty_started=4,
        lots=[{"material_spec": "AL_6061", "qty_received": 4, "unit_cost_cents": 1000,
               "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-OpC"}],
        slot_specs=[{"machine_class": "MILL_3AX", "machine_code": "VF2-OpC",
                     "start_min": 0, "end_min": 60}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 4, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="OpC",
    )
    res = api.complete_routing_op(ops[0]["id"], {}, ADMIN)
    validate_error(res, "ERR_MISSING_ACTUAL_CYCLE")


def _released_wo_one_5ax_op_fully_allocated(customer_id):
    """RELEASED SS_304 WO, qty 4, fully drawn from a single lot (now DEPLETED),
    with one MILL_5AX op still PLANNED. No machine slot is booked: per PRD §3.4
    booking the first slot drives the op SCHEDULED and bubbles the work order
    RELEASED -> IN_PROCESS, and PRD §3.3 permits cancellation only while the WO
    is still PLANNED or RELEASED. To exercise the RELEASED -> CANCELLED
    compensation cascade the WO must therefore remain RELEASED. Returns
    (quote, ops, wo, lot)."""
    rfq, pl, quote, ops, wo, lots = create_released_work_order(
        routing_ops=[{"seq": 1, "machine_class": "MILL_5AX",
                      "estimated_cycle_min": 8.0, "setup_fee_cents": 3000}],
        qty_ordered=4, qty_started=4,
        lots=[{"material_spec": "SS_304", "qty_received": 4, "unit_cost_cents": 2000,
               "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-SS"}],
        part_line_overrides={"material_spec": "SS_304", "quantity": 4, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 2000, "scrap_allowance_pct": 0},
        customer_id=customer_id,
    )
    return quote, ops, wo, lots[0]


def test_wo_cancel_cascade_restores_depleted_lot(api):
    """PRD §3.3: "When a released work order is cancelled (RELEASED -> CANCELLED),
    the server runs a full compensation cascade: every ACTIVE lot allocation of
    the work order is voided to VOIDED, each one restoring its qty_allocated to
    its source lot's qty_remaining and flipping any depleted lot back to
    AVAILABLE".

    A RELEASED WO whose single lot DEPLETED on allocation: cancelling it returns
    the lot to qty_remaining 4 and status AVAILABLE, and the WO becomes CANCELLED.

    Design: Difficulty/transitive_cascade/wo_cancel_cascade_depth3_alloc_lot_and_slot_op
    """
    quote, ops, wo, lot = _released_wo_one_5ax_op_fully_allocated("Casc")
    validate_success(api.cancel_work_order(wo["id"], ADMIN), 200)
    lot_after = validate_success(api.get_material_lot(lot["id"],
                                 TEST_USERS["material_controller_headers"]), 200)
    assert lot_after["qty_remaining"] == 4
    assert lot_after["status"] == "AVAILABLE"
    wo_after = validate_success(api.get_work_order(wo["id"], ADMIN), 200)
    assert wo_after["status"] == "CANCELLED"
