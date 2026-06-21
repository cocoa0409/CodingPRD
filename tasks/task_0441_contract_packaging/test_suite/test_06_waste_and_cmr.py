"""Waste reconciliation (planned vs actual, pinned per-line rounding) and the
customer-owned material ledger compensation invariants on a RUNNING cancel.
"""
from test_helpers import (
    validate_success, validate_paginated,
    create_customer, create_component, build_approved_recipe,
    create_production_line, create_crew,
    schedule_run, set_clock,
    setup_basic_scenario,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import RECEIVER, SCHEDULER, QA


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc / waste_planned_vs_actual_diverges_on_production_run
# ---------------------------------------------------------------------------

def test_waste_planned_vs_actual_diverge(api):
    """PRD 3.5: "The **planned** waste for a bill-of-materials line is the line's scrap-inflated required quantity at start less the unscrapped need — that is, the required quantity computed in Section 3.4 minus the product of `qty_per_unit` and `planned_units`; it reflects only the scrap reserved by the scrap factor and ignores actual output."
    PRD 3.5: "The **actual** waste for a line is the total actually consumed against that line — the sum of `consumed_qty` across the line's `LotConsumption` rows — minus the material embodied in the good units actually made, namely `qty_per_unit` multiplied by `actual_units_good`, rounded half up to three decimals."

    Design: Difficulty/dual_variant_calc/waste_planned_vs_actual_diverges_on_production_run
    """
    # ALMOND qty 2 scrap 5%, POUCH qty 1 scrap 0; planned 100, good 90.
    # planned waste: ALMOND 210-200=10, POUCH 0 => planned_total 10.000
    # actual waste:  ALMOND 210-(2*90)=30, POUCH 100-(1*90)=10 => actual_total 40.000
    scenario = setup_basic_scenario(almond_qty=2, almond_scrap=5, almond_received=500)
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")
    validate_success(api.start_run(run["id"],
        {"expected_line_version": scenario["line"]["version"]}, SCHEDULER))
    set_clock("2026-06-01T10:00:00Z")
    validate_success(api.complete_run(run["id"],
        {"actual_units_good": 90, "actual_units_scrapped": 10}, SCHEDULER))

    summary = validate_success(api.get_run_summary(run["id"], SCHEDULER))
    assert float(summary["planned_waste_total"]) == 10.000, (
        f"planned_waste_total must be 10.000, got {summary['planned_waste_total']}"
    )
    assert float(summary["actual_waste_total"]) == 40.000, (
        f"actual_waste_total must be 40.000, got {summary['actual_waste_total']}"
    )
    assert float(summary["planned_waste_total"]) != float(summary["actual_waste_total"]), (
        "planned and actual waste totals must diverge when good != planned"
    )


def test_waste_planned_independent_of_actual_output(api):
    """PRD 3.5: "The **planned** waste for a bill-of-materials line is the line's scrap-inflated required quantity at start less the unscrapped need — that is, the required quantity computed in Section 3.4 minus the product of `qty_per_unit` and `planned_units`; it reflects only the scrap reserved by the scrap factor and ignores actual output."

    Design: Difficulty/dual_variant_calc/waste_planned_vs_actual_diverges_on_production_run
    """
    # Same recipe, but complete with full good output (good=100). planned waste is
    # unchanged at 10.000 because it ignores actual output, while actual waste now
    # differs — proving the planned variant is output-independent.
    scenario = setup_basic_scenario(almond_qty=2, almond_scrap=5, almond_received=500)
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")
    validate_success(api.start_run(run["id"],
        {"expected_line_version": scenario["line"]["version"]}, SCHEDULER))
    set_clock("2026-06-01T10:00:00Z")
    validate_success(api.complete_run(run["id"],
        {"actual_units_good": 100, "actual_units_scrapped": 0}, SCHEDULER))

    summary = validate_success(api.get_run_summary(run["id"], SCHEDULER))
    # ALMOND planned waste 210-200=10, POUCH 0 => 10.000 regardless of output.
    assert float(summary["planned_waste_total"]) == 10.000, (
        f"planned_waste_total must ignore actual output and stay 10.000, "
        f"got {summary['planned_waste_total']}"
    )


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula / waste_totals_round_per_line_then_sum
# ---------------------------------------------------------------------------

def _three_line_run_at_good(api, actual_units_good, actual_units_scrapped):
    """Build a three-line recipe (ALMOND qty 2 scrap 5%, OIL qty 0.25 scrap 0,
    POUCH qty 1), schedule/start a planned_units=100 run, then complete it with the
    given output. Returns the run id."""
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    oil = create_component(customer["id"], "OIL", "Oil", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    validate_success(api.receive_lot(almond["id"], {"supplier_lot_code": "ALM-1",
        "received_qty": 500, "expiration_date": "2026-12-31T00:00:00Z"}, RECEIVER),
        expected_status=201)
    validate_success(api.receive_lot(oil["id"], {"supplier_lot_code": "OIL-1",
        "received_qty": 100, "expiration_date": "2026-12-31T00:00:00Z"}, RECEIVER),
        expected_status=201)
    validate_success(api.receive_lot(pouch["id"], {"supplier_lot_code": "POU-1",
        "received_qty": 1000, "expiration_date": "2027-12-31T00:00:00Z"}, RECEIVER),
        expected_status=201)

    recipe = validate_success(api.create_recipe({"customer_id": customer["id"],
        "name": "Granola", "target_fill_weight_g": 200, "fill_tolerance_pct": 5,
        "shelf_life_days": 90}, SCHEDULER), expected_status=201)
    validate_success(api.add_bom_line(recipe["id"],
        {"component_id": almond["id"], "qty_per_unit": 2, "scrap_factor_pct": 5,
         "expected_recipe_version": recipe["version"]}, SCHEDULER), expected_status=201)
    rec_after1 = validate_success(api.get_recipe(recipe["id"], SCHEDULER))
    validate_success(api.add_bom_line(recipe["id"],
        {"component_id": oil["id"], "qty_per_unit": 0.25, "scrap_factor_pct": 0,
         "expected_recipe_version": rec_after1["version"]}, SCHEDULER), expected_status=201)
    rec_after2 = validate_success(api.get_recipe(recipe["id"], SCHEDULER))
    validate_success(api.add_bom_line(recipe["id"],
        {"component_id": pouch["id"], "qty_per_unit": 1,
         "expected_recipe_version": rec_after2["version"]}, SCHEDULER), expected_status=201)
    validate_success(api.submit_recipe(recipe["id"], SCHEDULER))
    validate_success(api.approve_recipe(recipe["id"], QA))

    line = create_production_line()
    crew = create_crew()
    run = schedule_run(recipe["id"], line["id"], crew["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")
    validate_success(api.start_run(run["id"],
        {"expected_line_version": line["version"]}, SCHEDULER))
    set_clock("2026-06-01T10:00:00Z")
    validate_success(api.complete_run(run["id"],
        {"actual_units_good": actual_units_good,
         "actual_units_scrapped": actual_units_scrapped}, SCHEDULER))
    return run["id"]


def test_waste_total_rounds_per_line_then_sums(api):
    """PRD 3.5: "Both totals follow a pinned rounding order: each per-line waste figure is rounded half up to three decimals *first*, and the already-rounded per-line figures are then summed — round per line, then sum, never sum then round, and the resulting sum is not rounded again."

    Design: Difficulty/combinatorial_formula/waste_totals_round_per_line_then_sum
    """
    # planned 100, good 90 => actual: ALMOND 210-180=30.000, OIL 25-22.5=2.500,
    # POUCH 100-90=10.000 => actual_total 42.500.
    run_id = _three_line_run_at_good(api, actual_units_good=90, actual_units_scrapped=10)
    summary = validate_success(api.get_run_summary(run_id, SCHEDULER))
    assert float(summary["actual_waste_total"]) == 42.500, (
        f"round-per-line-then-sum must give 30.000+2.500+10.000=42.500, "
        f"got {summary['actual_waste_total']}"
    )


def test_waste_total_per_line_rounding_with_fractional_oil(api):
    """PRD 3.5: "the actual total sums the rounded actual waste across every line that has lot consumptions."

    Design: Difficulty/combinatorial_formula/waste_totals_round_per_line_then_sum
    """
    # planned 100, good 85 => actual per line: ALMOND 210-170=40.000,
    # OIL 25-(0.25*85)=25-21.25=3.750, POUCH 100-85=15.000 => total 58.750.
    run_id = _three_line_run_at_good(api, actual_units_good=85, actual_units_scrapped=15)
    summary = validate_success(api.get_run_summary(run_id, SCHEDULER))
    assert float(summary["actual_waste_total"]) == 58.750, (
        f"round-per-line-then-sum must give 40.000+3.750+15.000=58.750, "
        f"got {summary['actual_waste_total']}"
    )


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant / running_cancel_restores_material_remaining_invariant
# ---------------------------------------------------------------------------

def test_running_cancel_restores_material(api):
    """PRD 3.7: "A run in `RUNNING` has already drawn material, so its cancellation is a full compensation: every `LotConsumption` is reversed by restoring its `consumed_qty` to the corresponding lot's `remaining_qty`, any lot that had gone `DEPLETED` flips back `DEPLETED → AVAILABLE` once its remaining quantity rises above zero"

    Design: Difficulty/compensating_invariant/running_cancel_restores_material_remaining_invariant
    """
    # ALMOND lot 500; start draws 210 (lot -> 290); RUNNING cancel restores to 500.
    scenario = setup_basic_scenario(almond_qty=2, almond_scrap=5, almond_received=500)
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")
    validate_success(api.start_run(run["id"],
        {"expected_line_version": scenario["line"]["version"]}, SCHEDULER))
    validate_success(api.cancel_run(run["id"], SCHEDULER))

    lot = validate_success(api.get_component_lot(scenario["almond_lot"]["id"], SCHEDULER))
    assert float(lot["remaining_qty"]) == 500.000, (
        f"RUNNING cancel must restore remaining_qty to pre-start 500, "
        f"got {lot['remaining_qty']}"
    )
    assert lot["status"] == "AVAILABLE", (
        f"a restored lot returns to AVAILABLE, got {lot['status']}"
    )


def test_running_cancel_depleted_lot_flips_back_available(api):
    """PRD 3.7: "any lot that had gone `DEPLETED` flips back `DEPLETED → AVAILABLE` once its remaining quantity rises above zero"

    Design: Difficulty/compensating_invariant/running_cancel_restores_material_remaining_invariant
    """
    # ALMOND lot exactly 210; start drains it to 0 (DEPLETED); cancel flips it back.
    scenario = setup_basic_scenario(almond_qty=2, almond_scrap=5, almond_received=210)
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")
    validate_success(api.start_run(run["id"],
        {"expected_line_version": scenario["line"]["version"]}, SCHEDULER))
    depleted = validate_success(api.get_component_lot(scenario["almond_lot"]["id"], SCHEDULER))
    assert depleted["status"] == "DEPLETED", "precondition: lot drained to DEPLETED"

    validate_success(api.cancel_run(run["id"], SCHEDULER))
    restored = validate_success(api.get_component_lot(scenario["almond_lot"]["id"], SCHEDULER))
    assert float(restored["remaining_qty"]) == 210.000, (
        f"cancel restores the drained 210, got {restored['remaining_qty']}"
    )
    assert restored["status"] == "AVAILABLE", (
        f"a previously DEPLETED lot flips back to AVAILABLE, got {restored['status']}"
    )


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant / running_cancel_nets_cmr_ledger_to_zero
# ---------------------------------------------------------------------------

def test_running_cancel_nets_cmr_to_zero(api):
    """PRD 3.7: "When a `RUNNING` run is cancelled, the compensation also emits, for each customer-owned consumed component, a `RETURN_ON_CANCEL` entry whose `delta_qty` is the positive of the consumed quantity, so that the running cancel restores exactly the material it drew and the customer's reconciled balance for each component nets back to zero."

    Design: Difficulty/compensating_invariant/running_cancel_nets_cmr_ledger_to_zero
    """
    # Customer owns components => ALMOND is customer-owned. Start emits CONSUME -210,
    # RUNNING cancel emits RETURN_ON_CANCEL +210, ledger nets to 0.
    scenario = setup_basic_scenario(owns_components=True, almond_qty=2,
                                    almond_scrap=5, almond_received=500)
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")
    validate_success(api.start_run(run["id"],
        {"expected_line_version": scenario["line"]["version"]}, SCHEDULER))
    validate_success(api.cancel_run(run["id"], SCHEDULER))

    entries, _meta = validate_paginated(
        api.list_cmr_ledger_entries(RECEIVER, params={"production_run_id": run["id"]})
    )
    almond_entries = [e for e in entries if e["component_id"] == scenario["almond"]["id"]]
    total = sum(float(e["delta_qty"]) for e in almond_entries)
    assert abs(total) < 1e-9, (
        f"CMR ledger for the run's customer-owned component must net to 0, got {total}"
    )
    reasons = {e["reason"]: float(e["delta_qty"]) for e in almond_entries}
    assert reasons.get("CONSUME") == -210.000, (
        f"start must emit a CONSUME entry of -210.000, got {reasons.get('CONSUME')}"
    )
    assert reasons.get("RETURN_ON_CANCEL") == 210.000, (
        f"RUNNING cancel must emit a RETURN_ON_CANCEL entry of +210.000, "
        f"got {reasons.get('RETURN_ON_CANCEL')}"
    )


def test_running_cancel_emits_return_on_cancel_entry(api):
    """PRD 3.7: "a `RETURN_ON_CANCEL` entry whose `delta_qty` is the positive of the consumed quantity"

    Design: Difficulty/compensating_invariant/running_cancel_nets_cmr_ledger_to_zero
    """
    scenario = setup_basic_scenario(owns_components=True, almond_qty=2,
                                    almond_scrap=5, almond_received=500)
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")
    validate_success(api.start_run(run["id"],
        {"expected_line_version": scenario["line"]["version"]}, SCHEDULER))
    validate_success(api.cancel_run(run["id"], SCHEDULER))

    entries, _meta = validate_paginated(
        api.list_cmr_ledger_entries(RECEIVER, params={"production_run_id": run["id"]})
    )
    returns = [e for e in entries
               if e["reason"] == "RETURN_ON_CANCEL"
               and e["component_id"] == scenario["almond"]["id"]]
    assert len(returns) == 1, (
        f"exactly one RETURN_ON_CANCEL entry expected for the component, got {len(returns)}"
    )
    assert float(returns[0]["delta_qty"]) == 210.000, (
        f"RETURN_ON_CANCEL delta_qty must equal +consumed 210.000, "
        f"got {returns[0]['delta_qty']}"
    )
