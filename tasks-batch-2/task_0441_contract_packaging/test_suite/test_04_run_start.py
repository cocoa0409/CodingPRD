"""Starting a run: FEFO consumption, depletion cascade, lot-code minting,
line OCC, and the start-specific safety gates (allergen, expiry, material) with
their priority ordering.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_customer, create_component, create_recipe, add_bom_line,
    create_production_line, create_crew, build_approved_recipe,
    setup_basic_scenario, schedule_run, set_clock,
    setup_dirty_line_with_clean_recipe,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import RECEIVER, SCHEDULER, QA


def _start(api, run_id, line_version):
    return api.start_run(run_id, {"expected_line_version": line_version}, SCHEDULER)


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula / material_consumption_three_inputs_fefo_tiered_draw
# ---------------------------------------------------------------------------

def test_material_consumption_fefo_tiered_draw(api):
    """PRD 3.4: "The line's total required quantity is that gross-per-unit figure multiplied by the run's `planned_units`, rounded half up to three decimals. The lots that satisfy this requirement are drawn first-expired-first-out ... the system orders by `expiration_date` ascending, breaking ties by `created_at` ascending, and draws from each in turn. The quantity drawn from any one lot is the smaller of that lot's `remaining_qty` and the residual still required after earlier lots"

    Design: Difficulty/combinatorial_formula/material_consumption_three_inputs_fefo_tiered_draw
    """
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    lot_a = api.receive_lot(almond["id"], {"supplier_lot_code": "ALM-A",
        "received_qty": 150, "expiration_date": "2026-07-01T00:00:00Z"}, RECEIVER)
    lot_a = validate_success(lot_a, expected_status=201)
    lot_b = api.receive_lot(almond["id"], {"supplier_lot_code": "ALM-B",
        "received_qty": 200, "expiration_date": "2026-08-01T00:00:00Z"}, RECEIVER)
    lot_b = validate_success(lot_b, expected_status=201)
    validate_success(api.receive_lot(pouch["id"], {"supplier_lot_code": "POU-A",
        "received_qty": 1000, "expiration_date": "2027-01-01T00:00:00Z"}, RECEIVER),
        expected_status=201)
    recipe = build_approved_recipe(customer["id"], almond["id"], pouch["id"],
                                   ingredient_qty=2, ingredient_scrap=5)
    line = create_production_line()
    crew = create_crew()
    run = schedule_run(recipe["id"], line["id"], crew["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")

    # required = round(2*(1+5/100)*100) = 210; FEFO: 150 from lot A, 60 from lot B.
    validate_success(_start(api, run["id"], line["version"]))

    after_a = validate_success(api.get_component_lot(lot_a["id"], SCHEDULER))
    after_b = validate_success(api.get_component_lot(lot_b["id"], SCHEDULER))
    assert float(after_a["remaining_qty"]) == 0.000, (
        f"earliest-expiring lot drawn to zero, got {after_a['remaining_qty']}"
    )
    assert after_a["status"] == "DEPLETED", (
        f"a lot drawn to zero moves to DEPLETED, got {after_a['status']}"
    )
    assert float(after_b["remaining_qty"]) == 140.000, (
        f"later lot supplies the residual 60 (200-60=140), got {after_b['remaining_qty']}"
    )


def test_material_consumption_required_qty_three_inputs(api):
    """PRD 3.4: "The gross draw per finished unit is the line's `qty_per_unit` inflated by its scrap factor — that is, `qty_per_unit` multiplied by one plus `scrap_factor_pct` divided by 100. The line's total required quantity is that gross-per-unit figure multiplied by the run's `planned_units`, rounded half up to three decimals."

    Design: Difficulty/combinatorial_formula/material_consumption_three_inputs_fefo_tiered_draw
    """
    # qty_per_unit=2, scrap=5%, planned=100 => required = round(2*1.05*100,3) = 210.000.
    # A single ample lot proves the three-input formula value via total consumed_qty.
    scenario = setup_basic_scenario(almond_qty=2, almond_scrap=5, almond_received=1000)
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")
    validate_success(_start(api, run["id"], scenario["line"]["version"]))

    rows = validate_success(api.list_run_lot_consumptions(run["id"], SCHEDULER))
    almond_rows = [r for r in rows
                   if r["component_lot_id"] == scenario["almond_lot"]["id"]]
    total = sum(float(r["consumed_qty"]) for r in almond_rows)
    assert total == 210.000, (
        f"required draw from the three inputs (2 * 1.05 * 100) must be 210.000, got {total}"
    )


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade / start_consume_depletes_lot_then_recomputes_on_hand_depth3
# ---------------------------------------------------------------------------

def test_start_depletes_lot_and_recomputes_on_hand(api):
    """PRD 3.4: "each touched lot's `remaining_qty` is decremented by the quantity drawn, and any lot whose `remaining_qty` reaches zero moves `AVAILABLE → DEPLETED` and is no longer selectable for future runs. Each consumed component's `on_hand_qty` is recomputed and the `reserved_qty` this run had been holding is released."

    Design: Difficulty/transitive_cascade/start_consume_depletes_lot_then_recomputes_on_hand_depth3
    """
    # single ALMOND lot of exactly 210; recipe consumes exactly 210 -> deplete.
    scenario = setup_basic_scenario(almond_qty=2, almond_scrap=5, almond_received=210)
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")
    validate_success(_start(api, run["id"], scenario["line"]["version"]))

    lot = validate_success(api.get_component_lot(scenario["almond_lot"]["id"], SCHEDULER))
    assert float(lot["remaining_qty"]) == 0.000, f"lot drained, got {lot['remaining_qty']}"
    assert lot["status"] == "DEPLETED", f"lot at zero is DEPLETED, got {lot['status']}"
    comp = validate_success(api.get_component(scenario["almond"]["id"], SCHEDULER))
    assert float(comp["on_hand_qty"]) == 0.000, (
        f"on_hand_qty recomputes to 0 once the only lot is DEPLETED, "
        f"got {comp['on_hand_qty']}"
    )


def test_start_partial_draw_keeps_lot_available_and_recomputes_on_hand(api):
    """PRD 3.4: "each touched lot's `remaining_qty` is decremented by the quantity drawn, and any lot whose `remaining_qty` reaches zero moves `AVAILABLE → DEPLETED` and is no longer selectable for future runs. Each consumed component's `on_hand_qty` is recomputed and the `reserved_qty` this run had been holding is released."

    Design: Difficulty/transitive_cascade/start_consume_depletes_lot_then_recomputes_on_hand_depth3
    """
    # Lot 300, draw 210 => remaining 90 (still AVAILABLE since > 0), on_hand 90.
    scenario = setup_basic_scenario(almond_qty=2, almond_scrap=5, almond_received=300)
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")
    validate_success(_start(api, run["id"], scenario["line"]["version"]))

    lot = validate_success(api.get_component_lot(scenario["almond_lot"]["id"], SCHEDULER))
    assert float(lot["remaining_qty"]) == 90.000, (
        f"a partially drawn lot keeps 300-210=90, got {lot['remaining_qty']}"
    )
    assert lot["status"] == "AVAILABLE", (
        f"a lot above zero stays AVAILABLE (no DEPLETED), got {lot['status']}"
    )
    comp = validate_success(api.get_component(scenario["almond"]["id"], SCHEDULER))
    assert float(comp["on_hand_qty"]) == 90.000, (
        f"on_hand_qty recomputes to the AVAILABLE remaining 90, got {comp['on_hand_qty']}"
    )


# ---------------------------------------------------------------------------
# Queue B — calculations / lot_code_format_customer_date_recipe_seq
# ---------------------------------------------------------------------------

def test_lot_code_minted_at_start(api):
    """PRD 3.4: "The lot code is then assembled as the customer's `code`, a hyphen, the eight-digit pack date, a hyphen, a four-character recipe short token, a hyphen, and the sequence zero-padded to three digits. The recipe short token is the first four alphanumeric characters of the recipe's `name` uppercased"

    Design: Corner/calculations/lot_code_format_customer_date_recipe_seq
    """
    scenario = setup_basic_scenario(recipe_name="Granola")
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")

    started = validate_success(_start(api, run["id"], scenario["line"]["version"]))
    assert started["lot_code"] == "ACME-20260601-GRAN-001", (
        f"lot_code must follow code-date-short-seq, got {started['lot_code']}"
    )


# ---------------------------------------------------------------------------
# Queue B — state_machines / start_run_with_expired_lot_rejected
# ---------------------------------------------------------------------------

def test_start_with_expired_lot_rejected(api):
    """PRD 3.4: "no physical lot selected for consumption may have an `expiration_date` at or before the logical clock at the moment of start; a chosen lot that is expired blocks the start with `ERR_LOT_EXPIRED`."

    Design: Corner/state_machines/start_run_with_expired_lot_rejected
    """
    # ALMOND lot expires 2026-05-01; clock advanced to 2026-06-01 => expired.
    scenario = setup_basic_scenario(almond_exp="2026-05-01T00:00:00Z")
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")

    resp = _start(api, run["id"], scenario["line"]["version"])
    validate_error(resp, ApiErrorId.ERR_LOT_EXPIRED.value)


# ---------------------------------------------------------------------------
# Queue B — state_machines / start_run_insufficient_material_rejected
# ---------------------------------------------------------------------------

def test_start_insufficient_material_rejected(api):
    """PRD 3.4: "for each bill-of-materials line, the aggregate `remaining_qty` of the component's available, non-expired lots must cover the run's scrap-inflated required quantity for that line; a shortfall is rejected with `ERR_INSUFFICIENT_MATERIAL`."

    Design: Corner/state_machines/start_run_insufficient_material_rejected
    """
    # need 210 ALMOND but only 50 available (clean line, no allergen issue).
    scenario = setup_basic_scenario(almond_qty=2, almond_scrap=5, almond_received=50)
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")

    resp = _start(api, run["id"], scenario["line"]["version"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_MATERIAL.value)


# ---------------------------------------------------------------------------
# Queue B — state_machines / sanitation_clears_residue_allows_allergen_free_run
# ---------------------------------------------------------------------------

def test_sanitation_clears_residue_allows_allergen_free_run(api):
    """PRD 3.4: "the only way to clear the block without changing the recipe is a sanitation event on that line."
    PRD 3.7: "snapshots the line's `current_allergen_residue` onto its own `cleared_allergens`, records the cleaned `line_id`, empties the line's residue, and increments the line's `version` by one."

    Design: Corner/state_machines/sanitation_clears_residue_allows_allergen_free_run
    """
    ctx = setup_dirty_line_with_clean_recipe(almond_received=1000)
    # Sanitation clears the PEANUT residue and bumps the line version.
    validate_success(
        api.create_sanitation_event(ctx["line"]["id"], QA), expected_status=201
    )
    line_after_san = validate_success(api.get_production_line(ctx["line"]["id"], SCHEDULER))
    set_clock("2026-06-01T13:00:00Z")

    started = validate_success(_start(api, ctx["run_alm"]["id"], line_after_san["version"]))
    assert started["status"] == "RUNNING", (
        f"after sanitation the allergen-free run must start, got {started['status']}"
    )


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict / start_allergen_safety_beats_insufficient_material_fiscal
# (also owns Corner stub state_machines/error_allergen_changeover_on_start)
# ---------------------------------------------------------------------------

def test_allergen_changeover_beats_insufficient_material(api):
    """PRD 3.8: "On run start specifically, the order of the transition-specific checks is allergen changeover (`ERR_ALLERGEN_CHANGEOVER_REQUIRED`) first, then expired lots (`ERR_LOT_EXPIRED`), then material sufficiency (`ERR_INSUFFICIENT_MATERIAL`)."
    PRD 3.4: "a line still dirty with an allergen the incoming recipe does not declare ... is blocked with `ERR_ALLERGEN_CHANGEOVER_REQUIRED"

    Design: Difficulty/priority_pair_validation_conflict/start_allergen_safety_beats_insufficient_material_fiscal
    """
    # Line PEANUT-dirty; almond run is allergen-free AND its lot holds only 50 (<210).
    ctx = setup_dirty_line_with_clean_recipe(almond_received=50)
    set_clock("2026-06-01T12:00:00Z")

    resp = _start(api, ctx["run_alm"]["id"], ctx["line_version_dirty"])
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_CHANGEOVER_REQUIRED.value)


def test_allergen_changeover_blocks_clean_recipe_on_dirty_line(api):
    """PRD 3.4: "most sharply, packing an allergen-free recipe on an allergen-contaminated line — is blocked with `ERR_ALLERGEN_CHANGEOVER_REQUIRED"

    Design: Difficulty/priority_pair_validation_conflict/start_allergen_safety_beats_insufficient_material_fiscal
    """
    # Same dirty line but ample almond stock — isolates the allergen gate alone.
    ctx = setup_dirty_line_with_clean_recipe(almond_received=1000)
    set_clock("2026-06-01T12:00:00Z")

    resp = _start(api, ctx["run_alm"]["id"], ctx["line_version_dirty"])
    validate_error(resp, ApiErrorId.ERR_ALLERGEN_CHANGEOVER_REQUIRED.value)


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict / start_invalid_state_beats_allergen_safety
# ---------------------------------------------------------------------------

def test_invalid_state_beats_allergen_on_start(api):
    """PRD 3.8: "For state-transition endpoints the state precondition is checked before the transition-specific business rules: a transition requested from a state in which it is undefined yields `ERR_INVALID_STATE`."
    PRD 3.4: "A `Scheduler` starts a run that is currently `SCHEDULED`; a start from any other state is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/start_invalid_state_beats_allergen_safety
    """
    ctx = setup_dirty_line_with_clean_recipe(almond_received=1000)
    # Cancel the still-SCHEDULED almond run, then try to start it on the dirty line.
    validate_success(api.cancel_run(ctx["run_alm"]["id"], SCHEDULER))
    set_clock("2026-06-01T12:00:00Z")

    resp = _start(api, ctx["run_alm"]["id"], ctx["line_version_dirty"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_start_already_cancelled_run_invalid_state(api):
    """PRD 3.4: "A `Scheduler` starts a run that is currently `SCHEDULED`; a start from any other state is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/priority_pair_validation_conflict/start_invalid_state_beats_allergen_safety
    """
    # Clean line, ample stock: cancelling first isolates the state check.
    scenario = setup_basic_scenario(almond_received=1000)
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    validate_success(api.cancel_run(run["id"], SCHEDULER))
    set_clock("2026-06-01T08:00:00Z")

    resp = _start(api, run["id"], scenario["line"]["version"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Queue B — cross_cutting_complexity_layers / occ_stale_line_version_on_run_start
# ---------------------------------------------------------------------------

def test_start_stale_line_version_rejected(api):
    """PRD 2.7: "the start request must carry `expected_line_version`, the client's last observed `version` of the referenced `ProductionLine`. If that value does not equal the line's current `version ... the start is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_line_version_on_run_start
    """
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    validate_success(api.receive_lot(almond["id"], {"supplier_lot_code": "ALM-1",
        "received_qty": 1000, "expiration_date": "2026-12-31T00:00:00Z"}, RECEIVER),
        expected_status=201)
    validate_success(api.receive_lot(pouch["id"], {"supplier_lot_code": "POU-1",
        "received_qty": 1000, "expiration_date": "2027-12-31T00:00:00Z"}, RECEIVER),
        expected_status=201)
    recipe = build_approved_recipe(customer["id"], almond["id"], pouch["id"])
    line = create_production_line()
    crew1 = create_crew(name="Crew 1", rest_buffer_minutes=0)
    crew2 = create_crew(name="Crew 2", rest_buffer_minutes=0)
    run1 = schedule_run(recipe["id"], line["id"], crew1["id"],
                        scheduled_start="2026-06-01T08:00:00Z")
    run2 = schedule_run(recipe["id"], line["id"], crew2["id"],
                        scheduled_start="2026-06-01T10:00:00Z")
    set_clock("2026-06-01T08:00:00Z")
    started1 = validate_success(_start(api, run1["id"], line["version"]))
    # Read the line's current (advanced) version, then deliberately go stale by one.
    line_now = validate_success(api.get_production_line(line["id"], SCHEDULER))
    set_clock("2026-06-01T10:00:00Z")

    resp = _start(api, run2["id"], line_now["version"] - 1)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
