"""Difficulty Rule 8 — resource_temporal_overlap (different interval semantics)."""
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
    create_model,
    create_order,
    create_showroom_sample_payload,
    create_spec,
    get_success_data,
    set_clock,
    setup_confirmed_order_with_plant_stock,
    setup_order_with_line,
    validate_error,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]


# ---------------------------------------------------------------------------
# Instance: cell_capacity_aggregate_overlap (aggregate capacity, inclusive)
# ---------------------------------------------------------------------------

def _capacity_fixture():
    """ALLOCATED line; capacity-2 CUTTING cell. Returns (line, cell)."""
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
        model, spec, dealer, order_number="ORD-CAP", quantity=1, lot_yards=30.0,
    )
    cell = create_cell("C-CAP", "CUTTING", 2, [])
    return line, cell


def test_exactly_at_capacity_is_allowed(api):
    """PRD §3.6: "On a multi-capacity cell, the new booking is rejected with
    `ERR_CELL_CAPACITY_EXCEEDED` only when it would push the count of
    overlapping active bookings above `capacity_slots`; landing exactly at
    capacity is allowed."

    Design: Difficulty/resource_temporal_overlap/cell_capacity_aggregate_overlap
    """
    line, cell = _capacity_fixture()
    b1 = validate_success(api.create_cell_booking({
        "cell_id": cell["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-08T10:00:00Z", "end_at": "2026-06-08T12:00:00Z",
    }, PLANNER), 201)
    b2 = validate_success(api.create_cell_booking({
        "cell_id": cell["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-08T11:00:00Z", "end_at": "2026-06-08T13:00:00Z",
    }, PLANNER), 201)
    assert b1["status"] == "BOOKED"
    assert b2["status"] == "BOOKED"
    cell_after = validate_success(api.get_cell(cell["id"], PLANNER))
    assert cell_after["committed_hours"] == pytest.approx(4.0, abs=0.001)


def test_exceeding_capacity_rejected(api):
    """PRD §3.6: "On a multi-capacity cell, the new booking is rejected with
    `ERR_CELL_CAPACITY_EXCEEDED` only when it would push the count of
    overlapping active bookings above `capacity_slots`."

    Design: Difficulty/resource_temporal_overlap/cell_capacity_aggregate_overlap
    """
    line, cell = _capacity_fixture()
    api.create_cell_booking({
        "cell_id": cell["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-08T10:00:00Z", "end_at": "2026-06-08T12:00:00Z",
    }, PLANNER)
    api.create_cell_booking({
        "cell_id": cell["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-08T11:00:00Z", "end_at": "2026-06-08T13:00:00Z",
    }, PLANNER)
    # Third overlapping booking pushes count from 2 to 3 — exceeds capacity 2
    res = api.create_cell_booking({
        "cell_id": cell["id"], "order_line_id": line["id"], "operation": "CUT",
        "start_at": "2026-06-08T11:30:00Z", "end_at": "2026-06-08T12:30:00Z",
    }, PLANNER)
    validate_error(res, "ERR_CELL_CAPACITY_EXCEEDED", expected_status=409)


# ---------------------------------------------------------------------------
# Instance: sample_serial_refurb_gap (closed loan + refurb gap)
# ---------------------------------------------------------------------------

def _serial_fixture():
    """Dealer + model; sample S1 (UNIT-77) created and returned at clock 2026-05-20.
    Returns (dealer, model, s1)."""
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP", category="CHAIR", base_fabric_yards=3.0,
                         base_price_cents=50000, requires_pattern_match=False,
                         option_rules=[{
                             "fabric_grade": "A", "finish_code": "ESPRESSO",
                             "allowed": True, "surcharge_pct": 0.0,
                             "lead_time_adder_days": 0,
                         }])
    dealer = create_dealer(sample_allowance_cents=100000)
    s1 = get_success_data(api_client.create_showroom_sample(
        create_showroom_sample_payload(
            dealer_id=dealer["id"], model_id=model["id"],
            unit_serial="UNIT-77", sample_value_cents=10000, due_back_days=30,
        ), SALES))
    set_clock("2026-05-20T00:00:00Z")
    get_success_data(api_client.return_sample(s1["id"], SALES))
    return dealer, model, s1


def test_reloan_within_refurb_gap_rejected(api):
    """PRD §3.8: "A returned serial goes through refurbishment: if the serial's
    last `RETURNED` sample came back less than five days ago on the logical
    clock — that is, its `returned_at` plus five days is still in the future —
    a new loan of that serial is rejected with `ERR_SAMPLE_IN_REFURB`."

    Design: Difficulty/resource_temporal_overlap/sample_serial_refurb_gap
    """
    dealer, model, s1 = _serial_fixture()
    # returned_at = 2026-05-20; + 5 days = 2026-05-25; clock at 2026-05-24 is inside the gap
    set_clock("2026-05-24T00:00:00Z")
    res = api.create_showroom_sample(create_showroom_sample_payload(
        dealer_id=dealer["id"], model_id=model["id"],
        unit_serial="UNIT-77", sample_value_cents=10000, due_back_days=30,
    ), SALES)
    validate_error(res, "ERR_SAMPLE_IN_REFURB", expected_status=409)


def test_reloan_at_exactly_five_days_succeeds(api):
    """PRD §3.8: "a request landing exactly on the boundary is allowed."

    Design: Difficulty/resource_temporal_overlap/sample_serial_refurb_gap
    """
    dealer, model, s1 = _serial_fixture()
    # returned_at = 2026-05-20T00:00:00Z; +5 days = 2026-05-25T00:00:00Z (inclusive)
    set_clock("2026-05-25T00:00:00Z")
    s2 = validate_success(api.create_showroom_sample(create_showroom_sample_payload(
        dealer_id=dealer["id"], model_id=model["id"],
        unit_serial="UNIT-77", sample_value_cents=10000, due_back_days=30,
    ), SALES), 201)
    assert s2["disposition"] == "ON_LOAN"
    dealer_now = validate_success(api.get_dealer_account(dealer["id"], SALES))
    assert dealer_now["outstanding_sample_value_cents"] == 10000
