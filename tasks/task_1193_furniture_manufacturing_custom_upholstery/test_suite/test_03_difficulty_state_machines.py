"""Difficulty Rule 3 — non_linear_state_machine (different entities)."""
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
    create_dealer,
    create_draft_cut_plan,
    create_model,
    create_order,
    create_spec,
    drive_line_through_production,
    get_success_data,
    make_quality_inspector_headers,
    record_cut_on_plan,
    resolve_com_line_with_lot,
    set_clock,
    setup_confirmed_order_with_plant_stock,
    setup_order_with_line,
    setup_three_cells,
    start_and_complete_booking,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]


# ---------------------------------------------------------------------------
# Instance: order_hold_and_rework_cycles (CustomerOrder cyclic)
# ---------------------------------------------------------------------------

def _order_cycle_fixture():
    """COM order in MATERIAL_HOLD; lot available to resolve. Returns
    (order, line, lot, cells)."""
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(
        model_code="M-HOLD", category="SOFA", base_fabric_yards=3.0,
        base_price_cents=80000, requires_pattern_match=False,
        option_rules=[{
            "fabric_grade": "COM", "finish_code": "ANY",
            "allowed": True, "surcharge_pct": 0.0, "lead_time_adder_days": 0,
        }],
    )
    spec = create_spec(fabric_code="FAB-COM-X", origin="CUSTOMER", grade="COM",
                       nominal_width_inches=54.0, com_credit_per_yard_cents=250)
    dealer = create_dealer()
    order, line = setup_order_with_line(
        model, spec, dealer, order_number="ORD-CYC", quantity=2,
        fabric_source="COM",
    )
    confirm_order(order["id"])
    return order, line, model, spec


def test_material_hold_then_confirmed_bubble_up(api):
    """PRD §3.3: "when the order's last `MATERIAL_SHORTFALL` line flips to
    `ALLOCATED`, the order returns to `CONFIRMED`."
    PRD §3.4: "When the passing lot is customer-owned, the plant immediately
    puts it to work: the system auto-creates an ACTIVE reservation allocation
    to the lot's bound order line for the smaller of the lot's `usable_yards`
    and that line's current `shortfall_yards`, then re-evaluates the line's
    shortfall and status."

    Design: Difficulty/non_linear_state_machine/order_hold_and_rework_cycles
    """
    order, line, model, spec = _order_cycle_fixture()
    # Cycle entry: order in MATERIAL_HOLD, line in MATERIAL_SHORTFALL
    ord_now = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_now["status"] == "MATERIAL_HOLD"
    line_now = validate_success(api.get_order_line(line["id"], SALES))
    assert line_now["status"] == "MATERIAL_SHORTFALL"

    # Resolve the shortfall: receive + inspect COM lot covering requirement
    resolve_com_line_with_lot(line_now, spec, usable_yards=10.0)

    ord_after = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_after["status"] == "CONFIRMED"
    line_after = validate_success(api.get_order_line(line["id"], SALES))
    assert line_after["status"] == "ALLOCATED"


def test_quality_rework_cycle_loops_back_to_sewn(api):
    """PRD §3.7: "Failing quality requires `rework_line_ids` naming a non-empty
    set of the order's lines, each currently `UPHOLSTERED`... On a failure, the
    order's `quality_result` becomes `FAILED`, each listed line loops back to
    `SEWN` — rework needs a fresh UPHOLSTER booking to climb out — and the
    order returns to `IN_PRODUCTION`."

    Design: Difficulty/non_linear_state_machine/order_hold_and_rework_cycles
    """
    order, line, model, spec = _order_cycle_fixture()
    # Resolve hold so we can drive the line
    resolve_com_line_with_lot(
        validate_success(api.get_order_line(line["id"], SALES)), spec,
        usable_yards=10.0,
    )
    # Drive through the production chain to UPHOLSTERED → QUALITY_REVIEW
    c_cut = create_cell("C-CUT", "CUTTING", 1, ["COM_HANDLING"])
    c_sew = create_cell("C-SEW", "SEWING", 1, ["COM_HANDLING"])
    c_uph = create_cell("C-UPH", "UPHOLSTERY", 1, ["COM_HANDLING"])
    line_now = validate_success(api.get_order_line(line["id"], SALES))

    b_cut = book_cell(c_cut["id"], line_now["id"], "CUT",
                      "2026-06-01T08:00:00Z", "2026-06-01T10:00:00Z")
    start_and_complete_booking(b_cut["id"])
    plan = create_approved_cut_plan(line_now, marker_length_yards=7.1)
    record_cut_on_plan(plan)
    b_sew = book_cell(c_sew["id"], line_now["id"], "SEW",
                      "2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z")
    start_and_complete_booking(b_sew["id"])
    b_uph = book_cell(c_uph["id"], line_now["id"], "UPHOLSTER",
                      "2026-06-01T13:00:00Z", "2026-06-01T15:00:00Z")
    start_and_complete_booking(b_uph["id"])

    ord_now = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_now["status"] == "QUALITY_REVIEW"
    line_now = validate_success(api.get_order_line(line["id"], SALES))
    assert line_now["status"] == "UPHOLSTERED"

    # Fail quality: rework loop
    qi = make_quality_inspector_headers("qi-1")
    fail_res = api.fail_quality(order["id"], {"rework_line_ids": [line["id"]]}, qi)
    failed = validate_success(fail_res, 200)
    assert failed["status"] == "IN_PRODUCTION"
    assert failed["quality_result"] == "FAILED"
    line_back = validate_success(api.get_order_line(line["id"], SALES))
    assert line_back["status"] == "SEWN"

    # Re-upholster: fresh UPHOLSTER booking climbs back to QUALITY_REVIEW
    b_uph2 = book_cell(c_uph["id"], line["id"], "UPHOLSTER",
                       "2026-06-02T08:00:00Z", "2026-06-02T10:00:00Z")
    start_and_complete_booking(b_uph2["id"])
    line_done = validate_success(api.get_order_line(line["id"], SALES))
    assert line_done["status"] == "UPHOLSTERED"
    ord_done = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_done["status"] == "QUALITY_REVIEW"


# ---------------------------------------------------------------------------
# Instance: cutplan_revision_loop (CutPlan cyclic)
# ---------------------------------------------------------------------------

def _revision_fixture():
    """ALLOCATED line qty 2, lot 30.0 measured 54. Returns (order, line, lot)."""
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-RL", category="CHAIR", base_fabric_yards=3.0,
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
        model, spec, dealer, order_number="ORD-RL", quantity=2, lot_yards=30.0,
    )
    return order, line, lot


def test_revision_clears_required_yards_final(api):
    """PRD §3.5: "Sending an APPROVED plan back to `DRAFT` — the revise loop —
    requires the plan in `APPROVED` (else `ERR_CUT_PLAN_NOT_APPROVED`) and
    clears the line's `required_yards_final` to null, re-evaluating the
    shortfall against the provisional requirement."

    Design: Difficulty/non_linear_state_machine/cutplan_revision_loop
    """
    order, line, lot = _revision_fixture()
    plan = create_approved_cut_plan(line, marker_length_yards=7.0)
    # 7.0 × 52 / 52 = 7.000
    line_after_approve = validate_success(api.get_order_line(line["id"], SALES))
    assert line_after_approve["required_yards_final"] == pytest.approx(7.000, abs=0.001)

    revised = validate_success(api.revise_cut_plan(plan["id"], PLANNER), 200)
    assert revised["status"] == "DRAFT"
    line_after_revise = validate_success(api.get_order_line(line["id"], SALES))
    assert line_after_revise["required_yards_final"] is None


def test_reapproving_recomputes_final_from_new_marker(api):
    """PRD §3.5: "At approval the system computes the final requirement: it
    takes the narrowest `measured_width_inches` among the lots holding ACTIVE
    allocations for the line, then sets `required_yards_final` to
    `marker_length_yards` multiplied by 52 ... divided by that measured width
    less the same 2-inch trim..."
    PRD §3.5: "Approval and revision may iterate any number of times before
    cutting."

    Design: Difficulty/non_linear_state_machine/cutplan_revision_loop
    """
    order, line, lot = _revision_fixture()
    plan = create_approved_cut_plan(line, marker_length_yards=7.0)
    validate_success(api.revise_cut_plan(plan["id"], PLANNER), 200)
    reapproved = validate_success(
        api.approve_cut_plan(plan["id"], {"marker_length_yards": 7.1}, PLANNER), 200
    )
    assert reapproved["status"] == "APPROVED"
    line_after = validate_success(api.get_order_line(line["id"], SALES))
    # 7.1 × 52 / 52 = 7.100
    assert line_after["required_yards_final"] == pytest.approx(7.100, abs=0.001)
