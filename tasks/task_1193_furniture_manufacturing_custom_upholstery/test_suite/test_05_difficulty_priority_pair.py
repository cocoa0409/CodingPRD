"""Difficulty Rule 5 — priority_pair_validation_conflict (different pairs)."""
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
    resolve_com_line_with_lot,
    set_clock,
    setup_confirmed_com_order,
    setup_confirmed_order_with_plant_stock,
    setup_order_with_line,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
RECEIVER = TEST_USERS["material_receiver_headers"]


# ---------------------------------------------------------------------------
# Instance: state_beats_fiscal_on_allocation (priority 5 vs 9)
# ---------------------------------------------------------------------------

def _state_vs_fiscal_fixture():
    """Order with MATERIAL_SHORTFALL line; lot RECEIVED but not inspected."""
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP", category="SOFA", base_fabric_yards=3.0,
                         base_price_cents=50000, requires_pattern_match=False,
                         option_rules=[{
                             "fabric_grade": "A", "finish_code": "ESPRESSO",
                             "allowed": True, "surcharge_pct": 0.0,
                             "lead_time_adder_days": 0,
                         }])
    spec = create_spec(fabric_code="FAB-A", origin="PLANT", grade="A",
                       nominal_width_inches=54.0, price_per_yard_cents=3000)
    dealer = create_dealer()
    order, line = setup_order_with_line(model, spec, dealer, order_number="ORD-SF",
                                        quantity=4)
    confirm_order(order["id"])  # no stock — line MATERIAL_SHORTFALL

    lot = create_lot(spec["id"], expected_yards=10.0)
    receive_lot(lot["id"], received_yards=10.0)
    # Lot stays RECEIVED — NOT inspected, so not AVAILABLE and available_yards 0.0
    return order, line, lot


def test_state_error_beats_fiscal_on_allocation(api):
    """PRD §2.8: "5. **State legality** — the target resource sits in a state
    the state machine permits for the operation (a model ACTIVE, a dealer not
    SUSPENDED, an order DRAFT for confirm, a lot AVAILABLE for allocation...)
    ... 9. **Fiscal checks** — credit limits, yardage sufficiency, sample
    allowance headroom, and allocation sufficiency are evaluated last."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_allocation
    """
    order, line, lot = _state_vs_fiscal_fixture()
    # Lot is RECEIVED (state violation, priority 5) AND 50.0 > available 0.0
    # (fiscal violation, priority 9)
    res = api.create_material_allocation({
        "lot_id": lot["id"], "order_line_id": line["id"], "yards": 50.0,
    }, PLANNER)
    validate_error(res, "ERR_LOT_NOT_AVAILABLE", expected_status=409)


def test_state_error_id_is_not_the_fiscal_one(api):
    """PRD §2.8: "the surfaced error is deterministic."
    PRD §3.4: "the lot must be `AVAILABLE` (`ERR_LOT_NOT_AVAILABLE` otherwise);
    ... and the requested `yards` must not exceed the lot's `available_yards`
    (`ERR_INSUFFICIENT_YARDAGE` otherwise)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_allocation
    """
    order, line, lot = _state_vs_fiscal_fixture()
    res = api.create_material_allocation({
        "lot_id": lot["id"], "order_line_id": line["id"], "yards": 50.0,
    }, PLANNER)
    # Must be the state error, not the fiscal one
    assert res.status_code == 409
    err_id = res.json()["data"]["error_id"]
    assert err_id == "ERR_LOT_NOT_AVAILABLE"
    assert err_id != "ERR_INSUFFICIENT_YARDAGE"


# ---------------------------------------------------------------------------
# Instance: safety_beats_constraint_on_booking (priority 6 vs 7)
# ---------------------------------------------------------------------------

def _safety_vs_constraint_fixture():
    """Two orders (PLANT and COM lines), cell with capacity 1, no COM_HANDLING.
    First booking on PLANT line occupies [10:00,12:00). Second booking (COM
    line) would overlap AND miss the COM_HANDLING certification.
    Returns (cell, plant_line, com_line)."""
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(
        model_code="M-NP", category="CHAIR", base_fabric_yards=3.0,
        base_price_cents=50000, requires_pattern_match=False,
        option_rules=[
            {"fabric_grade": "A", "finish_code": "ANY", "allowed": True,
             "surcharge_pct": 0.0, "lead_time_adder_days": 0},
            {"fabric_grade": "COM", "finish_code": "ANY", "allowed": True,
             "surcharge_pct": 0.0, "lead_time_adder_days": 0},
        ],
    )
    spec_plant = create_spec(fabric_code="FAB-A", origin="PLANT", grade="A",
                             nominal_width_inches=54.0, price_per_yard_cents=3000)
    spec_com = create_spec(fabric_code="FAB-COM-Y", origin="CUSTOMER", grade="COM",
                           nominal_width_inches=54.0, com_credit_per_yard_cents=250)
    dealer = create_dealer()

    # PLANT line confirmed against stock
    order1, line1 = setup_order_with_line(model, spec_plant, dealer,
                                          order_number="ORD-P1", quantity=1)
    lot_plant = create_available_lot(spec_plant["id"], yards=30.0)
    confirm_order(order1["id"])

    # COM line, then resolve it
    order2, line2 = setup_order_with_line(model, spec_com, dealer,
                                          order_number="ORD-P2", quantity=1,
                                          fabric_source="COM")
    confirm_order(order2["id"])
    resolve_com_line_with_lot(line2, spec_com, usable_yards=10.0)

    # Cell without COM_HANDLING, capacity 1
    cell = create_cell("C-CUT", "CUTTING", 1, [])
    # PLANT booking occupies [10:00, 12:00)
    book_cell(cell["id"], line1["id"], "CUT",
              "2026-06-10T10:00:00Z", "2026-06-10T12:00:00Z")
    return cell, line1, line2


def test_safety_error_beats_overlap(api):
    """PRD §2.8: "6. **Business safety** — cell certifications cover the
    operation, the cell is not DOWN, flammability standards agree, and
    segregation of duties holds; failures yield `ERR_CELL_CERTIFICATION_MISSING`,
    `ERR_CELL_DOWN`, or `ERR_FLAMMABILITY_STANDARD_MISMATCH` (HTTP 422)... 7.
    **Business constraints** — option-matrix admissibility, cell-type matching,
    booking overlap and capacity..."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_booking
    """
    cell, plant_line, com_line = _safety_vs_constraint_fixture()
    # COM line on a cell lacking COM_HANDLING (safety, p6) AND overlapping
    # existing booking (constraint, p7)
    res = api.create_cell_booking({
        "cell_id": cell["id"],
        "order_line_id": com_line["id"],
        "operation": "CUT",
        "start_at": "2026-06-10T11:00:00Z",
        "end_at": "2026-06-10T13:00:00Z",
    }, PLANNER)
    validate_error(res, "ERR_CELL_CERTIFICATION_MISSING", expected_status=422)


def test_safety_error_id_is_not_overlap(api):
    """PRD §2.8: "the surfaced error is deterministic."
    PRD §3.6: "Booking a COM line demands a cell carrying the COM_HANDLING
    certification, else `ERR_CELL_CERTIFICATION_MISSING`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_booking
    """
    cell, plant_line, com_line = _safety_vs_constraint_fixture()
    res = api.create_cell_booking({
        "cell_id": cell["id"],
        "order_line_id": com_line["id"],
        "operation": "CUT",
        "start_at": "2026-06-10T11:00:00Z",
        "end_at": "2026-06-10T13:00:00Z",
    }, PLANNER)
    assert res.status_code == 422
    err_id = res.json()["data"]["error_id"]
    assert err_id == "ERR_CELL_CERTIFICATION_MISSING"
    assert err_id != "ERR_CELL_OVERLAP"
