"""Difficulty Rule 9 — compensating_invariant (different conserved quantities)."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    book_cell,
    confirm_order,
    create_available_lot,
    create_cell,
    create_dealer,
    create_model,
    create_spec,
    get_success_data,
    set_clock,
    setup_confirmed_order_with_plant_stock,
    setup_order_with_line,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
RECEIVER = TEST_USERS["material_receiver_headers"]


# ---------------------------------------------------------------------------
# Instance: cell_hours_book_release_conserved (conserved quantity = cell hours)
# ---------------------------------------------------------------------------

def _cell_hours_fixture():
    """ALLOCATED line + capacity-1 cell. Returns (line, cell)."""
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
        model, spec, dealer, order_number="ORD-HRS", quantity=1, lot_yards=30.0,
    )
    cell = create_cell("C-CUT", "CUTTING", 1, [])
    return line, cell


def test_booking_adds_to_committed_hours(api):
    """PRD §3.6: "the cell's `committed_hours` — the summed `duration_hours` of
    its bookings in `BOOKED` or `IN_PROGRESS` — is recomputed whenever a
    booking is created, started, completed, or released."

    Design: Difficulty/compensating_invariant/cell_hours_book_release_conserved
    """
    line, cell = _cell_hours_fixture()
    cell_before = validate_success(api.get_cell(cell["id"], PLANNER))
    assert cell_before["committed_hours"] == pytest.approx(0.0, abs=0.001)

    booking = book_cell(cell["id"], line["id"], "CUT",
                        "2026-06-09T08:00:00Z", "2026-06-09T11:30:00Z")
    cell_mid = validate_success(api.get_cell(cell["id"], PLANNER))
    assert cell_mid["committed_hours"] == pytest.approx(3.5, abs=0.001)


def test_release_returns_committed_hours_to_zero(api):
    """PRD §3.6: "Releasing (only from `BOOKED`, else `ERR_BOOKING_INVALID_STATE`)
    moves the booking to `RELEASED` and recomputes the cell's committed hours."

    Design: Difficulty/compensating_invariant/cell_hours_book_release_conserved
    """
    line, cell = _cell_hours_fixture()
    booking = book_cell(cell["id"], line["id"], "CUT",
                        "2026-06-09T08:00:00Z", "2026-06-09T11:30:00Z")
    validate_success(api.release_booking(booking["id"], PLANNER), 200)
    cell_end = validate_success(api.get_cell(cell["id"], PLANNER))
    assert cell_end["committed_hours"] == pytest.approx(0.0, abs=0.001)


# ---------------------------------------------------------------------------
# Instance: lot_yardage_allocate_release_conserved (conserved = fabric yards)
# ---------------------------------------------------------------------------

def _yardage_fixture():
    """MATERIAL_SHORTFALL line qty 4 (provisional 14.331); AVAILABLE lot 20.0."""
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
    # Confirm with NO stock — line goes MATERIAL_SHORTFALL
    order, line = setup_order_with_line(model, spec, dealer, order_number="ORD-YRD",
                                        quantity=4)
    confirm_order(order["id"])
    # Now add an AVAILABLE lot of 20.0
    lot = create_available_lot(spec["id"], yards=20.0, measured_width_inches=54.0)
    return order, line, lot


def test_allocation_moves_lot_yardage(api):
    """PRD §3.4: "A lot's allocatable position is its `available_yards`: its
    `usable_yards` (zero while unset) minus the summed `yards` of its ACTIVE
    allocations minus the summed `consumed_yards` of its CONSUMED allocations."
    PRD §3.4: "Creation recomputes the lot and line derived fields, re-runs
    the shortfall evaluation..."

    Design: Difficulty/compensating_invariant/lot_yardage_allocate_release_conserved
    """
    order, line, lot = _yardage_fixture()
    alloc = validate_success(api.create_material_allocation({
        "lot_id": lot["id"], "order_line_id": line["id"], "yards": 4.5,
    }, PLANNER), 201)
    assert alloc["status"] == "ACTIVE"

    lot_mid = validate_success(api.get_material_lot(lot["id"], RECEIVER))
    assert lot_mid["allocated_yards"] == pytest.approx(4.5, abs=0.001)
    assert lot_mid["available_yards"] == pytest.approx(15.5, abs=0.001)

    line_mid = validate_success(api.get_order_line(line["id"], SALES))
    assert line_mid["allocated_yards"] == pytest.approx(4.5, abs=0.001)
    # 14.331 - 4.5 = 9.831 short
    assert line_mid["shortfall_yards"] == pytest.approx(9.831, abs=0.001)
    assert line_mid["status"] == "MATERIAL_SHORTFALL"


def test_release_restores_lot_yardage(api):
    """PRD §3.4: "Release moves it to `RELEASED`, recomputes the lot's and
    line's derived fields, re-runs the shortfall evaluation — which may flip
    the line `ALLOCATED` → `MATERIAL_SHORTFALL`..."

    Design: Difficulty/compensating_invariant/lot_yardage_allocate_release_conserved
    """
    order, line, lot = _yardage_fixture()
    alloc = validate_success(api.create_material_allocation({
        "lot_id": lot["id"], "order_line_id": line["id"], "yards": 4.5,
    }, PLANNER), 201)
    validate_success(api.release_allocation(alloc["id"], PLANNER), 200)

    lot_end = validate_success(api.get_material_lot(lot["id"], RECEIVER))
    assert lot_end["allocated_yards"] == pytest.approx(0.0, abs=0.001)
    assert lot_end["available_yards"] == pytest.approx(20.0, abs=0.001)
    # Invariant: allocated + available == usable (unchanged at 20.0)
    assert (lot_end["allocated_yards"] + lot_end["available_yards"]) == pytest.approx(
        lot_end["usable_yards"], abs=0.001
    )

    line_end = validate_success(api.get_order_line(line["id"], SALES))
    assert line_end["allocated_yards"] == pytest.approx(0.0, abs=0.001)
    assert line_end["shortfall_yards"] == pytest.approx(14.331, abs=0.001)
