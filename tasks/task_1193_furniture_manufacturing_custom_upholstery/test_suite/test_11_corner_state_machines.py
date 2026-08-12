"""Corner tests — §state_machines (initial states, invalid transitions,
terminal lockdowns, precondition guards)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_line,
    api_client,
    book_cell,
    confirm_order,
    create_approved_cut_plan,
    create_available_lot,
    create_cell,
    create_certificate,
    create_dealer,
    create_draft_cut_plan,
    create_lot,
    create_model,
    create_order,
    create_showroom_sample_payload,
    create_spec,
    drive_line_through_production,
    get_success_data,
    inspect_lot_fail,
    inspect_lot_pass,
    make_compliance_officer_headers,
    make_quality_inspector_headers,
    receive_lot,
    record_cut_on_plan,
    set_clock,
    setup_confirmed_order_with_plant_stock,
    setup_delivered_shipment,
    setup_order_in_quality_review,
    setup_order_with_line,
    start_and_complete_booking,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
RECEIVER = TEST_USERS["material_receiver_headers"]
SHIP = TEST_USERS["shipping_coordinator_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def test_initial_states_on_create(api):
    """PRD §3.2: "A new order sits in `DRAFT` with `quality_result` `NONE` and
    all monetary totals at zero."
    PRD §3.2: "the line itself starts in `PENDING`..."
    PRD §3.4: "the lot starts in `EXPECTED`..."
    PRD §3.6: "A cell is born `ACTIVE`..."
    PRD §3.7: "A `ComplianceOfficer` drafts one for an order..."
    PRD §3.8: "A new sample is born `ON_LOAN`, with `loaned_at` stamped from
    the logical clock and `due_back_at` computed as `loaned_at` plus
    `due_back_days`."

    Design: Corner/state_machines/initial_states_on_create
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer(sample_allowance_cents=100000)
    order = create_order("ORD-INIT", dealer["id"])
    line = add_line(order["id"], model["id"], spec["id"])
    lot = create_lot(spec["id"], expected_yards=10.0)
    cell = create_cell("C-CUT", "CUTTING", 1, [])
    cert = create_certificate(order["id"], standard="TB117_2013",
                              label_lot_number="LBL-1", label_count=1)
    sample = get_success_data(api_client.create_showroom_sample(
        create_showroom_sample_payload(
            dealer_id=dealer["id"], model_id=model["id"],
            unit_serial="UNIT-1", sample_value_cents=10000, due_back_days=30,
        ), SALES))

    order_now = validate_success(api.get_customer_order(order["id"], SALES))
    assert order_now["status"] == "DRAFT"
    line_now = validate_success(api.get_order_line(line["id"], SALES))
    assert line_now["status"] == "PENDING"
    lot_now = validate_success(api.get_material_lot(lot["id"], RECEIVER))
    assert lot_now["status"] == "EXPECTED"
    assert lot_now["ownership"] == "PLANT"
    cell_now = validate_success(api.get_cell(cell["id"], PLANNER))
    assert cell_now["status"] == "ACTIVE"
    assert cell_now["committed_hours"] == pytest.approx(0.0, abs=0.001)
    cert_now = validate_success(api.get_compliance_certificate(cert["id"], CO))
    assert cert_now["status"] == "DRAFT"
    sample_now = validate_success(api.get_showroom_sample(sample["id"], SALES))
    assert sample_now["disposition"] == "ON_LOAN"
    # loaned 2026-05-10 + 30 days = 2026-06-09
    assert sample_now["due_back_at"].startswith("2026-06-09")
    dealer_now = validate_success(api.get_dealer_account(dealer["id"], SALES))
    assert dealer_now["outstanding_sample_value_cents"] == 10000


def test_lot_invalid_transitions_rejected(api):
    """PRD §3.4: "receipt against a lot not in `EXPECTED` is rejected with
    `ERR_LOT_INVALID_STATE`."
    PRD §3.4: "Inspection is a `QualityInspector`'s call on a `RECEIVED` lot
    (anything else draws `ERR_LOT_INVALID_STATE`)..."

    Design: Corner/state_machines/lot_invalid_transitions_rejected
    """
    spec = create_spec(fabric_code="FAB-A")
    lot1 = create_lot(spec["id"], expected_yards=10.0)
    lot2 = create_lot(spec["id"], expected_yards=10.0)
    receive_lot(lot2["id"], received_yards=10.0)

    # Inspect on EXPECTED lot fails
    res1 = api.inspect_lot(lot1["id"], {
        "result": "PASS", "usable_yards": 10.0, "rejected_yards": 0.0,
        "measured_width_inches": 54.0,
    }, TEST_USERS["quality_inspector_headers"])
    validate_error(res1, "ERR_LOT_INVALID_STATE", expected_status=409)

    # Second receive on RECEIVED lot fails
    res2 = api.receive_lot(lot2["id"], {"received_yards": 5.0}, RECEIVER)
    validate_error(res2, "ERR_LOT_INVALID_STATE", expected_status=409)


def test_lot_receiving_and_inspection_guards(api):
    """PRD §3.4: "the `received_yards`, which must be greater than zero and no
    more than the expected yardage plus a ten percent over-receipt tolerance —
    anything outside that band is rejected with `ERR_OVER_RECEIPT`."
    PRD §3.4: "On a pass, yardage must conserve exactly: `usable_yards` plus
    `rejected_yards` must equal `received_yards` at a three-decimal comparison,
    and `usable_yards` must be greater than zero — violations are rejected with
    `ERR_INSPECTION_YARDAGE_MISMATCH`."

    Design: Corner/state_machines/lot_receiving_and_inspection_guards
    """
    spec = create_spec(fabric_code="FAB-A")
    lot1 = create_lot(spec["id"], expected_yards=10.0)
    lot2 = create_lot(spec["id"], expected_yards=10.0)
    lot3 = create_lot(spec["id"], expected_yards=10.0)
    receive_lot(lot3["id"], received_yards=10.0)

    # 11.0 == 110% of 10.0 — inclusive boundary, accepted
    ok = validate_success(api.receive_lot(
        lot1["id"], {"received_yards": 11.0}, RECEIVER), 200)
    assert ok["status"] == "RECEIVED"

    # 11.001 > 110% — rejected
    res_over = api.receive_lot(lot2["id"], {"received_yards": 11.001}, RECEIVER)
    validate_error(res_over, "ERR_OVER_RECEIPT", expected_status=422)

    # 7.0 + 2.0 != 10.0 — conservation violation
    res_cons = api.inspect_lot(lot3["id"], {
        "result": "PASS", "usable_yards": 7.0, "rejected_yards": 2.0,
        "measured_width_inches": 54.0,
    }, TEST_USERS["quality_inspector_headers"])
    validate_error(res_cons, "ERR_INSPECTION_YARDAGE_MISMATCH", expected_status=422)

    # 7.0 + 3.0 == 10.0 — accepted
    ok2 = validate_success(api.inspect_lot(lot3["id"], {
        "result": "PASS", "usable_yards": 7.0, "rejected_yards": 3.0,
        "measured_width_inches": 54.0,
    }, TEST_USERS["quality_inspector_headers"]), 200)
    assert ok2["status"] == "AVAILABLE"
    assert ok2["usable_yards"] == pytest.approx(7.0, abs=0.001)
    assert ok2["measured_width_inches"] == pytest.approx(54.0, abs=0.001)


def test_cancel_cancelled_order_rejected(api):
    """PRD §3.2: "Cancellation is available while an order is in `DRAFT`,
    `CONFIRMED`, or `MATERIAL_HOLD`; a cancel request against an order in any
    other status is rejected with `ERR_ORDER_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_cancelled_order_rejected
    """
    dealer = create_dealer()
    order = create_order("ORD-C1", dealer["id"])
    validate_success(api.cancel_order(order["id"], SALES), 200)
    res = api.cancel_order(order["id"], SALES)
    validate_error(res, "ERR_ORDER_NOT_CANCELLABLE", expected_status=409)


def test_booking_invalid_transitions_rejected(api):
    """PRD §3.6: "Completing it (only from `IN_PROGRESS`, else
    `ERR_BOOKING_INVALID_STATE`)..."
    PRD §3.6: "Releasing (only from `BOOKED`, else `ERR_BOOKING_INVALID_STATE`)
    moves the booking to `RELEASED`..."

    Design: Corner/state_machines/booking_invalid_transitions_rejected
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order, line, lot = setup_confirmed_order_with_plant_stock(
        model, spec, dealer, order_number="ORD-BI", quantity=1, lot_yards=30.0,
    )
    cell = create_cell("C-CUT", "CUTTING", 1, [])
    b1 = book_cell(cell["id"], line["id"], "CUT",
                   "2026-06-01T08:00:00Z", "2026-06-01T09:00:00Z")
    b2 = book_cell(cell["id"], line["id"], "CUT",
                   "2026-06-01T09:00:00Z", "2026-06-01T10:00:00Z")
    get_success_data(api_client.start_booking(b2["id"], PLANNER))

    # complete on BOOKED (b1) fails
    res1 = api.complete_booking(b1["id"], PLANNER)
    validate_error(res1, "ERR_BOOKING_INVALID_STATE", expected_status=409)
    # release on IN_PROGRESS (b2) fails
    res2 = api.release_booking(b2["id"], PLANNER)
    validate_error(res2, "ERR_BOOKING_INVALID_STATE", expected_status=409)


def test_sample_and_requisition_double_action_rejected(api):
    """PRD §3.8: "Returning the sample (only from `ON_LOAN`, else
    `ERR_SAMPLE_NOT_ON_LOAN`)..."
    PRD §3.6: "receiving it (only from `PLACED`, else
    `ERR_REQUISITION_INVALID_STATE`)..."

    Design: Corner/state_machines/sample_and_requisition_double_action_rejected
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer(sample_allowance_cents=100000)
    s1 = get_success_data(api_client.create_showroom_sample(
        create_showroom_sample_payload(
            dealer_id=dealer["id"], model_id=model["id"],
            unit_serial="UNIT-2", sample_value_cents=10000, due_back_days=30,
        ), SALES))
    get_success_data(api_client.return_sample(s1["id"], SALES))

    order = create_order("ORD-RQ", dealer["id"])
    line = add_line(order["id"], model["id"], spec["id"])
    confirm_order(order["id"])
    req = get_success_data(api_client.create_supply_requisition({
        "order_line_id": line["id"], "component_code": "FRAME",
        "quantity": 1, "source_type": "DOMESTIC",
    }, PLANNER))
    get_success_data(api_client.place_requisition(req["id"], PLANNER))
    set_clock("2026-05-17T00:00:00Z")
    get_success_data(api_client.receive_requisition(req["id"], PLANNER))

    # Second sample return
    res1 = api.return_sample(s1["id"], SALES)
    validate_error(res1, "ERR_SAMPLE_NOT_ON_LOAN", expected_status=409)
    # Second requisition receive
    res2 = api.receive_requisition(req["id"], PLANNER)
    validate_error(res2, "ERR_REQUISITION_INVALID_STATE", expected_status=409)


def test_shipment_and_certificate_invalid_transitions_rejected(api):
    """PRD §3.9: "Recording delivery (only from `PICKED_UP`, else
    `ERR_SHIPMENT_INVALID_STATE`)..."
    PRD §3.7: "The certificate must be in `DRAFT` (else
    `ERR_CERTIFICATE_NOT_DRAFT`)..."

    Design: Corner/state_machines/shipment_and_certificate_invalid_transitions_rejected
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order, line, lot = setup_confirmed_order_with_plant_stock(
        model, spec, dealer, order_number="ORD-SC", quantity=1, lot_yards=30.0,
    )
    ship = get_success_data(api_client.create_shipment({
        "order_id": order["id"], "carrier_name": "Averitt",
        "weight_lb": 100.0, "length_in": 40.0, "width_in": 30.0,
        "height_in": 30.0, "declared_value_cents": 0, "piece_count": 1,
    }, SHIP))

    cell = create_cell("C-CUT", "CUTTING", 1, [])
    b1 = book_cell(cell["id"], line["id"], "CUT",
                   "2026-06-01T08:00:00Z", "2026-06-01T09:00:00Z")
    get_success_data(api_client.start_booking(b1["id"], PLANNER))

    cert = create_certificate(order["id"], standard="TB117_2013",
                              label_lot_number="LBL-2", label_count=1)
    get_success_data(api_client.certify_certificate(
        cert["id"], make_compliance_officer_headers("co-2")))

    # record-delivery on DRAFT shipment fails
    res1 = api.record_delivery(ship["id"], SHIP)
    validate_error(res1, "ERR_SHIPMENT_INVALID_STATE", expected_status=409)
    # Second certify fails
    res2 = api.certify_certificate(cert["id"], make_compliance_officer_headers("co-2"))
    validate_error(res2, "ERR_CERTIFICATE_NOT_DRAFT", expected_status=409)


def test_cutplan_and_allocation_invalid_transitions_rejected(api):
    """PRD §3.5: "It requires the plan in `APPROVED` (else
    `ERR_CUT_PLAN_NOT_APPROVED`)..."
    PRD §3.5: "the plan must be in `DRAFT` (else `ERR_CUT_PLAN_NOT_DRAFT`)..."
    PRD §3.4: "Releasing an allocation is the mirror action, permitted on an
    `ACTIVE` allocation (else `ERR_ALLOCATION_INVALID_STATE`)."

    Design: Corner/state_machines/cutplan_and_allocation_invalid_transitions_rejected
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order, line, lot = setup_confirmed_order_with_plant_stock(
        model, spec, dealer, order_number="ORD-CP", quantity=2, lot_yards=30.0,
    )
    lot2 = create_available_lot(spec["id"], yards=20.0)
    alloc2 = get_success_data(api_client.create_material_allocation({
        "lot_id": lot2["id"], "order_line_id": line["id"], "yards": 1.0,
    }, PLANNER))
    get_success_data(api_client.release_allocation(alloc2["id"], PLANNER))

    plan = create_draft_cut_plan(line)

    # record-cut on DRAFT plan fails
    res1 = api.record_cut(plan["id"], PLANNER)
    validate_error(res1, "ERR_CUT_PLAN_NOT_APPROVED", expected_status=409)
    # approve once
    get_success_data(api.approve_cut_plan(plan["id"], {"marker_length_yards": 7.0}, PLANNER))
    # approve again fails
    res2 = api.approve_cut_plan(plan["id"], {"marker_length_yards": 7.0}, PLANNER)
    validate_error(res2, "ERR_CUT_PLAN_NOT_DRAFT", expected_status=409)
    # release on RELEASED allocation fails
    res3 = api.release_allocation(alloc2["id"], PLANNER)
    validate_error(res3, "ERR_ALLOCATION_INVALID_STATE", expected_status=409)


def test_terminal_shipment_and_delivered_order_lockdown(api):
    """PRD §3.9: "Recording delivery (only from `PICKED_UP`, else
    `ERR_SHIPMENT_INVALID_STATE`) moves the shipment to `DELIVERED` and the
    order automatically to `DELIVERED`."
    PRD §3.2: "Cancellation is available while an order is in `DRAFT`,
    `CONFIRMED`, or `MATERIAL_HOLD`; a cancel request against an order in any
    other status is rejected with `ERR_ORDER_NOT_CANCELLABLE`."

    Design: Corner/state_machines/terminal_shipment_and_delivered_order_lockdown
    """
    model = create_model(model_code="M-NP")
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order, line, lot, cells, cert, ship = setup_delivered_shipment(
        model, spec, dealer, order_number="ORD-DONE",
    )
    assert order["status"] == "DELIVERED"
    assert ship["status"] == "DELIVERED"

    # Second record-delivery fails
    res1 = api.record_delivery(ship["id"], SHIP)
    validate_error(res1, "ERR_SHIPMENT_INVALID_STATE", expected_status=409)
    # Cancel on DELIVERED fails
    res2 = api.cancel_order(order["id"], SALES)
    validate_error(res2, "ERR_ORDER_NOT_CANCELLABLE", expected_status=409)
