"""Batch production workflow: the dispersion self-loop, the QC rework cycle,
fill weigh-gate boundaries, mass reconciliation, and dual-variant costing."""

import test_helpers as fx
from test_helpers import ApiErrorId, validate_error, validate_success


def test_dispersion_fail_self_loops_then_pass_advances(api):
    """PRD §3.5: "Each dispersion check records a `grind_reading` in microns:
    a reading above the tint base's `grind_spec_um` keeps the batch in
    `MILLING` and increments its `dispersion_cycles` counter, while a reading
    at or below the specification advances the batch to `TINTING`."

    Design: Difficulty/non_linear_state_machine/batch_dispersion_self_loop_and_rework_cycle
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.start_batch(b1["id"])

    failed = validate_success(
        api.dispersion_check(b1["id"], {"grind_reading": 30},
                             fx.PRODUCTION_OPERATOR)
    )
    assert failed["status"] == "MILLING", "a failed grind reading self-loops"
    assert failed["dispersion_cycles"] == 1

    passed = validate_success(
        api.dispersion_check(b1["id"], {"grind_reading": 18},
                             fx.PRODUCTION_OPERATOR)
    )
    assert passed["status"] == "TINTING"
    assert passed["dispersion_cycles"] == 1


def test_rework_cycle_reenters_milling_and_closes_after_approval(api):
    """PRD §3.6: "When the batch's `rework_count` is still below the cap of 2,
    rejection moves the batch from `QC_PENDING` to `REWORK` and increments
    `rework_count` by one"
    PRD §3.6: "Sending a rejected batch back down the line is the operator's
    rework action: the mill must be `ACTIVE` (`ERR_MILL_NOT_AVAILABLE`), the
    batch moves from `REWORK` back to `MILLING` — where dispersion checks,
    further adjustments, and a fresh QC submission all run again — and a
    `BLOCKED` order behind it returns to `IN_PRODUCTION`."
    PRD §3.6: "`cycle_index`, the batch's `rework_count` at measurement time"

    Design: Difficulty/non_linear_state_machine/batch_dispersion_self_loop_and_rework_cycle
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.start_batch(b1["id"])
    fx.dispersion_pass(b1["id"], 18)
    fx.submit_qc(b1["id"], 3)

    cm1 = fx.enter_measurement(b1["id"], 1.5)
    assert fx.read_color_match(cm1["id"])["cycle_index"] == 0
    fx.reject_match(cm1["id"])
    held = fx.read_batch(b1["id"])
    assert held["status"] == "REWORK"
    assert held["rework_count"] == 1

    reentered = validate_success(api.rework_batch(b1["id"], fx.PRODUCTION_OPERATOR))
    assert reentered["status"] == "MILLING"

    # Full second cycle: dispersion, submission, fresh measurement.
    fx.dispersion_pass(b1["id"], 18)
    fx.submit_qc(b1["id"], 3)
    cm2 = fx.enter_measurement(b1["id"], 0.42)
    assert fx.read_color_match(cm2["id"])["cycle_index"] == 1, (
        "the second-cycle measurement pins the advanced rework count"
    )
    fx.approve_match(cm2["id"])
    assert fx.read_batch(b1["id"])["status"] == "QC_APPROVED"

    # The loop terminates: fill, complete, close.
    for _ in range(3):
        fx.fill_container(b1["id"], "GALLON", 4600)
    fx.complete_filling(b1["id"], 0)
    closed = validate_success(api.close_batch(b1["id"], fx.PRODUCTION_OPERATOR))
    assert closed["status"] == "CLOSED"


def test_batch_cost_provisional_at_creation_vs_final_after_rework(api):
    """PRD §3.4: "The provisional cost is the planned gallonage multiplied by
    the per-gallon recipe cost: the base's `base_cost_per_gal_cents` plus,
    summed over the formula's lines, each line's `shots_per_gallon` times its
    colorant's `cost_per_shot_cents`."
    PRD §3.7: "The final cost is built from actuals: the `actual_gallons`
    multiplied by the base's `base_cost_per_gal_cents`, plus the formula-line
    colorant cost recomputed at actual gallons — each line's
    `shots_per_gallon` times `actual_gallons` times `cost_per_shot_cents`,
    plus every `TINT_SHOT` adjustment's shots at `cost_per_shot_cents`, plus
    the waste charge — `waste_gallons` times the base cost per gallon times
    50 percent recovery, rounded half up to whole cents — plus a rework fee
    of 25000 cents for each cycle in `rework_count`."

    Design: Difficulty/dual_variant_calc/batch_cost_provisional_vs_final
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)

    # Provisional variant: 3 * (1500 + 4*30) = 4860.
    assert b1["theoretical_cost_cents"] == 4860
    fx.assert_batch_invariants(b1)

    # One failed dispersion reading, one TINT_SHOT, one full reject/rework.
    fx.start_batch(b1["id"])
    validate_success(
        api.dispersion_check(b1["id"], {"grind_reading": 30},
                             fx.PRODUCTION_OPERATOR)
    )
    fx.dispersion_pass(b1["id"], 18)
    fx.record_adjustment(b1["id"], kind="TINT_SHOT", quantity=6,
                         colorant_id=_c1["id"])
    fx.submit_qc(b1["id"], 3)
    cm1 = fx.enter_measurement(b1["id"], 1.2)
    fx.reject_match(cm1["id"])
    validate_success(api.rework_batch(b1["id"], fx.PRODUCTION_OPERATOR))
    fx.dispersion_pass(b1["id"], 18)
    fx.submit_qc(b1["id"], 3)
    cm2 = fx.enter_measurement(b1["id"], 0.42)
    fx.approve_match(cm2["id"])

    for _ in range(3):
        fx.fill_container(b1["id"], "GALLON", 4600)
    filled = fx.complete_filling(b1["id"], 0)

    # Final variant: 3*1500 + 12*30 + 6*30 + 0 + 1*25000 = 30040.
    assert filled["status"] == "FILLED"
    assert filled["actual_cost_cents"] == 30040
    assert filled["rework_count"] == 1
    assert filled["dispersion_cycles"] == 1
    assert filled["theoretical_cost_cents"] == 4860, (
        "the provisional figure is retained alongside the final one"
    )
    assert filled["theoretical_cost_cents"] != filled["actual_cost_cents"], (
        "same batch data, divergent variants"
    )


def test_final_cost_uses_actuals_where_provisional_used_plan(api):
    """PRD §3.7: "Where the provisional variant used planned gallons and
    nominal shots, the final variant uses what actually happened, so the same
    batch data yields a different, truer number."
    PRD §3.4: "Because it uses planned gallons and nominal formula shots only
    — no adjustments, no waste, no rework fee — it is an estimate; the final
    variant computed at the end of filling (§3.7) uses actuals and will
    generally differ."

    Design: Difficulty/dual_variant_calc/batch_cost_provisional_vs_final
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    assert b1["theoretical_cost_cents"] == 3 * (1500 + 4 * 30)
    assert b1.get("actual_cost_cents") is None, (
        "no final variant exists before filling completes"
    )

    # Clean run: no adjustments, no waste, no rework — final == provisional
    # only because nothing deviated from plan.
    fx.drive_batch_to_qc_approved(b1["id"], actual_gallons=3,
                                  measured_delta_e=0.42)
    for _ in range(3):
        fx.fill_container(b1["id"], "GALLON", 4600)
    filled = fx.complete_filling(b1["id"], 0)
    assert filled["status"] == "FILLED"
    assert filled["actual_cost_cents"] == 3 * 1500 + 12 * 30 + 0 + 0 * 25000
    assert filled["rework_count"] == 0


def test_batch_creation_requires_active_formula(api):
    """PRD §3.4: "A `ProductionOperator` plans a batch by naming the
    `formula_id` to produce, the `mill_id` to reserve, the `planned_gallons`,
    the reservation window `mill_window_start` and `mill_window_end`, and
    optionally the `order_id` the batch serves — a batch without an order is
    a stock batch."
    PRD §3.4: "The formula must be `ACTIVE` (`ERR_FORMULA_NOT_ACTIVE`), the
    planned size must not exceed the mill's capacity
    (`ERR_MILL_CAPACITY_EXCEEDED`), it must meet the formula's
    `min_batch_gallons` — 50 gallons for a custom formula, 1 otherwise
    (`ERR_CUSTOM_MINIMUM_NOT_MET`) — and the window must satisfy the conflict
    rules of §2.10 (`ERR_MILL_WINDOW_CONFLICT`)."
    PRD §3.4: "Creation stamps a server-minted human batch code in
    `batch_code` (the series runs B-000001, B-000002, monotonically
    increasing), pins `pinned_formula_version_no` to the formula's current
    `formula_version_no`, snapshots the tint base's `product_category` and
    `base_family` onto the batch so later master-data edits cannot rewrite
    history, computes the provisional cost into `theoretical_cost_cents`,
    adds the window's minutes to the mill's `reserved_minutes`, and parks the
    batch in `PLANNED`."

    Design: Difficulty/cross_entity_state_dependency/batch_requires_formula_active
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    tb1, c1, f1 = fx.setup_lab_catalog()  # F1 stays DRAFT
    m1 = fx.create_mill()

    refused = api.create_batch(
        fx.create_batch_payload(f1["id"], m1["id"], planned_gallons=3),
        fx.PRODUCTION_OPERATOR,
    )
    validate_error(refused, ApiErrorId.ERR_FORMULA_NOT_ACTIVE.value, 422)
    assert fx.read_formula(f1["id"])["status"] == "DRAFT"

    # Activating the same formula flips the dependency: the identical
    # payload now succeeds and pins the formula's current version number.
    fx.activate_formula(f1["id"])
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.assert_batch(b1)
    assert b1["status"] == "PLANNED"
    assert b1["pinned_formula_version_no"] == 1


def test_batch_resume_requires_active_new_formula(api):
    """PRD §3.4: "Resuming it, a `ProductionOperator` supplies a
    `new_formula_id` that must reference an `ACTIVE` formula
    (`ERR_FORMULA_NOT_ACTIVE`); the batch's `formula_id` is repointed,
    `pinned_formula_version_no` is re-snapshotted from the new formula, the
    batch returns to `PLANNED`, and its order, if `BLOCKED`, returns to
    `SCHEDULED`."
    PRD §3.5: "the batch's formula is `ACTIVE` — a formula deprecated since
    planning blocks the start with `ERR_FORMULA_NOT_ACTIVE`"

    Design: Difficulty/cross_entity_state_dependency/batch_requires_formula_active
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    tb1, c1, f1, m1 = fx.setup_plant()  # F1 ACTIVE
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)

    # Deprecate F1: the planned batch goes ON_HOLD, and start-mill is
    # blocked — §3.5 names ERR_FORMULA_NOT_ACTIVE for a formula deprecated
    # since planning, while the cascaded ON_HOLD state also fails gate 6
    # (state permission, §2.9); the PRD does not pin which pre-empts.
    validate_success(api.deprecate_formula(f1["id"], fx.LAB_TECHNICIAN))
    assert fx.read_batch(b1["id"])["status"] == "ON_HOLD"
    blocked_start = api.start_mill(b1["id"], fx.PRODUCTION_OPERATOR)
    fx.validate_error_is_one_of(
        blocked_start,
        [ApiErrorId.ERR_FORMULA_NOT_ACTIVE.value,
         ApiErrorId.ERR_INVALID_STATE.value],
    )

    # A DRAFT formula cannot receive the batch either.
    f_new = fx.create_f1(tb1["id"], c1["id"], formula_code="CLR-9000")
    refused = api.resume_batch(b1["id"], {"new_formula_id": f_new["id"]},
                               fx.PRODUCTION_OPERATOR)
    validate_error(refused, ApiErrorId.ERR_FORMULA_NOT_ACTIVE.value, 422)
    assert fx.read_batch(b1["id"])["status"] == "ON_HOLD"

    # Once the new formula is ACTIVE the resume succeeds and re-pins.
    fx.activate_formula(f_new["id"])
    resumed = validate_success(
        api.resume_batch(b1["id"], {"new_formula_id": f_new["id"]},
                         fx.PRODUCTION_OPERATOR)
    )
    assert resumed["status"] == "PLANNED"
    assert resumed["formula_id"] == f_new["id"]
    assert resumed["pinned_formula_version_no"] == f_new["formula_version_no"]


def test_fill_tolerance_exact_boundary(api):
    """PRD §3.7: "The tolerance is the larger of the nominal fill multiplied
    by 1.5 percent, rounded half up to whole grams, and a floor of 10 grams;
    the container passes when the absolute difference between `actual_fill_g`
    and `nominal_fill_g` is less than or equal to that tolerance, with
    equality passing. A passing container is born `IN_STOCK`; a failing one
    is born `QUARANTINED`."

    Design: Difficulty/boundary_precision_check/fill_tolerance_exact_boundary
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.drive_batch_to_qc_approved(b1["id"], actual_gallons=3)

    # GALLON tolerance is max(round_half_up(4600 * 0.015), 10) = 69 grams.
    edge = fx.fill_container(b1["id"], "GALLON", 4531)
    assert edge["status"] == "IN_STOCK", "|4531-4600| == 69 <= 69: equality passes"
    assert edge["fill_variance_g"] == -69

    under = fx.fill_container(b1["id"], "GALLON", 4530)
    assert under["status"] == "QUARANTINED", "|4530-4600| == 70 > 69"
    assert under["fill_variance_g"] == -70


def test_fill_tolerance_upper_edge_and_floor(api):
    """PRD §3.7: "the container passes when the absolute difference between
    `actual_fill_g` and `nominal_fill_g` is less than or equal to that
    tolerance, with equality passing. A passing container is born `IN_STOCK`;
    a failing one is born `QUARANTINED`."
    PRD §3.7: "its `fill_variance_g` is recorded as the actual minus the
    nominal fill"

    Design: Difficulty/boundary_precision_check/fill_tolerance_exact_boundary
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.drive_batch_to_qc_approved(b1["id"], actual_gallons=3)

    # Upper edge: 4669 is exactly +69 over nominal.
    over_edge = fx.fill_container(b1["id"], "GALLON", 4669)
    assert over_edge["status"] == "IN_STOCK"
    assert over_edge["fill_variance_g"] == 69

    over = fx.fill_container(b1["id"], "GALLON", 4670)
    assert over["status"] == "QUARANTINED"
    assert over["fill_variance_g"] == 70

    # QUART tolerance is max(round_half_up(1150 * 0.015), 10) = 17 grams.
    quart_edge = fx.fill_container(b1["id"], "QUART", 1133)
    assert quart_edge["status"] == "IN_STOCK", "1133 is exactly -17 from 1150"
    quart_under = fx.fill_container(b1["id"], "QUART", 1132)
    assert quart_under["status"] == "QUARANTINED"


def test_fill_reconciliation_rounding_order(api):
    """PRD §3.7: "The rounding order is load-bearing: three pails at 4605
    grams each sum to 4.61 + 4.61 + 4.61 = 13.83 kilograms, not the 13.82
    that summing 13815 raw grams and then rounding would give."
    PRD §3.7: "The batch passes when the absolute difference between filled
    mass and drawdown, divided by the drawdown and expressed as a percentage,
    is less than or equal to 0.5"

    Design: Difficulty/combinatorial_formula/fill_reconciliation_rounding_order
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.drive_batch_to_qc_approved(b1["id"], actual_gallons=3)

    containers = [fx.fill_container(b1["id"], "GALLON", 4605) for _ in range(3)]
    for can in containers:
        fx.assert_container(can)
        assert can["net_weight_kg"] == 4.61, "each can rounds first"
        assert can["fill_variance_g"] == 5

    filled = fx.complete_filling(b1["id"], 0)
    assert filled["status"] == "FILLED", (
        "|13.83 - 13.8| / 13.8 = 0.217% <= 0.5% must pass"
    )
    assert filled["filled_net_kg"] == 13.83, (
        "per-container-then-sum rounding: 3 x 4.61 = 13.83, not 13.82"
    )


def test_fill_reconciliation_sums_rounded_containers(api):
    """PRD §3.7: "Declaring filling complete is the plant's mass-balance
    moment. The operator declares `waste_gallons` of process waste, and the
    reconciliation runs with a pinned rounding order — each container's net
    weight is rounded to two decimals first, and only then summed. The filled
    mass `filled_net_kg` is the sum of `net_weight_kg` over every container
    of the batch that is not `REJECTED` — `QUARANTINED` containers still
    count, because their mass left the tank."

    Design: Difficulty/combinatorial_formula/fill_reconciliation_rounding_order
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=1)
    fx.drive_batch_to_qc_approved(b1["id"], actual_gallons=1)

    # One 4605 g can: rounds to 4.61 kg; drawdown is 1 gal * 4.6 = 4.6 kg.
    can = fx.fill_container(b1["id"], "GALLON", 4605)
    assert can["net_weight_kg"] == 4.61
    filled = fx.complete_filling(b1["id"], 0)
    # |4.61 - 4.6| / 4.6 = 0.217% <= 0.5% passes.
    assert filled["status"] == "FILLED"
    assert filled["filled_net_kg"] == 4.61, (
        "the persisted filled mass carries the per-container rounding"
    )


def test_fill_reconciliation_failure_blocks_completion(api):
    """PRD §3.7: "The batch passes when the absolute difference between
    filled mass and drawdown, divided by the drawdown and expressed as a
    percentage, is less than or equal to 0.5; anything more is
    `ERR_FILL_RECONCILIATION_FAILED`."

    Design: Corner/calculations/fill_reconciliation_failure_blocks_completion
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)
    fx.drive_batch_to_qc_approved(b1["id"], actual_gallons=3)
    for _ in range(3):
        fx.fill_container(b1["id"], "GALLON", 4600)

    # Over-declared waste: filled 13.8 kg vs drawdown (3 - 0.5) * 4.6 = 11.5 kg
    # is a 20% miss, far past the 0.5% gate.
    failed = api.complete_filling(b1["id"], {"waste_gallons": 0.5},
                                  fx.PRODUCTION_OPERATOR)
    validate_error(failed, ApiErrorId.ERR_FILL_RECONCILIATION_FAILED.value, 422)
    assert fx.read_batch(b1["id"])["status"] == "FILLING"

    # The honest declaration reconciles exactly and computes the final cost.
    completed = fx.complete_filling(b1["id"], 0)
    assert completed["status"] == "FILLED"
    assert completed["actual_cost_cents"] == 4860
