"""Completing a run (run rate, over-run gate), the QA fork (release vs
quarantine and its cascades), and checkweigh verdict boundaries / the QA gate.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_customer, create_component, build_approved_recipe,
    create_production_line, create_crew,
    setup_basic_scenario, schedule_run, set_clock,
    setup_running_run, setup_pending_qa_run, add_passing_sample,
    setup_released_run,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import RECEIVER, SCHEDULER, QA


# ---------------------------------------------------------------------------
# Queue B — calculations / run_rate_two_hour_elapsed_correct
# ---------------------------------------------------------------------------

def test_run_rate_two_hour_elapsed(api):
    """PRD 3.5: "the rate is the total divided by elapsed hours, rounded half up to two decimals." "total units is `actual_units_good` plus `actual_units_scrapped`."

    Design: Corner/calculations/run_rate_two_hour_elapsed_correct
    """
    scenario, started = setup_running_run(
        planned_units=100, scheduled_start="2026-06-01T08:00:00Z",
        start_clock="2026-06-01T08:00:00Z", almond_received=1000,
    )
    set_clock("2026-06-01T10:00:00Z")  # 2h elapsed
    run = validate_success(api.complete_run(
        started["id"], {"actual_units_good": 90, "actual_units_scrapped": 10}, SCHEDULER,
    ))
    # total 100 / 2h = 50.00
    assert float(run["run_rate_units_per_hour"]) == 50.00, (
        f"100 units over 2h must give 50.00/h, got {run['run_rate_units_per_hour']}"
    )


# ---------------------------------------------------------------------------
# Queue B — state_machines / error_overrun_on_complete
# ---------------------------------------------------------------------------

def test_complete_overrun_rejected(api):
    """PRD 3.5: "the total produced, good plus scrapped — must not exceed the over-run ceiling, which is `planned_units` multiplied by one plus the over-run allowance of 10 percent ... exceeding the ceiling is rejected with `ERR_OVERRUN_EXCEEDED`."

    Design: Corner/state_machines/error_overrun_on_complete
    """
    scenario, started = setup_running_run(planned_units=100, almond_received=1000)
    set_clock("2026-06-01T10:00:00Z")
    # 111 > 100*1.10=110 => over-run.
    resp = api.complete_run(
        started["id"], {"actual_units_good": 111, "actual_units_scrapped": 0}, SCHEDULER,
    )
    validate_error(resp, ApiErrorId.ERR_OVERRUN_EXCEEDED.value)


def test_complete_at_overrun_ceiling_succeeds(api):
    """PRD 3.5: "so a run planned for some number of units may produce at most that number times 1.10"

    Design: Corner/state_machines/error_overrun_on_complete
    """
    scenario, started = setup_running_run(planned_units=100, almond_received=1000)
    set_clock("2026-06-01T10:00:00Z")
    # exactly 110 == ceiling => allowed.
    run = validate_success(api.complete_run(
        started["id"], {"actual_units_good": 110, "actual_units_scrapped": 0}, SCHEDULER,
    ))
    assert run["status"] == "PENDING_QA", (
        f"output exactly at the ceiling must complete, got {run['status']}"
    )


# ---------------------------------------------------------------------------
# Queue B — state_machines / complete_run_from_scheduled_invalid_state
# ---------------------------------------------------------------------------

def test_complete_from_scheduled_rejected(api):
    """PRD 3.5: "a `Scheduler` completes a `RUNNING` run; a complete from any other state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complete_run_from_scheduled_invalid_state
    """
    scenario = setup_basic_scenario(almond_received=1000)
    run = schedule_run(scenario["recipe"]["id"], scenario["line"]["id"],
                       scenario["crew"]["id"], planned_units=100)
    resp = api.complete_run(
        run["id"], {"actual_units_good": 100, "actual_units_scrapped": 0}, SCHEDULER,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine / production_run_qa_fork_release_vs_quarantine
# ---------------------------------------------------------------------------

def test_qa_fork_release_sets_fg_expiration(api):
    """PRD 3.6: "On a valid release the run's `fg_expiration_date` is computed as the `pack_date` plus the recipe's `shelf_life_days`, the run transitions `PENDING_QA → RELEASED` so its finished goods become sellable"

    Design: Difficulty/non_linear_state_machine/production_run_qa_fork_release_vs_quarantine
    """
    scenario, run = setup_pending_qa_run(
        planned_units=100, almond_received=1000,
        start_clock="2026-06-01T08:00:00Z", complete_clock="2026-06-01T10:00:00Z",
        actual_units_good=100, actual_units_scrapped=0,
    )
    add_passing_sample(run["id"])
    released = validate_success(api.release_run(run["id"], QA))
    assert released["status"] == "RELEASED", (
        f"release branch must reach RELEASED, got {released['status']}"
    )
    # pack_date stamped at start 08:00 + 90 shelf-life days.
    assert released["fg_expiration_date"] == "2026-08-30T08:00:00.000Z", (
        f"fg_expiration_date must be pack_date + 90 days, "
        f"got {released['fg_expiration_date']}"
    )


def test_qa_fork_quarantine_locks_lots(api):
    """PRD 3.6: "Unlike release, quarantine computes no finished-goods expiration and produces no sellable goods — it locks the source lots instead."
    PRD 3.6: "On quarantine, every component lot consumed by the run moves to `QUARANTINED"

    Design: Difficulty/non_linear_state_machine/production_run_qa_fork_release_vs_quarantine
    """
    scenario, run = setup_pending_qa_run(
        planned_units=100, almond_received=1000,
        actual_units_good=100, actual_units_scrapped=0,
    )
    add_passing_sample(run["id"])
    quarantined = validate_success(api.quarantine_run(run["id"], QA))
    assert quarantined["status"] == "QUARANTINED", (
        f"quarantine branch must reach QUARANTINED, got {quarantined['status']}"
    )


# ---------------------------------------------------------------------------
# Queue A — transitive_cascade / quarantine_locks_lots_then_recomputes_on_hand_depth2
# ---------------------------------------------------------------------------

def test_quarantine_locks_lot_and_recomputes_on_hand(api):
    """PRD 3.6: "every component lot consumed by the run moves to `QUARANTINED ... their remaining quantities are held out of the available on-hand computation, each affected component's `on_hand_qty` is recomputed excluding the quarantined lots"

    Design: Difficulty/transitive_cascade/quarantine_locks_lots_then_recomputes_on_hand_depth2
    """
    # ALMOND lot 500; run consumes 210 (lot remaining 290 AVAILABLE) then quarantined.
    scenario, run = setup_pending_qa_run(
        almond_qty=2, almond_scrap=5, almond_received=500,
        actual_units_good=100, actual_units_scrapped=0,
    )
    add_passing_sample(run["id"])
    validate_success(api.quarantine_run(run["id"], QA))

    lot = validate_success(api.get_component_lot(scenario["almond_lot"]["id"], SCHEDULER))
    assert lot["status"] == "QUARANTINED", (
        f"the consumed lot must move to QUARANTINED, got {lot['status']}"
    )
    comp = validate_success(api.get_component(scenario["almond"]["id"], SCHEDULER))
    # available on_hand excludes the now-quarantined lot's 290 remaining => 0.
    assert float(comp["on_hand_qty"]) == 0.000, (
        f"on_hand_qty must exclude the quarantined lot, got {comp['on_hand_qty']}"
    )


def test_quarantine_recompute_excludes_only_quarantined_lot(api):
    """PRD 3.6: "each affected component's `on_hand_qty` is recomputed excluding the quarantined lots"
    PRD 3.1: "it is the sum of the `remaining_qty` of every physical lot of the component whose `status` is `AVAILABLE`, less the component's `reserved_qty"

    Design: Difficulty/transitive_cascade/quarantine_locks_lots_then_recomputes_on_hand_depth2
    """
    # Two ALMOND lots: ALM-EARLY 500 (consumed) and ALM-LATE 400 (untouched, later
    # expiry so FEFO leaves it). After quarantine, ALM-EARLY is QUARANTINED and
    # excluded; ALM-LATE (400) is still AVAILABLE and counted.
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    lot_early = validate_success(api.receive_lot(almond["id"],
        {"supplier_lot_code": "ALM-EARLY", "received_qty": 500,
         "expiration_date": "2026-07-01T00:00:00Z"}, RECEIVER), expected_status=201)
    validate_success(api.receive_lot(almond["id"],
        {"supplier_lot_code": "ALM-LATE", "received_qty": 400,
         "expiration_date": "2026-09-01T00:00:00Z"}, RECEIVER), expected_status=201)
    validate_success(api.receive_lot(pouch["id"],
        {"supplier_lot_code": "POU-1", "received_qty": 1000,
         "expiration_date": "2027-12-31T00:00:00Z"}, RECEIVER), expected_status=201)
    recipe = build_approved_recipe(customer["id"], almond["id"], pouch["id"],
                                   ingredient_qty=2, ingredient_scrap=5)
    line = create_production_line()
    crew = create_crew()
    run = schedule_run(recipe["id"], line["id"], crew["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")
    validate_success(api.start_run(run["id"],
        {"expected_line_version": line["version"]}, SCHEDULER))  # draws 210 from ALM-EARLY
    set_clock("2026-06-01T10:00:00Z")
    validate_success(api.complete_run(run["id"],
        {"actual_units_good": 100, "actual_units_scrapped": 0}, SCHEDULER))
    add_passing_sample(run["id"])
    validate_success(api.quarantine_run(run["id"], QA))

    early_after = validate_success(api.get_component_lot(lot_early["id"], SCHEDULER))
    assert early_after["status"] == "QUARANTINED", (
        f"the consumed lot must be QUARANTINED, got {early_after['status']}"
    )
    comp = validate_success(api.get_component(almond["id"], SCHEDULER))
    # available = only the untouched ALM-LATE lot's 400; quarantined ALM-EARLY excluded.
    assert float(comp["on_hand_qty"]) == 400.000, (
        f"recompute must exclude only the quarantined lot, leaving 400, "
        f"got {comp['on_hand_qty']}"
    )


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc / inventory_available_vs_physical_diverges_on_component
# ---------------------------------------------------------------------------

def test_inventory_available_drops_below_physical_after_quarantine(api):
    """PRD 3.1: "The on-hand figure has a precise meaning: it is the sum of the `remaining_qty` of every physical lot of the component whose `status` is `AVAILABLE`, less the component's `reserved_qty`, rounded half up to three decimals. This is the *available* view." "The figure stored and returned as the component's `on_hand_qty` is always the available view."

    Design: Difficulty/dual_variant_calc/inventory_available_vs_physical_diverges_on_component
    """
    # Two ALMOND lots 150 + 200 = 350; run consumes 210 FEFO (lot A->0 DEPLETED,
    # lot B->140 AVAILABLE); after quarantine both consumed lots are QUARANTINED.
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    validate_success(api.receive_lot(almond["id"], {"supplier_lot_code": "ALM-A",
        "received_qty": 150, "expiration_date": "2026-07-01T00:00:00Z"}, RECEIVER),
        expected_status=201)
    validate_success(api.receive_lot(almond["id"], {"supplier_lot_code": "ALM-B",
        "received_qty": 200, "expiration_date": "2026-08-01T00:00:00Z"}, RECEIVER),
        expected_status=201)
    validate_success(api.receive_lot(pouch["id"], {"supplier_lot_code": "POU-A",
        "received_qty": 1000, "expiration_date": "2027-01-01T00:00:00Z"}, RECEIVER),
        expected_status=201)
    recipe = build_approved_recipe(customer["id"], almond["id"], pouch["id"],
                                   ingredient_qty=2, ingredient_scrap=5)
    line = create_production_line()
    crew = create_crew()
    run = schedule_run(recipe["id"], line["id"], crew["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")
    validate_success(api.start_run(run["id"],
        {"expected_line_version": line["version"]}, SCHEDULER))
    set_clock("2026-06-01T10:00:00Z")
    validate_success(api.complete_run(run["id"],
        {"actual_units_good": 95, "actual_units_scrapped": 5}, SCHEDULER))
    add_passing_sample(run["id"])
    validate_success(api.quarantine_run(run["id"], QA))

    comp = validate_success(api.get_component(almond["id"], SCHEDULER))
    # Both consumed lots (A depleted, B with 140 remaining) are now QUARANTINED;
    # the available view returned as on_hand_qty therefore reads 0.
    assert float(comp["on_hand_qty"]) == 0.000, (
        f"available on_hand_qty must read 0 once both lots are QUARANTINED, "
        f"got {comp['on_hand_qty']}"
    )


def test_quarantined_lot_still_holds_physical_remaining(api):
    """PRD 3.6: "every component lot consumed by the run moves to `QUARANTINED ... their remaining quantities are held out of the available on-hand computation"
    PRD 3.1: "A second, traceability-only view — *physical* on hand — sums the `remaining_qty` of every lot whose status is `AVAILABLE` or `QUARANTINED` and ignores reservations entirely; it diverges from the available view exactly when one of the component's lots has been quarantined."

    Design: Difficulty/dual_variant_calc/inventory_available_vs_physical_diverges_on_component
    """
    # Two ALMOND lots 150 + 200; run draws 210 FEFO leaving lot B with 140; after
    # quarantine lot B is QUARANTINED but still physically reports remaining_qty 140
    # — the divergence between the available view (component.on_hand_qty == 0) and
    # the physical material still on the floor (lot.remaining_qty == 140).
    customer = create_customer()
    almond = create_component(customer["id"], "ALMOND", "Almonds", "INGREDIENT")
    pouch = create_component(customer["id"], "POUCH", "Pouch", "PACKAGING")
    lot_a = validate_success(api.receive_lot(almond["id"], {"supplier_lot_code": "ALM-A",
        "received_qty": 150, "expiration_date": "2026-07-01T00:00:00Z"}, RECEIVER),
        expected_status=201)
    lot_b = validate_success(api.receive_lot(almond["id"], {"supplier_lot_code": "ALM-B",
        "received_qty": 200, "expiration_date": "2026-08-01T00:00:00Z"}, RECEIVER),
        expected_status=201)
    validate_success(api.receive_lot(pouch["id"], {"supplier_lot_code": "POU-A",
        "received_qty": 1000, "expiration_date": "2027-01-01T00:00:00Z"}, RECEIVER),
        expected_status=201)
    recipe = build_approved_recipe(customer["id"], almond["id"], pouch["id"],
                                   ingredient_qty=2, ingredient_scrap=5)
    line = create_production_line()
    crew = create_crew()
    run = schedule_run(recipe["id"], line["id"], crew["id"], planned_units=100)
    set_clock("2026-06-01T08:00:00Z")
    validate_success(api.start_run(run["id"],
        {"expected_line_version": line["version"]}, SCHEDULER))
    set_clock("2026-06-01T10:00:00Z")
    validate_success(api.complete_run(run["id"],
        {"actual_units_good": 95, "actual_units_scrapped": 5}, SCHEDULER))
    add_passing_sample(run["id"])
    validate_success(api.quarantine_run(run["id"], QA))

    lot_b_after = validate_success(api.get_component_lot(lot_b["id"], SCHEDULER))
    assert lot_b_after["status"] == "QUARANTINED", (
        f"the partially-drawn lot must move to QUARANTINED, got {lot_b_after['status']}"
    )
    assert float(lot_b_after["remaining_qty"]) == 140.000, (
        f"the quarantined lot still physically holds 140 remaining, "
        f"got {lot_b_after['remaining_qty']}"
    )
    comp = validate_success(api.get_component(almond["id"], SCHEDULER))
    assert float(comp["on_hand_qty"]) == 0.000, (
        f"yet the available on_hand_qty reads 0 (divergence), got {comp['on_hand_qty']}"
    )


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check / checkweigh_upper_boundary_inclusive_pass_vs_over
# ---------------------------------------------------------------------------

def test_checkweigh_upper_boundary_inclusive_pass(api):
    """PRD 3.6: "a reading anywhere from the lower endpoint through the upper endpoint inclusive — the boundaries themselves pass — is `PASS`."

    Design: Difficulty/boundary_precision_check/checkweigh_upper_boundary_inclusive_pass_vs_over
    """
    scenario, started = setup_running_run(almond_received=1000)  # target 200 tol 5% => upper 210
    sample = validate_success(api.add_checkweigh_sample(
        started["id"], {"measured_weight_g": 210}, QA), expected_status=201)
    assert sample["verdict"] == "PASS", (
        f"210.000 == upper endpoint must PASS, got {sample['verdict']}"
    )


def test_checkweigh_above_upper_boundary_over(api):
    """PRD 3.6: "a reading strictly above the upper endpoint is `OVER"

    Design: Difficulty/boundary_precision_check/checkweigh_upper_boundary_inclusive_pass_vs_over
    """
    scenario, started = setup_running_run(almond_received=1000)
    sample = validate_success(api.add_checkweigh_sample(
        started["id"], {"measured_weight_g": 210.001}, QA), expected_status=201)
    assert sample["verdict"] == "OVER", (
        f"210.001 > upper endpoint must be OVER, got {sample['verdict']}"
    )


# ---------------------------------------------------------------------------
# Queue B — calculations / checkweigh_lower_boundary_inclusive
# ---------------------------------------------------------------------------

def test_checkweigh_lower_boundary_inclusive_pass(api):
    """PRD 3.6: "a reading anywhere from the lower endpoint through the upper endpoint inclusive — the boundaries themselves pass — is `PASS`."

    Design: Corner/calculations/checkweigh_lower_boundary_inclusive
    """
    scenario, started = setup_running_run(almond_received=1000)  # lower 190
    sample = validate_success(api.add_checkweigh_sample(
        started["id"], {"measured_weight_g": 190}, QA), expected_status=201)
    assert sample["verdict"] == "PASS", (
        f"190.000 == lower endpoint must PASS, got {sample['verdict']}"
    )


def test_checkweigh_below_lower_boundary_under(api):
    """PRD 3.6: "A reading strictly below the lower endpoint is `UNDER"

    Design: Corner/calculations/checkweigh_lower_boundary_inclusive
    """
    scenario, started = setup_running_run(almond_received=1000)
    sample = validate_success(api.add_checkweigh_sample(
        started["id"], {"measured_weight_g": 189.999}, QA), expected_status=201)
    assert sample["verdict"] == "UNDER", (
        f"189.999 < lower endpoint must be UNDER, got {sample['verdict']}"
    )


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check / release_blocked_when_zero_checkweigh_samples_empty_set
# ---------------------------------------------------------------------------

def test_release_blocked_with_zero_samples(api):
    """PRD 3.6: "the run must have at least one checkweigh sample, and its reject rate must not exceed the maximum reject rate of 0.05 ... A release attempted with no samples, or with a reject rate above the maximum, is rejected with `ERR_QA_REJECT_RATE_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/release_blocked_when_zero_checkweigh_samples_empty_set
    """
    scenario, run = setup_pending_qa_run(
        almond_received=1000, actual_units_good=100, actual_units_scrapped=0,
    )
    # No checkweigh samples recorded.
    resp = api.release_run(run["id"], QA)
    validate_error(resp, ApiErrorId.ERR_QA_REJECT_RATE_EXCEEDED.value)
    after = validate_success(api.get_run(run["id"], SCHEDULER))
    assert after["status"] == "PENDING_QA", (
        f"a blocked release must leave the run PENDING_QA, got {after['status']}"
    )


def test_release_succeeds_with_one_passing_sample(api):
    """PRD 3.6: "On a valid release the run's `fg_expiration_date` is computed as the `pack_date` plus the recipe's `shelf_life_days`, the run transitions `PENDING_QA → RELEASED` so its finished goods become sellable"

    Design: Difficulty/boundary_precision_check/release_blocked_when_zero_checkweigh_samples_empty_set
    """
    scenario, run = setup_pending_qa_run(
        almond_received=1000, actual_units_good=100, actual_units_scrapped=0,
    )
    add_passing_sample(run["id"])  # one PASS => reject_rate 0.0 <= 0.05
    released = validate_success(api.release_run(run["id"], QA))
    assert released["status"] == "RELEASED", (
        f"one passing sample must allow release, got {released['status']}"
    )


# ---------------------------------------------------------------------------
# Queue B — state_machines / cancel_released_run_terminal_lockdown
# ---------------------------------------------------------------------------

def test_cancel_released_run_terminal_lockdown(api):
    """PRD 3.7: "Cancellation is defined only from `SCHEDULED` or `RUNNING`; attempting it from any other state is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/cancel_released_run_terminal_lockdown
    """
    scenario, released = setup_released_run(
        almond_received=1000, actual_units_good=100, actual_units_scrapped=0,
    )
    resp = api.cancel_run(released["id"], SCHEDULER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
