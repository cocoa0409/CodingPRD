"""Difficulty Rule 7 — cross_entity_state_dependency (different entity pairs)."""
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
    create_model,
    create_order,
    create_shipment_payload,
    create_spec,
    drive_line_through_production,
    get_success_data,
    make_compliance_officer_headers,
    make_quality_inspector_headers,
    record_cut_on_plan,
    set_clock,
    setup_confirmed_order_with_plant_stock,
    setup_order_in_quality_review,
    setup_order_ready_to_ship,
    setup_order_with_line,
    setup_three_cells,
    start_and_complete_booking,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
SHIP = TEST_USERS["shipping_coordinator_headers"]


# ---------------------------------------------------------------------------
# Instance: booking_gated_on_line_stage (CellBooking → OrderLine)
# ---------------------------------------------------------------------------

def _booking_stage_fixture():
    """ALLOCATED line; CUTTING and SEWING cells. Returns (order, line, lot, c_cut, c_sew)."""
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP", category="CHAIR", base_fabric_yards=3.0,
                         base_price_cents=50000, requires_pattern_match=False,
                         option_rules=[{
                             "fabric_grade": "A", "finish_code": "ESPRESSO",
                             "allowed": True, "surcharge_pct": 0.0,
                             "lead_time_adder_days": 0,
                         }])
    spec = create_spec(fabric_code="FAB-A", origin="PLANT", grade="A",
                       nominal_width_inches=54.0, price_per_yard_cents=3000)
    dealer = create_dealer()
    order, line, lot = setup_confirmed_order_with_plant_stock(
        model, spec, dealer, order_number="ORD-STG", quantity=1, lot_yards=30.0,
    )
    c_cut = create_cell("C-CUT", "CUTTING", 1, [])
    c_sew = create_cell("C-SEW", "SEWING", 1, [])
    return order, line, lot, c_cut, c_sew


def test_sew_booking_rejected_while_line_allocated(api):
    """PRD §3.6: "Operation sequencing follows the line's stage: a SEW booking
    requires the line already `CUT`, and an UPHOLSTER booking requires it
    `SEWN`, else `ERR_LINE_STAGE_MISMATCH`."

    Design: Difficulty/cross_entity_state_dependency/booking_gated_on_line_stage
    """
    order, line, lot, c_cut, c_sew = _booking_stage_fixture()
    res = api.create_cell_booking({
        "cell_id": c_sew["id"], "order_line_id": line["id"], "operation": "SEW",
        "start_at": "2026-06-04T10:00:00Z", "end_at": "2026-06-04T12:00:00Z",
    }, PLANNER)
    validate_error(res, "ERR_LINE_STAGE_MISMATCH", expected_status=409)


def test_sew_booking_succeeds_after_record_cut(api):
    """PRD §3.6: "a CUT completion leaves the line's stage alone — the line
    reaches `CUT` only through record-cut, which demands that completed CUT
    booking."
    PRD §3.5: "The line itself moves `ALLOCATED` → `CUT`."

    Design: Difficulty/cross_entity_state_dependency/booking_gated_on_line_stage
    """
    order, line, lot, c_cut, c_sew = _booking_stage_fixture()
    # Walk through CUT: booking complete, plan approved, record-cut
    b_cut = book_cell(c_cut["id"], line["id"], "CUT",
                      "2026-06-04T08:00:00Z", "2026-06-04T10:00:00Z")
    start_and_complete_booking(b_cut["id"])
    plan = create_approved_cut_plan(line, marker_length_yards=3.5)
    record_cut_on_plan(plan)
    line_after_cut = validate_success(api.get_order_line(line["id"], SALES))
    assert line_after_cut["status"] == "CUT"

    # Now the same SEW booking is accepted
    b_sew = validate_success(api.create_cell_booking({
        "cell_id": c_sew["id"], "order_line_id": line["id"], "operation": "SEW",
        "start_at": "2026-06-04T10:00:00Z", "end_at": "2026-06-04T12:00:00Z",
    }, PLANNER), 201)
    assert b_sew["status"] == "BOOKED"


# ---------------------------------------------------------------------------
# Instance: tender_gated_on_order_ready (Shipment → CustomerOrder)
# ---------------------------------------------------------------------------

def _tender_fixture():
    """Order driven to IN_PRODUCTION via started CUT booking; rated DRAFT shipment.
    Returns (order, line, lot, cells, shipment)."""
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP", category="CHAIR", base_fabric_yards=3.0,
                         base_price_cents=50000, requires_pattern_match=False,
                         option_rules=[{
                             "fabric_grade": "A", "finish_code": "ESPRESSO",
                             "allowed": True, "surcharge_pct": 0.0,
                             "lead_time_adder_days": 0,
                         }])
    spec = create_spec(fabric_code="FAB-A", origin="PLANT", grade="A",
                       nominal_width_inches=54.0, price_per_yard_cents=3000)
    dealer = create_dealer()
    order, line, lot = setup_confirmed_order_with_plant_stock(
        model, spec, dealer, order_number="ORD-TND", quantity=2, lot_yards=30.0,
    )
    c_cut, c_sew, c_uph = setup_three_cells()
    b_cut = book_cell(c_cut["id"], line["id"], "CUT",
                      "2026-06-05T08:00:00Z", "2026-06-05T10:00:00Z")
    get_success_data(api_client.start_booking(b_cut["id"], PLANNER))

    ship = get_success_data(api_client.create_shipment(
        create_shipment_payload(
            order_id=order["id"], weight_lb=240.0, length_in=60.0,
            width_in=30.0, height_in=36.0, declared_value_cents=0, piece_count=3,
        ), SHIP))
    get_success_data(api_client.rate_shipment(ship["id"], SHIP))
    return order, line, lot, (c_cut, c_sew, c_uph), ship, b_cut


def test_tender_rejected_while_order_in_production(api):
    """PRD §3.9: "Tendering a `RATED` shipment (else `ERR_SHIPMENT_INVALID_STATE`)
    requires the order in `READY_TO_SHIP` (else `ERR_ORDER_NOT_READY_TO_SHIP`)
    and moves the shipment to `TENDERED`."

    Design: Difficulty/cross_entity_state_dependency/tender_gated_on_order_ready
    """
    order, line, lot, cells, ship, b_cut = _tender_fixture()
    ord_now = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_now["status"] == "IN_PRODUCTION"
    res = api.tender_shipment(ship["id"], SHIP)
    validate_error(res, "ERR_ORDER_NOT_READY_TO_SHIP", expected_status=409)


def test_tender_succeeds_once_order_ready_to_ship(api):
    """PRD §3.7: "Passing quality requires a `CERTIFIED` compliance certificate
    for the order... On a pass, the order's `quality_result` becomes `PASSED`,
    every `UPHOLSTERED` line moves to `COMPLETED`, and the order moves to
    `READY_TO_SHIP`."
    PRD §3.9: "Tendering a `RATED` shipment ... requires the order in
    `READY_TO_SHIP` ... and moves the shipment to `TENDERED`."

    Design: Difficulty/cross_entity_state_dependency/tender_gated_on_order_ready
    """
    order, line, lot, cells, ship, b_cut = _tender_fixture()
    c_cut, c_sew, c_uph = cells
    # Drive line through the rest of the production chain
    start_and_complete_booking(b_cut["id"])
    line_now = validate_success(api.get_order_line(line["id"], SALES))
    plan = create_approved_cut_plan(line_now, marker_length_yards=7.1)
    record_cut_on_plan(plan)
    b_sew = book_cell(c_sew["id"], line["id"], "SEW",
                      "2026-06-05T10:00:00Z", "2026-06-05T12:00:00Z")
    start_and_complete_booking(b_sew["id"])
    b_uph = book_cell(c_uph["id"], line["id"], "UPHOLSTER",
                      "2026-06-05T13:00:00Z", "2026-06-05T15:00:00Z")
    start_and_complete_booking(b_uph["id"])

    # Certify with a different officer (not the lot inspector)
    cert = create_certificate(order["id"], standard="TB117_2013",
                              label_lot_number="LBL-9", label_count=2)
    validate_success(api.certify_certificate(
        cert["id"], make_compliance_officer_headers("co-2")), 200)
    validate_success(api.pass_quality(
        order["id"], make_quality_inspector_headers("qi-1")), 200)

    ord_ready = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_ready["status"] == "READY_TO_SHIP"

    tendered = validate_success(api.tender_shipment(ship["id"], SHIP), 200)
    assert tendered["status"] == "TENDERED"
