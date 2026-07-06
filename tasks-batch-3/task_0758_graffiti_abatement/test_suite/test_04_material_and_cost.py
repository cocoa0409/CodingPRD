"""Material reservation stock movement and the abatement-cost calculation.

Queue A (Difficulty): boundary_precision_check (exact material), compensating_invariant
(reserve/release), dual_variant_calc (provisional vs final), combinatorial_formula
(per-line rounding order).
Queue B (Corner): validations / insufficient material.
"""
from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    setup_triaged_report, setup_dispatched, setup_completed,
    register_owner, register_site, register_crew, register_material,
    file_report, triage, cost_recovery_for_work_order, material_lines,
    create_work_order_payload,
)

COORD = TEST_USERS["coordinator_headers"]


# --------------------------------------------------------------------------
# boundary_precision_check / dispatch_material_exact_available_succeeds_boundary
# --------------------------------------------------------------------------
def test_reserve_exactly_available_succeeds(api):
    """PRD §3.3: "Finally, materials must be in stock: each requested line quantity is checked
    cumulatively across the request against that material's `quantity_available`, and any shortfall
    raises `ERR_INSUFFICIENT_MATERIAL` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/dispatch_material_exact_available_succeeds_boundary
    """
    scn = setup_triaged_report(api, ownership_type="PRIVATE", quantity_available=3.0)
    wo = validate_success(api.create_work_order(create_work_order_payload(
        scn["report_id"], scn["crew_id"], estimated_labor_hours=2.0,
        material_lines=material_lines(scn["material_id"], 3.0)), COORD), 201)
    assert wo["status"] == "SCHEDULED"
    mat = validate_success(api.get_material(scn["material_id"], COORD), 200)
    assert mat["quantity_available"] == 0.0
    assert mat["quantity_reserved"] == 3.0


def test_reserve_just_over_available_rejected(api):
    """PRD §3.3: "each requested line quantity is checked cumulatively across the request against that
    material's `quantity_available`, and any shortfall raises `ERR_INSUFFICIENT_MATERIAL` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/dispatch_material_exact_available_succeeds_boundary
    """
    scn = setup_triaged_report(api, ownership_type="PRIVATE", quantity_available=3.0)
    resp = api.create_work_order(create_work_order_payload(
        scn["report_id"], scn["crew_id"], estimated_labor_hours=2.0,
        material_lines=material_lines(scn["material_id"], 3.01)), COORD)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MATERIAL)


# --------------------------------------------------------------------------
# Corner: validations / dispatch_insufficient_material_single
# --------------------------------------------------------------------------
def test_dispatch_insufficient_material_single_rejected(api):
    """PRD §3.3: "Finally, materials must be in stock: each requested line quantity is checked
    cumulatively across the request against that material's `quantity_available`, and any shortfall
    raises `ERR_INSUFFICIENT_MATERIAL` (HTTP 409)."

    Design: Corner/validations/dispatch_insufficient_material_single_returns_insufficient_material
    """
    scn = setup_triaged_report(api, ownership_type="PRIVATE", quantity_available=3.0)
    resp = api.create_work_order(create_work_order_payload(
        scn["report_id"], scn["crew_id"], estimated_labor_hours=2.0,
        material_lines=material_lines(scn["material_id"], 4.0)), COORD)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MATERIAL)


# --------------------------------------------------------------------------
# compensating_invariant / material_reserve_release_conserves_total
# --------------------------------------------------------------------------
def test_dispatch_reservation_splits_but_conserves_total(api):
    """PRD §3.7: "The conserved invariant of the inventory is that `quantity_available` plus
    `quantity_reserved` is unchanged by any reserve-or-release pair: dispatch moves stock from
    available to reserved, release moves it back, and completion consumes reserved stock out of the
    system entirely."

    Design: Difficulty/compensating_invariant/material_reserve_release_conserves_total
    """
    scn = setup_dispatched(api, ownership_type="PRIVATE", est_labor=2.0, reserve_qty=3.0,
                           quantity_available=10.0)
    mat = validate_success(api.get_material(scn["material_id"], COORD), 200)
    assert mat["quantity_available"] == 7.0
    assert mat["quantity_reserved"] == 3.0
    assert mat["quantity_available"] + mat["quantity_reserved"] == 10.0


def test_cancel_releases_and_restores_material(api):
    """PRD §3.4: "**Cancelling** handles the pre-execution case: a coordinator may cancel a work order
    still in `SCHEDULED` ... releases every `RESERVED` reservation back to inventory exactly as recall
    does".
    PRD §3.4: "Recall **releases** rather than consumes materials: every `RESERVED` reservation moves
    to `RELEASED`, crediting its quantity back to the material's `quantity_available` and debiting the
    material's `quantity_reserved`."

    Design: Difficulty/compensating_invariant/material_reserve_release_conserves_total
    """
    scn = setup_dispatched(api, ownership_type="PRIVATE", est_labor=2.0, reserve_qty=3.0,
                           quantity_available=10.0)
    validate_success(api.cancel_work_order(scn["work_order_id"], {"reason": "duplicate"}, COORD), 200)
    mat = validate_success(api.get_material(scn["material_id"], COORD), 200)
    assert mat["quantity_available"] == 10.0
    assert mat["quantity_reserved"] == 0.0


# --------------------------------------------------------------------------
# dual_variant_calc / cost_provisional_vs_final_on_costrecovery
# --------------------------------------------------------------------------
def test_cost_provisional_estimated_at_dispatch(api):
    """PRD §3.3: "The labor line is the labor hours multiplied by a labor rate of 6500 cents per hour,
    rounded half up to whole cents, and stored as `labor_cost_cents`."
    PRD §3.3: "The provisional total, stored as `estimated_cost_cents`, is the sum of the rounded labor
    line, the summed material line, and the rounded admin fee."

    Design: Difficulty/dual_variant_calc/cost_provisional_vs_final_on_costrecovery
    """
    # est 2.5h * 6500 = 16250; 3.0L * 1200 = 3600; subtotal 19850; admin round(0.15*19850)=2978;
    # total 16250 + 3600 + 2978 = 22828.
    scn = setup_dispatched(api, ownership_type="PRIVATE", est_labor=2.5, reserve_qty=3.0,
                           unit_cost_cents=1200, quantity_available=10.0)
    cr = validate_success(api.get_cost_recovery(scn["cost_recovery_id"], COORD), 200)
    assert cr["estimated_cost_cents"] == 22828


def test_cost_final_assessed_diverges_from_provisional(api):
    """PRD §3.4: "the **final** variant of the abatement-cost calculation, which is identical in
    structure to the provisional variant but reads the work order's `actual_labor_hours` in place of
    the estimate and each reservation's `quantity_consumed` in place of its reserved quantity."
    PRD §3.4: "This recomputes `labor_cost_cents`, `material_cost_cents`, and `admin_fee_cents` on the
    recovery, sets `final_cost_cents` to the final total".

    Design: Difficulty/dual_variant_calc/cost_provisional_vs_final_on_costrecovery
    """
    # actual 3.0h * 6500 = 19500; consumed 3.0L * 1200 = 3600; subtotal 23100;
    # admin round(0.15*23100)=3465; total 19500 + 3600 + 3465 = 26565.
    scn = setup_completed(api, ownership_type="PRIVATE", est_labor=2.5, reserve_qty=3.0,
                          actual_labor=3.0, unit_cost_cents=1200, quantity_available=10.0)
    cr = validate_success(api.get_cost_recovery(scn["cost_recovery_id"], COORD), 200)
    assert cr["final_cost_cents"] == 26565
    assert cr["final_cost_cents"] != cr["estimated_cost_cents"]


# --------------------------------------------------------------------------
# combinatorial_formula / abatement_cost_per_line_rounding_order
# --------------------------------------------------------------------------
def _dispatch_two_material_lines(api):
    owner = register_owner(api)
    site = register_site(api, ownership_type="PRIVATE", property_owner_id=owner["id"])
    mat1 = register_material(api, name="P1", category="PAINT", unit_cost_cents=1333,
                             quantity_available=10.0)
    mat2 = register_material(api, name="P2", category="SOLVENT", unit_cost_cents=777,
                             quantity_available=10.0)
    crew = register_crew(api)
    rep = file_report(api, site["id"], severity="HIGH", surface_type="WALL")
    triage(api, rep["id"])
    wo = validate_success(api.create_work_order(create_work_order_payload(
        rep["id"], crew["id"], method="CHEMICAL", estimated_labor_hours=2.0,
        material_lines=[{"material_id": mat1["id"], "quantity": 2.5},
                        {"material_id": mat2["id"], "quantity": 1.5}]), COORD), 201)
    return cost_recovery_for_work_order(api, wo["id"])


def test_material_line_rounding_per_reservation_then_sum(api):
    """PRD §2.6: "each line item is rounded to whole cents first, and only the already-rounded lines
    are summed — the system never sums raw products and rounds once at the end."
    PRD §3.3: "The material line is computed per reservation — each reservation's quantity multiplied
    by its material's `unit_cost_cents`, rounded half up on its own — and those per-reservation amounts
    are then summed into `material_cost_cents`."

    Design: Difficulty/combinatorial_formula/abatement_cost_per_line_rounding_order
    """
    # round(2.5*1333)=3333 + round(1.5*777)=1166 -> 4499 (sum-then-round would give 4498).
    cr = _dispatch_two_material_lines(api)
    cr = validate_success(api.get_cost_recovery(cr["id"], COORD), 200)
    assert cr["material_cost_cents"] == 4499


def test_estimated_cost_uses_pinned_rounding_order(api):
    """PRD §3.3: "The subtotal is `labor_cost_cents` plus `material_cost_cents`; the administrative fee
    is 15 percent of that rounded subtotal, itself rounded half up, and stored as `admin_fee_cents`.
    The provisional total, stored as `estimated_cost_cents`, is the sum of the rounded labor line, the
    summed material line, and the rounded admin fee."

    Design: Difficulty/combinatorial_formula/abatement_cost_per_line_rounding_order
    """
    # labor round(2.0*6500)=13000; material 4499; subtotal 17499; admin round(0.15*17499)=2625;
    # total 13000 + 4499 + 2625 = 20124.
    cr = _dispatch_two_material_lines(api)
    cr = validate_success(api.get_cost_recovery(cr["id"], COORD), 200)
    assert cr["estimated_cost_cents"] == 20124
