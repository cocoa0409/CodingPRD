"""Difficulty Rule 4 — transitive_cascade (different triggers, depths)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_line,
    api_client,
    book_cell,
    create_available_lot,
    create_cell,
    create_certificate,
    create_dealer,
    create_draft_cut_plan,
    create_lot,
    create_model,
    create_order,
    create_spec,
    get_success_data,
    inspect_lot_pass,
    make_quality_inspector_headers,
    receive_lot,
    set_clock,
    setup_confirmed_order_with_plant_stock,
    setup_order_with_line,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
RECEIVER = TEST_USERS["material_receiver_headers"]


# ---------------------------------------------------------------------------
# Instance: lot_recall_cascade (depth-4 chain from reject-lot)
# ---------------------------------------------------------------------------

def _recall_fixture():
    """Pattern-match order confirmed against two lots; BOOKED CUT booking.
    Returns (order, line, lot_a, lot_b, cell, booking)."""
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(
        model_code="M-PM", category="SOFA", base_fabric_yards=3.0,
        base_price_cents=50000, requires_pattern_match=True,
        option_rules=[{
            "fabric_grade": "A", "finish_code": "ESPRESSO",
            "allowed": True, "surcharge_pct": 0.0, "lead_time_adder_days": 0,
        }],
    )
    spec = create_spec(fabric_code="FAB-STRAIGHT", origin="PLANT", grade="A",
                       nominal_width_inches=54.0, pattern_repeat_v_inches=9.0,
                       match_method="STRAIGHT", price_per_yard_cents=3000)
    dealer = create_dealer()
    lot_a = create_available_lot(spec["id"], yards=10.0, measured_width_inches=54.0)
    lot_b = create_available_lot(spec["id"], yards=10.0, measured_width_inches=54.0)
    order, line = setup_order_with_line(model, spec, dealer, order_number="ORD-RC",
                                        quantity=4)
    # Confirm: FEFO reserves lotA 10.000 + lotB 4.950
    from test_helpers import confirm_order
    confirm_order(order["id"])

    cell = create_cell("C-CUT", "CUTTING", 1, [])
    booking = book_cell(cell["id"], line["id"], "CUT",
                        "2026-06-02T08:00:00Z", "2026-06-02T10:00:00Z")
    return order, line, lot_a, lot_b, cell, booking


def test_lot_recall_cascades_to_order_hold(api):
    """PRD §3.4: "The recall moves the lot to `REJECTED` and cascades: every
    ACTIVE allocation on the lot moves to `RELEASED`; each affected order line
    recomputes its `allocated_yards`, and lines that drop below their effective
    requirement move to `MATERIAL_SHORTFALL`; each such line's order, if
    `CONFIRMED`, moves to `MATERIAL_HOLD` and has its BOOKED cell bookings
    released."

    Design: Difficulty/transitive_cascade/lot_recall_cascade
    """
    order, line, lot_a, lot_b, cell, booking = _recall_fixture()
    qi2 = make_quality_inspector_headers("qi-2")
    lot_after = validate_success(api.reject_lot(lot_a["id"], qi2), 200)
    assert lot_after["status"] == "REJECTED"

    line_after = validate_success(api.get_order_line(line["id"], SALES))
    assert line_after["allocated_yards"] == pytest.approx(4.950, abs=0.001)
    assert line_after["shortfall_yards"] == pytest.approx(10.000, abs=0.001)
    assert line_after["status"] == "MATERIAL_SHORTFALL"

    order_after = validate_success(api.get_customer_order(order["id"], SALES))
    assert order_after["status"] == "MATERIAL_HOLD"


def test_lot_recall_releases_booked_bookings(api):
    """PRD §3.4: "each such line's order, if `CONFIRMED`, moves to
    `MATERIAL_HOLD` and has its BOOKED cell bookings released."
    PRD §3.6: "the cell's `committed_hours` — the summed `duration_hours` of
    its bookings in `BOOKED` or `IN_PROGRESS` — is recomputed whenever a
    booking is created, started, completed, or released."

    Design: Difficulty/transitive_cascade/lot_recall_cascade
    """
    order, line, lot_a, lot_b, cell, booking = _recall_fixture()
    qi2 = make_quality_inspector_headers("qi-2")
    api.reject_lot(lot_a["id"], qi2)

    booking_after = validate_success(api.get_cell_booking(booking["id"], PLANNER))
    assert booking_after["status"] == "RELEASED"
    cell_after = validate_success(api.get_cell(cell["id"], PLANNER))
    assert cell_after["committed_hours"] == pytest.approx(0.0, abs=0.001)


# ---------------------------------------------------------------------------
# Instance: order_cancel_cascade (depth-3 chain from cancel)
# ---------------------------------------------------------------------------

def _cancel_fixture():
    """Confirmed plant-stock order with requisition, plan, booking, certificate.
    Returns (order, line, lot, requisition, plan, booking, cert)."""
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-CX", category="CHAIR", base_fabric_yards=3.0,
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
        model, spec, dealer, order_number="ORD-CX", quantity=2, lot_yards=30.0,
    )
    requisition = get_success_data(api_client.create_supply_requisition(
        {
            "order_line_id": line["id"],
            "component_code": "FRAME",
            "quantity": 10,
            "source_type": "DOMESTIC",
        }, PLANNER))
    plan = create_draft_cut_plan(line)
    cell = create_cell("C-CUT", "CUTTING", 1, [])
    booking = book_cell(cell["id"], line["id"], "CUT",
                        "2026-06-03T08:00:00Z", "2026-06-03T10:00:00Z")
    cert = create_certificate(order["id"], standard="TB117_2013",
                              label_lot_number="LBL-1", label_count=2)
    return order, line, lot, requisition, plan, booking, cert


def test_order_cancel_cascades_to_lines_and_allocations(api):
    """PRD §3.2: "Cancelling cascades through everything the order touched:
    every non-terminal line moves to `CANCELLED`; each cancelled line's ACTIVE
    allocations move to `RELEASED` and the owning lots' `allocated_yards` are
    recomputed..."

    Design: Difficulty/transitive_cascade/order_cancel_cascade
    """
    order, line, lot, req, plan, booking, cert = _cancel_fixture()
    cancelled = validate_success(api.cancel_order(order["id"], SALES), 200)
    assert cancelled["status"] == "CANCELLED"

    line_after = validate_success(api.get_order_line(line["id"], SALES))
    assert line_after["status"] == "CANCELLED"

    lot_after = validate_success(api.get_material_lot(lot["id"], RECEIVER))
    assert lot_after["allocated_yards"] == pytest.approx(0.0, abs=0.001)
    assert lot_after["available_yards"] == pytest.approx(30.0, abs=0.001)


def test_order_cancel_cascades_to_dependent_records(api):
    """PRD §3.2: "the lines' OPEN or PLACED supply requisitions move to
    `CANCELLED`; their DRAFT or APPROVED cut plans move to `VOID`; their
    BOOKED cell bookings move to `RELEASED`; and the order's DRAFT compliance
    certificates move to `VOID`."

    Design: Difficulty/transitive_cascade/order_cancel_cascade
    """
    order, line, lot, req, plan, booking, cert = _cancel_fixture()
    api.cancel_order(order["id"], SALES)

    req_after = validate_success(api.get_supply_requisition(req["id"], PLANNER))
    assert req_after["status"] == "CANCELLED"
    plan_after = validate_success(api.get_cut_plan(plan["id"], PLANNER))
    assert plan_after["status"] == "VOID"
    booking_after = validate_success(api.get_cell_booking(booking["id"], PLANNER))
    assert booking_after["status"] == "RELEASED"
    cert_after = validate_success(api.get_compliance_certificate(cert["id"], TEST_USERS["compliance_officer_headers"]))
    assert cert_after["status"] == "VOID"
