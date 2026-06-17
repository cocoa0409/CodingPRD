"""Shipments, penalties, invoices, actual cost, and ship/invoice lifecycle.

Translates queue A dual_variant_calc (ACTUAL cost divergence; shipment penalty +
yield independence), compensating_invariant (shipment void restores qty_shipped),
and queue B calculations (invoice totals, penalty credit, cap) plus
state_machines (shipment void with invoice, close WO unpaid, pay invoice twice).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    create_in_process_work_order, setup_completed_wo_ready_to_ship,
    ship, invoice, disposition, open_inspection, create_station,
    book_slot,
    create_shipment_payload, create_invoice_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["shop_admin_headers"]
EST = TEST_USERS["estimator_headers"]
MAT = TEST_USERS["material_controller_headers"]


def test_actual_cost_diverges_from_estimate(api):
    """PRD §3.4: "Per completed operation, multiply its actual_cycle_min by the
    per-minute rate of its machine class and round half up to whole cents, then
    multiply by the work order's qty_started, then add that operation's setup
    fee ... The work order's actual_cost_cents is realized labor plus realized
    material."

    qty_started 11; op1 MILL_3AX actual 14.0, op2 LATHE actual 6.0; material 4@1400
    + 7@1500 -> actual_cost_cents 66220.

    Design: Difficulty/dual_variant_calc/quote_estimate_vs_workorder_actual_cost_diverge
    """
    rfq, pl, quote, ops, wo, lots, slots = create_in_process_work_order(
        routing_ops=[
            {"seq": 1, "machine_class": "MILL_3AX", "estimated_cycle_min": 12.5, "setup_fee_cents": 8000},
            {"seq": 2, "machine_class": "LATHE", "estimated_cycle_min": 6.0, "setup_fee_cents": 4500},
        ],
        qty_ordered=10, qty_started=11,
        lots=[
            {"material_spec": "AL_6061", "qty_received": 4, "unit_cost_cents": 1400,
             "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-A"},
            {"material_spec": "AL_6061", "qty_received": 10, "unit_cost_cents": 1500,
             "received_at": "2026-06-02T00:00:00Z", "heat_number": "H-B"},
        ],
        slot_specs=[
            {"machine_class": "MILL_3AX", "machine_code": "VF2-01", "start_min": 0, "end_min": 150},
            {"machine_class": "LATHE", "machine_code": "L-01", "start_min": 0, "end_min": 80},
        ],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 10, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1500, "scrap_allowance_pct": 5},
        customer_id="CUST-1",
    )
    api.complete_routing_op(ops[0]["id"], {"actual_cycle_min": 14.0}, ADMIN)
    api.complete_routing_op(ops[1]["id"], {"actual_cycle_min": 6.0}, ADMIN)
    wo_after = validate_success(api.get_work_order(wo["id"], ADMIN), 200)
    assert wo_after["actual_cost_cents"] == 66220


def test_estimate_and_actual_are_different_numbers(api):
    """PRD §1 (Introduction): "The two figures are deliberately calculated by
    different rules and will rarely match — that divergence is the shop's
    profitability signal."
    PRD §3.2: "The estimated total cost, recorded in extended_cost_cents, is
    labor total plus material total."

    For the same job extended_cost_cents == 59750 while actual_cost_cents ==
    66220 — distinct figures on distinct entities.

    Design: Difficulty/dual_variant_calc/quote_estimate_vs_workorder_actual_cost_diverge
    """
    rfq, pl, quote, ops, wo, lots, slots = create_in_process_work_order(
        routing_ops=[
            {"seq": 1, "machine_class": "MILL_3AX", "estimated_cycle_min": 12.5, "setup_fee_cents": 8000},
            {"seq": 2, "machine_class": "LATHE", "estimated_cycle_min": 6.0, "setup_fee_cents": 4500},
        ],
        qty_ordered=10, qty_started=11,
        lots=[
            {"material_spec": "AL_6061", "qty_received": 4, "unit_cost_cents": 1400,
             "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-A"},
            {"material_spec": "AL_6061", "qty_received": 10, "unit_cost_cents": 1500,
             "received_at": "2026-06-02T00:00:00Z", "heat_number": "H-B"},
        ],
        slot_specs=[
            {"machine_class": "MILL_3AX", "machine_code": "VF2-01b", "start_min": 0, "end_min": 150},
            {"machine_class": "LATHE", "machine_code": "L-01b", "start_min": 0, "end_min": 80},
        ],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 10, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1500, "scrap_allowance_pct": 5},
        customer_id="CUST-1b",
    )
    api.complete_routing_op(ops[0]["id"], {"actual_cycle_min": 14.0}, ADMIN)
    api.complete_routing_op(ops[1]["id"], {"actual_cycle_min": 6.0}, ADMIN)
    q_after = validate_success(api.get_quote(quote["id"], EST), 200)
    wo_after = validate_success(api.get_work_order(wo["id"], ADMIN), 200)
    assert q_after["extended_cost_cents"] == 59750
    assert wo_after["actual_cost_cents"] == 66220
    assert wo_after["actual_cost_cents"] != q_after["extended_cost_cents"]


def _ship_late_three_days(customer_id, qty=9):
    """Bring a WO to COMPLETED with qty_accepted parts, then ship `qty` parts 3
    days late (promised 2026-07-01, actual 2026-07-04). Returns the shipment."""
    rfq, pl, quote, ops, wo, lots, slots = create_in_process_work_order(
        routing_ops=[{"seq": 1, "machine_class": "MILL_3AX",
                      "estimated_cycle_min": 12.5, "setup_fee_cents": 8000}],
        qty_ordered=10, qty_started=10,
        lots=[{"material_spec": "AL_6061", "qty_received": 10, "unit_cost_cents": 1500,
               "received_at": "2026-06-01T00:00:00Z", "heat_number": "H-" + customer_id}],
        slot_specs=[{"machine_class": "MILL_3AX", "machine_code": "VF2-" + customer_id,
                     "start_min": 0, "end_min": 150}],
        part_line_overrides={"material_spec": "AL_6061", "quantity": 10, "tolerance_class": "STANDARD"},
        quote_overrides={"material_unit_cost_cents": 1500, "scrap_allowance_pct": 5},
        customer_id=customer_id,
    )
    station = create_station(name="CMM-" + customer_id, supports_mode="ALL", buffer_min=15)
    insp = open_inspection(wo["id"], station["id"], "FINAL", 200, 260)
    disposition(insp["id"], qty_inspected=10, qty_accepted=9, qty_rework=0, qty_scrap=1)
    return ship(wo["id"], qty, "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")


def test_shipment_late_penalty_and_on_time_flag(api):
    """PRD §3.6: "The liquidated-damages figure, recorded in late_penalty_cents,
    is the smaller of a hard cap of 20000 cents and the product of qty_shipped, a
    per-unit-per-day penalty of 50 cents, and days_late."
    PRD §3.6: "The shipment is on time — on_time is true — when the actual ship
    date is on or before the promised date."

    9 parts, 3 days late -> penalty 9*50*3 = 1350; on_time false.

    Design: Difficulty/dual_variant_calc/shipment_penalty_vs_inspection_yield_independent_subjects
    """
    shp = _ship_late_three_days("Pen1", qty=9)
    assert shp["late_penalty_cents"] == 1350
    assert shp["on_time"] is False


def test_shipment_penalty_independent_of_inspection_yield(api):
    """PRD §3.6: "The days_late figure is the whole-day difference between the
    actual ship date and the promised date, floored to a whole number of days and
    never allowed below 0".

    The Shipment penalty (a capped monetary threshold on days_late) is a separate
    metric on a separate entity from the inspection's first-pass yield; 3 days
    late on 9 parts yields days_late 3 and penalty 1350.

    Design: Difficulty/dual_variant_calc/shipment_penalty_vs_inspection_yield_independent_subjects
    """
    shp = _ship_late_three_days("Pen2", qty=9)
    assert shp["days_late"] == 3
    assert shp["late_penalty_cents"] == 1350


def test_penalty_cap_applies_for_very_late_shipment(api):
    """PRD §3.6: "the smaller of a hard cap of 20000 cents and the product of
    qty_shipped, a per-unit-per-day penalty of 50 cents, and days_late."

    10 parts, 50 days late: raw 10*50*50 = 25000 exceeds the 20000 cap.

    Design: Corner/calculations/penalty_cap_applies_for_very_late_shipment
    """
    rfq, pl, quote, wo = setup_completed_wo_ready_to_ship(qty=10)
    shp = ship(wo["id"], 10, "2026-07-01T00:00:00Z", "2026-08-20T00:00:00Z")
    assert shp["days_late"] == 50
    assert shp["late_penalty_cents"] == 20000
    assert shp["on_time"] is False


def test_invoice_total_with_tax_no_penalty(api):
    """PRD §3.7: "The subtotal, recorded in subtotal_cents, is the quoted unit
    price of the job multiplied by the shipment's qty_shipped".
    PRD §3.7: "The tax, recorded in tax_cents, is the subtotal multiplied by the
    tax rate of 8.25 percent divided by 100, rounded half up to whole cents".
    PRD §3.7: "The grand total, recorded in total_cents, is the subtotal plus the
    tax minus the penalty credit".

    On-time shipment of 10 at unit 7469: subtotal 74690, tax 6162, total 80852.

    Design: Corner/calculations/invoice_total_with_tax_no_penalty
    """
    rfq, pl, quote, wo = setup_completed_wo_ready_to_ship(qty=10)
    shp = ship(wo["id"], 10, "2026-07-01T00:00:00Z", "2026-06-30T00:00:00Z")
    inv = validate_success(api.create_invoice(create_invoice_payload(shp["id"]), ADMIN), 201)
    assert inv["subtotal_cents"] == 74690
    assert inv["tax_cents"] == 6162
    assert inv["penalty_credit_cents"] == 0
    assert inv["total_cents"] == 80852


def test_invoice_total_with_late_penalty_credit(api):
    """PRD §3.7: "The penalty credit, recorded in penalty_credit_cents, equals
    the shipment's late_penalty_cents and is credited to (subtracted from) the
    customer."
    PRD §3.7: "the grand total, recorded in total_cents, is the subtotal plus the
    tax minus the penalty credit".

    Late shipment of 10 (3 days, penalty 1500): total = 74690 + 6162 - 1500 =
    79352.

    Design: Corner/calculations/invoice_total_with_late_penalty_credit
    """
    rfq, pl, quote, wo = setup_completed_wo_ready_to_ship(qty=10)
    shp = ship(wo["id"], 10, "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z")
    assert shp["late_penalty_cents"] == 1500
    inv = validate_success(api.create_invoice(create_invoice_payload(shp["id"]), ADMIN), 201)
    assert inv["penalty_credit_cents"] == 1500
    assert inv["total_cents"] == 79352


def test_shipment_void_restores_qty_shipped_and_reverts_wo(api):
    """PRD §3.6: "Voiding a shipment compensates the work order by subtracting the
    shipment's qty_shipped back off the work order's cumulative shipped count, and
    if the work order had already advanced to SHIPPED it reverts to COMPLETED."

    A 10-part shipment makes the WO SHIPPED (qty_shipped 10 == qty_accepted 10);
    voiding it returns qty_shipped to 0 and the WO to COMPLETED, qty_accepted
    unchanged.

    Design: Difficulty/compensating_invariant/part_count_conservation_shipment_void_restores_qty_shipped
    """
    rfq, pl, quote, wo = setup_completed_wo_ready_to_ship(qty=10)
    shp = ship(wo["id"], 10, "2026-07-01T00:00:00Z", "2026-06-30T00:00:00Z")
    validate_success(api.void_shipment(shp["id"], ADMIN), 200)
    wo_after = validate_success(api.get_work_order(wo["id"], ADMIN), 200)
    assert wo_after["qty_shipped"] == 0
    assert wo_after["qty_accepted"] == 10
    assert wo_after["status"] == "COMPLETED"


def test_voided_shipment_is_terminal_voided(api):
    """PRD §3.6: "A ShopAdmin may void a shipment, driving it SHIPPED -> VOIDED".
    PRD §3.6: "A VOIDED shipment is terminal."

    Design: Difficulty/compensating_invariant/part_count_conservation_shipment_void_restores_qty_shipped
    """
    rfq, pl, quote, wo = setup_completed_wo_ready_to_ship(qty=10)
    shp = ship(wo["id"], 10, "2026-07-01T00:00:00Z", "2026-06-30T00:00:00Z")
    voided = validate_success(api.void_shipment(shp["id"], ADMIN), 200)
    assert voided["status"] == "VOIDED"


def test_shipment_void_with_invoice_rejected(api):
    """PRD §3.6: "A ShopAdmin may void a shipment ... but only when no ISSUED or
    PAID invoice references it; a void attempt against an invoiced shipment is
    refused with ERR_SHIPMENT_HAS_INVOICE."

    Design: Corner/state_machines/shipment_void_with_invoice_rejected
    """
    rfq, pl, quote, wo = setup_completed_wo_ready_to_ship(qty=10)
    shp = ship(wo["id"], 10, "2026-07-01T00:00:00Z", "2026-06-30T00:00:00Z")
    invoice(shp["id"])
    res = api.void_shipment(shp["id"], ADMIN)
    validate_error(res, "ERR_SHIPMENT_HAS_INVOICE")


def test_close_wo_with_unpaid_invoice_rejected(api):
    """PRD §3.7: "a work order can be closed (SHIPPED -> CLOSED) by a ShopAdmin
    only when every invoice for that work order's shipments is PAID, and a close
    attempt while any such invoice is unpaid is refused with ERR_INVOICE_UNPAID."

    Design: Corner/state_machines/close_wo_with_unpaid_invoice_rejected
    """
    rfq, pl, quote, wo = setup_completed_wo_ready_to_ship(qty=10)
    shp = ship(wo["id"], 10, "2026-07-01T00:00:00Z", "2026-06-30T00:00:00Z")
    invoice(shp["id"])  # ISSUED, not PAID
    res = api.close_work_order(wo["id"], ADMIN)
    validate_error(res, "ERR_INVOICE_UNPAID")


def test_pay_invoice_twice_second_invalid_state(api):
    """PRD §3.7: "A ShopAdmin marks an issued invoice paid, driving it ISSUED ->
    PAID ... both PAID and VOIDED are terminal."
    PRD §2.9: "the target resource must currently be in a state from which the
    requested transition is defined; otherwise ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/pay_invoice_twice_second_invalid_state
    """
    rfq, pl, quote, wo = setup_completed_wo_ready_to_ship(qty=10)
    shp = ship(wo["id"], 10, "2026-07-01T00:00:00Z", "2026-06-30T00:00:00Z")
    inv = invoice(shp["id"])
    validate_success(api.pay_invoice(inv["id"], ADMIN), 200)
    res = api.pay_invoice(inv["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")
