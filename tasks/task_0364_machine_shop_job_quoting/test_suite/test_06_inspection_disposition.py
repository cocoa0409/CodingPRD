"""Inspection disposition: branching counters, first-pass yield, QC gates.

Translates queue A non_linear_state_machine (inspection rework/scrap/accept
fork), boundary_precision_check (zero-inspected yield), cross_entity_state_dependency
(disposition requires WO in process), priority_pair (safety vs constraint),
resource_temporal_overlap (station buffered conflict), the yield side of
dual_variant, plus queue B validations/errors disposition instances.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_open_inspection_on_in_process_wo, create_released_work_order,
    create_station, open_inspection, disposition,
    create_inspection_payload, disposition_payload,
    TEST_USERS,
)

INSP = TEST_USERS["inspector_headers"]
ADMIN = TEST_USERS["shop_admin_headers"]

# Standard single-op chain used by most disposition tests.
_OPS = [{"seq": 1, "machine_class": "MILL_3AX", "estimated_cycle_min": 4.0, "setup_fee_cents": 1000}]
_SLOTS = [{"machine_class": "MILL_3AX", "machine_code": "VF2-FX", "start_min": 0, "end_min": 60}]


def _in_process_wo_with_open_inspection(customer_id, quantity, tolerance="STANDARD",
                                        station_mode="ALL", inspection_mode="FINAL",
                                        window=(200, 260)):
    return create_open_inspection_on_in_process_wo(
        routing_ops=_OPS, qty_ordered=quantity, qty_started=quantity,
        lots=[{"material_spec": ("AL_6061" if tolerance != "CRITICAL" else "TI_6AL4V"),
               "qty_received": quantity, "unit_cost_cents": 1000,
               "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-" + customer_id}],
        slot_specs=[{"machine_class": "MILL_3AX",
                     "machine_code": "VF2-" + customer_id, "start_min": 0, "end_min": 60}],
        station_supports_mode=station_mode, inspection_mode=inspection_mode,
        window_start_min=window[0], window_end_min=window[1],
        part_line_overrides={"material_spec": ("AL_6061" if tolerance != "CRITICAL" else "TI_6AL4V"),
                             "quantity": quantity, "tolerance_class": tolerance},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id=customer_id,
    )


def test_disposition_splits_into_accept_rework_scrap_buckets(api):
    """PRD §3.5: "The disposition then cascades onto the work order's counters:
    qty_in_process is decreased by qty_inspected; qty_accepted on the work order
    is increased by the inspection's accepted count; qty_rework_pending is
    increased by the inspection's rework count; and qty_scrapped is increased by
    the inspection's scrap count."

    11 parts split 9 accept / 1 rework / 1 scrap.

    Design: Difficulty/non_linear_state_machine/workorder_inspection_branching_rework_scrap_accept
    """
    rfq, pl, quote, ops, wo, lots, slots, station, insp = \
        _in_process_wo_with_open_inspection("Fork", 11)
    disposition(insp["id"], qty_inspected=11, qty_accepted=9, qty_rework=1, qty_scrap=1)
    wo_after = validate_success(api.get_work_order(wo["id"], ADMIN), 200)
    assert wo_after["qty_accepted"] == 9
    assert wo_after["qty_rework_pending"] == 1
    assert wo_after["qty_scrapped"] == 1
    assert wo_after["qty_in_process"] == 0


def test_disposition_with_rework_pending_keeps_wo_in_process(api):
    """PRD §3.5: "once the work order's qty_in_process reaches 0 and
    qty_rework_pending reaches 0 — meaning every part has been dispositioned to
    accepted or scrap — the work order bubbles up IN_PROCESS -> COMPLETED."

    With 1 part still rework-pending, the fork has not joined: the WO stays
    IN_PROCESS even though qty_in_process is 0.

    Design: Difficulty/non_linear_state_machine/workorder_inspection_branching_rework_scrap_accept
    """
    rfq, pl, quote, ops, wo, lots, slots, station, insp = \
        _in_process_wo_with_open_inspection("Fork2", 11)
    disposition(insp["id"], qty_inspected=11, qty_accepted=9, qty_rework=1, qty_scrap=1)
    wo_after = validate_success(api.get_work_order(wo["id"], ADMIN), 200)
    assert wo_after["status"] == "IN_PROCESS"


def test_yield_zero_inspected_returns_zero(api):
    """PRD §3.5: "As a guard against division by zero, when qty_inspected is 0
    the yield is recorded as 0."

    Design: Difficulty/boundary_precision_check/yield_zero_inspected_empty_set_returns_zero
    """
    rfq, pl, quote, ops, wo, lots, slots, station, insp = \
        _in_process_wo_with_open_inspection("Zero", 2, window=(100, 160))
    disp = disposition(insp["id"], qty_inspected=0, qty_accepted=0, qty_rework=0, qty_scrap=0)
    assert disp["first_pass_yield_pct"] == 0


def test_yield_zero_inspected_disposition_succeeds(api):
    """PRD §3.5: "An Inspector then dispositions an OPEN inspection, driving it
    OPEN -> DISPOSITIONED."
    PRD §3.5: "the counts must balance, with qty_inspected equal to the sum of
    qty_accepted, qty_rework, and qty_scrap".

    qty_inspected=0=0+0+0 is a valid (balanced) disposition, never a division
    error; the inspection reaches DISPOSITIONED.

    Design: Difficulty/boundary_precision_check/yield_zero_inspected_empty_set_returns_zero
    """
    rfq, pl, quote, ops, wo, lots, slots, station, insp = \
        _in_process_wo_with_open_inspection("Zero2", 2, window=(100, 160))
    disp = disposition(insp["id"], qty_inspected=0, qty_accepted=0, qty_rework=0, qty_scrap=0)
    assert disp["status"] == "DISPOSITIONED"


def test_first_pass_yield_ratio(api):
    """PRD §3.5: "On a successful disposition the inspection computes its
    first-pass yield, recorded in first_pass_yield_pct: the accepted count
    divided by the inspected count, multiplied by 100, rounded half up to two
    decimal places."

    9 accepted of 10 inspected -> 90.0.

    Design: Difficulty/dual_variant_calc/shipment_penalty_vs_inspection_yield_independent_subjects
    """
    rfq, pl, quote, ops, wo, lots, slots, station, insp = \
        _in_process_wo_with_open_inspection("Yld", 10)
    disp = disposition(insp["id"], qty_inspected=10, qty_accepted=9, qty_rework=0, qty_scrap=1)
    assert disp["first_pass_yield_pct"] == 90.0


def test_inspection_disposition_requires_workorder_in_process(api):
    """PRD §3.5: "the work order must be IN_PROCESS, failing with
    ERR_WO_NOT_IN_PROCESS".

    A WO that is only RELEASED (no slot booked, so never bubbled to IN_PROCESS)
    cannot have its inspection dispositioned.

    Design: Difficulty/cross_entity_state_dependency/inspection_disposition_requires_workorder_in_process
    """
    rfq, pl, quote, ops, wo, lots = create_released_work_order(
        routing_ops=_OPS, qty_ordered=4, qty_started=4,
        lots=[{"material_spec": "AL_6061", "qty_received": 4, "unit_cost_cents": 1000,
               "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-XB"}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 4, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="CUST-14",
    )
    assert wo["status"] == "RELEASED"
    station = create_station(name="CMM-XB", supports_mode="ALL", buffer_min=15)
    insp = open_inspection(wo["id"], station["id"], "FINAL", 0, 60)
    res = api.disposition_inspection(
        insp["id"], disposition_payload(4, 4, 0, 0), INSP)
    validate_error(res, "ERR_WO_NOT_IN_PROCESS")


def test_disposition_block_is_from_workorder_state_not_inspection(api):
    """PRD §2.9: "Cross-entity referential preconditions — for example ...
    dispositioning an inspection requires its work order to be in process ...
    these yield ... ERR_WO_NOT_IN_PROCESS".
    PRD §3.5: "Disposition is gated by a chain of preconditions: the work order
    must be IN_PROCESS, failing with ERR_WO_NOT_IN_PROCESS".

    The inspection itself is a valid OPEN inspection on a balanced-count
    disposition; the only block is the referenced WorkOrder's RELEASED (not
    IN_PROCESS) state, so the WO state stays RELEASED after the rejected call.

    Design: Difficulty/cross_entity_state_dependency/inspection_disposition_requires_workorder_in_process
    """
    rfq, pl, quote, ops, wo, lots = create_released_work_order(
        routing_ops=_OPS, qty_ordered=4, qty_started=4,
        lots=[{"material_spec": "AL_6061", "qty_received": 4, "unit_cost_cents": 1000,
               "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-XB2"}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 4, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="CUST-14b",
    )
    station = create_station(name="CMM-XB2", supports_mode="ALL", buffer_min=15)
    insp = open_inspection(wo["id"], station["id"], "FINAL", 0, 60)
    res = api.disposition_inspection(
        insp["id"], disposition_payload(4, 4, 0, 0), INSP)
    validate_error(res, "ERR_WO_NOT_IN_PROCESS")
    wo_after = validate_success(api.get_work_order(wo["id"], ADMIN), 200)
    assert wo_after["status"] == "RELEASED"


def test_safety_gate_precedes_disposition_arithmetic(api):
    """PRD §2.9: inspection-mode safety gate (#8) sits ahead of disposition
    arithmetic (#11), and "a request that violates several rules at once always
    reports the failure highest in this list."
    PRD §3.5: "if the part line's tolerance_class is CRITICAL, the inspection
    mode must be FAI or FINAL (no in-process sign-off is allowed for critical
    parts), failing with ERR_INSPECTION_MODE_REQUIRED".

    A CRITICAL part dispositioned via IN_PROCESS AND with a deliberate count
    mismatch must report the safety gate error, not the arithmetic error.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_disposition_mode_required_wins
    """
    rfq, pl, quote, ops, wo, lots, slots, station, insp = \
        create_open_inspection_on_in_process_wo(
            routing_ops=[{"seq": 1, "machine_class": "MILL_5AX",
                          "estimated_cycle_min": 10.0, "setup_fee_cents": 4000}],
            qty_ordered=5, qty_started=5,
            lots=[{"material_spec": "TI_6AL4V", "qty_received": 5, "unit_cost_cents": 5000,
                   "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-TI"}],
            slot_specs=[{"machine_class": "MILL_5AX", "machine_code": "5AX-02",
                         "start_min": 0, "end_min": 100}],
            station_supports_mode="ALL", inspection_mode="IN_PROCESS",
            window_start_min=200, window_end_min=260,
            part_line_overrides={"material_spec": "TI_6AL4V", "quantity": 5,
                                 "tolerance_class": "CRITICAL"},
            quote_overrides={"material_unit_cost_cents": 5000, "scrap_allowance_pct": 0},
            customer_id="CUST-10",
        )
    res = api.disposition_inspection(
        insp["id"], disposition_payload(5, 5, 1, 1), INSP)  # 5 != 5+1+1 (mismatch too)
    validate_error(res, "ERR_INSPECTION_MODE_REQUIRED")


def test_critical_part_in_process_mode_rejected_alone(api):
    """PRD §3.5: "if the part line's tolerance_class is CRITICAL, the inspection
    mode must be FAI or FINAL (no in-process sign-off is allowed for critical
    parts), failing with ERR_INSPECTION_MODE_REQUIRED".

    Isolated safety-gate scenario: a CRITICAL part with mode IN_PROCESS and
    BALANCED counts still fails the QC gate.

    Design: Difficulty/priority_pair_validation_conflict/safety_vs_constraint_disposition_mode_required_wins
    """
    rfq, pl, quote, ops, wo, lots, slots, station, insp = \
        create_open_inspection_on_in_process_wo(
            routing_ops=[{"seq": 1, "machine_class": "MILL_5AX",
                          "estimated_cycle_min": 10.0, "setup_fee_cents": 4000}],
            qty_ordered=5, qty_started=5,
            lots=[{"material_spec": "TI_6AL4V", "qty_received": 5, "unit_cost_cents": 5000,
                   "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-TI2"}],
            slot_specs=[{"machine_class": "MILL_5AX", "machine_code": "5AX-02b",
                         "start_min": 0, "end_min": 100}],
            station_supports_mode="ALL", inspection_mode="IN_PROCESS",
            window_start_min=200, window_end_min=260,
            part_line_overrides={"material_spec": "TI_6AL4V", "quantity": 5,
                                 "tolerance_class": "CRITICAL"},
            quote_overrides={"material_unit_cost_cents": 5000, "scrap_allowance_pct": 0},
            customer_id="CUST-10b",
        )
    res = api.disposition_inspection(
        insp["id"], disposition_payload(5, 5, 0, 0), INSP)  # balanced counts
    validate_error(res, "ERR_INSPECTION_MODE_REQUIRED")


def test_disposition_exceeds_wip_rejected(api):
    """PRD §3.5: "the inspected quantity must not exceed the work order's
    qty_in_process, failing with ERR_DISPOSITION_EXCEEDS_WIP".

    Design: Corner/validations/disposition_exceeds_wip_rejected
    """
    rfq, pl, quote, ops, wo, lots, slots, station, insp = \
        _in_process_wo_with_open_inspection("WipB", 4, window=(100, 160))
    res = api.disposition_inspection(
        insp["id"], disposition_payload(12, 12, 0, 0), INSP)
    validate_error(res, "ERR_DISPOSITION_EXCEEDS_WIP")


def test_disposition_qty_mismatch_triggers_error(api):
    """PRD §3.5: "the counts must balance, with qty_inspected equal to the sum of
    qty_accepted, qty_rework, and qty_scrap, failing with
    ERR_DISPOSITION_QTY_MISMATCH".

    Design: Corner/errors/disposition_qty_mismatch_triggers_error
    """
    rfq, pl, quote, ops, wo, lots, slots, station, insp = \
        _in_process_wo_with_open_inspection("Mis", 5, window=(100, 160))
    res = api.disposition_inspection(
        insp["id"], disposition_payload(5, 3, 0, 0), INSP)
    validate_error(res, "ERR_DISPOSITION_QTY_MISMATCH")


def test_station_mode_unsupported_rejected(api):
    """PRD §3.5: "a station whose supports_mode is ALL accepts any mode,
    otherwise the requested mode must equal the station's declared mode, and a
    mismatch is refused with ERR_STATION_MODE_UNSUPPORTED."

    Design: Corner/validations/station_mode_unsupported_rejected
    """
    rfq, pl, quote, ops, wo, lots = create_released_work_order(
        routing_ops=_OPS, qty_ordered=4, qty_started=4,
        lots=[{"material_spec": "AL_6061", "qty_received": 4, "unit_cost_cents": 1000,
               "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-ModeU"}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 4, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
        customer_id="C-28",
    )
    # Bring the WO to IN_PROCESS by booking a slot.
    from test_helpers import book_slot
    book_slot("MILL_3AX", "VF2-ModeU", ops[0]["id"], 0, 60)
    station = create_station(name="FAI-only", supports_mode="FAI", buffer_min=15)
    res = api.create_inspection(
        create_inspection_payload(wo["id"], station["id"], "FINAL", 100, 160), INSP)
    validate_error(res, "ERR_STATION_MODE_UNSUPPORTED")


def test_inspection_station_buffered_window_overlap_rejected(api):
    """PRD §3.5: "the requested window, expanded by the station's buffer_min on
    both sides, must not overlap any existing window (whether OPEN or
    DISPOSITIONED) on the same station; an overlap is refused with
    ERR_STATION_CONFLICT."

    Existing window [100,160] with buffer 15 occupies [85,175]; a new [170,190]
    collides (170 <= 175).

    Design: Difficulty/resource_temporal_overlap/inspection_station_buffered_closed_overlap
    """
    rfq, pl, quote, ops, wo, lots, slots, station, insp = \
        create_open_inspection_on_in_process_wo(
            routing_ops=_OPS, qty_ordered=4, qty_started=4,
            lots=[{"material_spec": "AL_6061", "qty_received": 4, "unit_cost_cents": 1000,
                   "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-StA"}],
            slot_specs=[{"machine_class": "MILL_3AX", "machine_code": "VF2-StA",
                         "start_min": 0, "end_min": 60}],
            station_supports_mode="ALL", station_buffer_min=15, inspection_mode="FINAL",
            window_start_min=100, window_end_min=160,
            part_line_overrides={"material_spec": "AL_6061", "quantity": 4,
                                 "tolerance_class": "STANDARD"},
            quote_overrides={"material_unit_cost_cents": 1000, "scrap_allowance_pct": 0},
            customer_id="CUST-16",
        )
    res = api.create_inspection(
        create_inspection_payload(wo["id"], station["id"], "FINAL", 170, 190), INSP)
    validate_error(res, "ERR_STATION_CONFLICT")
