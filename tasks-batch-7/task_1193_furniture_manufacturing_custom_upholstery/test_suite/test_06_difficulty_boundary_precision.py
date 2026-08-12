"""Difficulty Rule 6 — boundary_precision_check (different metrics)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_line,
    api_client,
    book_cell,
    confirm_order,
    create_available_lot,
    create_cell,
    create_dealer,
    create_lot,
    create_model,
    create_order,
    create_spec,
    get_success_data,
    inspect_lot_pass,
    receive_lot,
    set_clock,
    setup_confirmed_order_with_plant_stock,
    setup_order_with_line,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
RECEIVER = TEST_USERS["material_receiver_headers"]


# ---------------------------------------------------------------------------
# Instance: shortfall_boundary_exact_coverage (yardage; inclusive boundary)
# ---------------------------------------------------------------------------

def _boundary_fixture():
    """Two COM orders with same line; lot1 received exactly 14.950, lot2 14.949."""
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(
        model_code="M-PM", category="SOFA", base_fabric_yards=3.0,
        base_price_cents=50000, requires_pattern_match=True,
        option_rules=[{
            "fabric_grade": "COM", "finish_code": "ANY",
            "allowed": True, "surcharge_pct": 0.0, "lead_time_adder_days": 0,
        }],
    )
    spec = create_spec(fabric_code="FAB-COM-Z", origin="CUSTOMER", grade="COM",
                       nominal_width_inches=54.0, pattern_repeat_v_inches=9.0,
                       match_method="STRAIGHT", com_credit_per_yard_cents=250)
    dealer = create_dealer()

    order1, line1 = setup_order_with_line(model, spec, dealer, order_number="ORD-B1",
                                          quantity=4, fabric_source="COM")
    confirm_order(order1["id"])
    lot1 = create_lot(spec["id"], expected_yards=14.95, order_line_id=line1["id"])
    receive_lot(lot1["id"], received_yards=14.95)

    order2, line2 = setup_order_with_line(model, spec, dealer, order_number="ORD-B2",
                                          quantity=4, fabric_source="COM")
    confirm_order(order2["id"])
    lot2 = create_lot(spec["id"], expected_yards=14.949, order_line_id=line2["id"])
    receive_lot(lot2["id"], received_yards=14.949)
    return order1, line1, lot1, order2, line2, lot2


def test_exact_coverage_allocates_line_and_confirms_order(api):
    """PRD §3.3: "The line is `ALLOCATED` exactly when `allocated_yards` is
    greater than or equal to the effective requirement — equality counts as
    covered — and `MATERIAL_SHORTFALL` otherwise."
    PRD §3.3: "when the order's last `MATERIAL_SHORTFALL` line flips to
    `ALLOCATED`, the order returns to `CONFIRMED`."

    Design: Difficulty/boundary_precision_check/shortfall_boundary_exact_coverage
    """
    order1, line1, lot1, _, _, _ = _boundary_fixture()
    # COM lot auto-allocation covers exactly 14.950 == required 14.950
    inspect_lot_pass(lot1["id"], usable_yards=14.95, measured_width_inches=54.0)

    line_after = validate_success(api.get_order_line(line1["id"], SALES))
    assert line_after["allocated_yards"] == pytest.approx(14.950, abs=0.001)
    assert line_after["shortfall_yards"] == pytest.approx(0.000, abs=0.001)
    assert line_after["status"] == "ALLOCATED"
    ord_after = validate_success(api.get_customer_order(order1["id"], SALES))
    assert ord_after["status"] == "CONFIRMED"


def test_one_thousandth_short_leaves_line_short(api):
    """PRD §3.3: "The line's `shortfall_yards` is the larger of zero and the
    effective requirement minus `allocated_yards`."
    PRD §3.3: "if any line landed in `MATERIAL_SHORTFALL`, the order lands in
    `MATERIAL_HOLD` rather than `CONFIRMED`."

    Design: Difficulty/boundary_precision_check/shortfall_boundary_exact_coverage
    """
    _, _, _, order2, line2, lot2 = _boundary_fixture()
    # COM lot auto-allocation covers 14.949 — 0.001 short
    inspect_lot_pass(lot2["id"], usable_yards=14.949, measured_width_inches=54.0)

    line_after = validate_success(api.get_order_line(line2["id"], SALES))
    assert line_after["allocated_yards"] == pytest.approx(14.949, abs=0.001)
    assert line_after["shortfall_yards"] == pytest.approx(0.001, abs=0.0005)
    assert line_after["status"] == "MATERIAL_SHORTFALL"
    ord_after = validate_success(api.get_customer_order(order2["id"], SALES))
    assert ord_after["status"] == "MATERIAL_HOLD"


# ---------------------------------------------------------------------------
# Instance: cell_booking_half_open_adjacency (time intervals)
# ---------------------------------------------------------------------------

def _adjacency_fixture():
    """Confirmed plant-stock order, exclusive capacity-1 CUTTING cell."""
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
        model, spec, dealer, order_number="ORD-ADJ", quantity=1, lot_yards=30.0,
    )
    cell = create_cell("C-CUT", "CUTTING", 1, [])
    return order, line, cell


def test_adjacent_bookings_allowed_on_exclusive_cell(api):
    """PRD §3.6: "Overlap is policed per cell capacity, treating windows as
    half-open so that adjacency — one booking's `end_at` equal to another's
    `start_at` — is allowed, and counting only active bookings (those in
    `BOOKED` or `IN_PROGRESS`; `COMPLETED` and `RELEASED` bookings do not
    block)."

    Design: Difficulty/boundary_precision_check/cell_booking_half_open_adjacency
    """
    order, line, cell = _adjacency_fixture()
    b1 = validate_success(api.create_cell_booking({
        "cell_id": cell["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-03T10:00:00Z", "end_at": "2026-06-03T12:00:00Z",
    }, PLANNER), 201)
    assert b1["status"] == "BOOKED"
    # Adjacent (start == prior end) is allowed
    b2 = validate_success(api.create_cell_booking({
        "cell_id": cell["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-03T12:00:00Z", "end_at": "2026-06-03T14:00:00Z",
    }, PLANNER), 201)
    assert b2["status"] == "BOOKED"

    cell_after = validate_success(api.get_cell(cell["id"], PLANNER))
    assert cell_after["committed_hours"] == pytest.approx(4.0, abs=0.001)


def test_overlapping_booking_rejected_on_exclusive_cell(api):
    """PRD §3.6: "On an exclusive cell — `capacity_slots` of 1 — a new booking
    that overlaps any active one is rejected with `ERR_CELL_OVERLAP`."

    Design: Difficulty/boundary_precision_check/cell_booking_half_open_adjacency
    """
    order, line, cell = _adjacency_fixture()
    api.create_cell_booking({
        "cell_id": cell["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-03T10:00:00Z", "end_at": "2026-06-03T12:00:00Z",
    }, PLANNER)
    api.create_cell_booking({
        "cell_id": cell["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-03T12:00:00Z", "end_at": "2026-06-03T14:00:00Z",
    }, PLANNER)
    # [11:00, 13:00) overlaps both — must fail
    res = api.create_cell_booking({
        "cell_id": cell["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-03T11:00:00Z", "end_at": "2026-06-03T13:00:00Z",
    }, PLANNER)
    validate_error(res, "ERR_CELL_OVERLAP", expected_status=409)
