"""Boil lifecycle: start-boil gates, deterioration-adjusted brix, dual yield
conventions, legal-brix boundary, finish side effects (PRD §2.5, §3.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    collect_confirmed_run,
    create_filling_batch,
    create_finish_payload,
    draw_from_run,
    finish_batch,
    get_only_syrup_lot,
    make_sugarmaker_headers,
    setup_batch_x_boiling,
    setup_live_operation,
    start_boil,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_finish_from_filling_rejected(api, manager_headers):
    """PRD §3.6: "Finishing the boil moves `BOILING → FINISHED`." — a batch
    still in `FILLING` is not in a valid from-state for finish.
    PRD §2.7: "5. **State precondition** — the target resource is not in a
    valid from-state, covering `ERR_INVALID_STATE` and the specific state-gate
    errors `ERR_SEASON_NOT_OPEN`, `ERR_SEASON_SUSPENDED`,
    `ERR_SUGARBUSH_NOT_LIVE`, `ERR_WINDOW_NOT_OPEN`, `ERR_CREW_NOT_ACTIVE`,
    `ERR_TAP_LINES_NOT_READY`, `ERR_VACUUM_STILL_LOW`, `ERR_BATCH_EMPTY`,
    `ERR_EVAPORATOR_BUSY`, `ERR_LOT_NOT_GRADED`, and `ERR_LOT_NOT_GRADABLE`."
    PRD §3.6: "Finishing creates the batch's **SyrupLot** — one lot per batch,
    carrying the batch's `batch_id` and denormalized `season_id`, with
    `measured_gallons` equal to the batch's `measured_syrup_gallons`,
    `finished_brix` equal to the batch's `finished_brix`, and
    `unpackaged_gallons` initialized to `measured_gallons`."

    Design: Corner/state_machines/finish_from_filling_rejected
    """
    ctx = setup_live_operation()
    run = collect_confirmed_run(ctx, 10.0, 2.0)
    batch = create_filling_batch(ctx, capacity=200)
    draw_from_run(ctx, batch["id"], run["id"], 10.0)

    res = api.finish_batch(batch["id"], create_finish_payload(66.5, 0.2),
                           make_sugarmaker_headers(ctx["boiler"]["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    after = validate_success(api.get_batch(batch["id"], manager_headers), 200)
    assert after["status"] == "FILLING"
    lots, _ = validate_paginated(
        api.list_syrup_lots(manager_headers, params={"batch_id": batch["id"]}))
    assert lots == [], "no syrup lot is created for a batch that never finished"


def test_batch_empty_start_boil_rejected(api, manager_headers):
    """PRD §3.6: "It requires `sap_gallons_in` to be greater than zero
    (otherwise `ERR_BATCH_EMPTY`)"

    Design: Corner/errors/batch_empty_start_boil_rejected
    """
    ctx = setup_live_operation()
    batch = create_filling_batch(ctx, capacity=200)

    res = api.start_boil(batch["id"], make_sugarmaker_headers(ctx["boiler"]["id"]))
    validate_error(res, ApiErrorId.ERR_BATCH_EMPTY)


def test_evaporator_busy_second_boil(api, manager_headers):
    """PRD §3.6: "It requires `sap_gallons_in` to be greater than zero
    (otherwise `ERR_BATCH_EMPTY`) and requires that no other batch of the same
    season is already in `BOILING` — the sugarhouse has a single evaporator, so
    a busy one rejects with `ERR_EVAPORATOR_BUSY`."

    Design: Corner/errors/evaporator_busy_second_boil
    """
    ctx = setup_live_operation()
    run = collect_confirmed_run(ctx, 20.0, 2.0)
    batch_a = create_filling_batch(ctx, capacity=50)
    draw_from_run(ctx, batch_a["id"], run["id"], 10.0)
    batch_b = create_filling_batch(ctx, capacity=50)
    draw_from_run(ctx, batch_b["id"], run["id"], 10.0)

    start_boil(ctx, batch_a["id"])
    res = api.start_boil(batch_b["id"], make_sugarmaker_headers(ctx["boiler"]["id"]))
    validate_error(res, ApiErrorId.ERR_EVAPORATOR_BUSY)

    finish_batch(ctx, batch_a["id"], 66.5, 0.22)
    boiling = validate_success(
        api.start_boil(batch_b["id"], make_sugarmaker_headers(ctx["boiler"]["id"])),
        200)
    assert boiling["status"] == "BOILING"


def test_immediate_visibility_after_finish(api, manager_headers):
    """PRD §2.8: "The platform maintains a set of derived counters and totals
    that must be consistent at the end of every request — consistency is
    immediate, never eventual."
    PRD §3.6: "The platform computes `yield_variance_pct` as the difference
    between `measured_syrup_gallons` and `expected_syrup_gallons`, divided by
    `expected_syrup_gallons`, multiplied by 100, rounded to 2 decimal places
    round half up."
    PRD §3.6: "Finishing creates the batch's **SyrupLot** — one lot per batch,
    carrying the batch's `batch_id` and denormalized `season_id`, with
    `measured_gallons` equal to the batch's `measured_syrup_gallons`,
    `finished_brix` equal to the batch's `finished_brix`, and
    `unpackaged_gallons` initialized to `measured_gallons`."

    Design: Corner/cross_cutting_complexity_layers/immediate_visibility_after_finish
    """
    ctx = setup_live_operation()
    run = collect_confirmed_run(ctx, 10.0, 2.0)
    batch = create_filling_batch(ctx, capacity=50)
    draw_from_run(ctx, batch["id"], run["id"], 10.0)
    start_boil(ctx, batch["id"])

    finished = finish_batch(ctx, batch["id"], 66.5, 0.22)
    assert finished["status"] == "FINISHED"
    # expected = round(10 * 2.0 / 88.2, 2) = 0.23; variance = (0.22-0.23)/0.23*100 = -4.35
    assert finished["yield_variance_pct"] == pytest.approx(-4.35, abs=0.004)

    lots, _ = validate_paginated(
        api.list_syrup_lots(manager_headers, params={"batch_id": batch["id"]}))
    assert len(lots) == 1
    assert lots[0]["measured_gallons"] == pytest.approx(0.22, abs=0.004)


def test_rule86_and_rule882_figures_at_start_boil(api, manager_headers):
    """PRD §3.6: "The `estimated_syrup_gallons` — the Rule-of-86 figure used
    for planning — is `sap_gallons_in` multiplied by `input_brix` and divided
    by 86, rounded to 2 decimal places round half up. The
    `expected_syrup_gallons` — the Rule-of-88.2 figure used for variance and
    settlement — is the same product divided by 88.2, rounded the same way."
    (160.00 gal @ input_brix 2.05: 328/86 -> 3.81; 328/88.2 -> 3.72.)

    Design: Difficulty/dual_variant_calc/boil_off_rule86_vs_rule882
    """
    ctx = setup_batch_x_boiling()
    batch = ctx["batch"]
    assert batch["status"] == "BOILING"
    assert batch["sap_gallons_in"] == pytest.approx(160.0, abs=0.004)
    assert batch["input_brix"] == pytest.approx(2.05, abs=0.004)
    assert batch["estimated_syrup_gallons"] == pytest.approx(3.81, abs=0.004)
    assert batch["expected_syrup_gallons"] == pytest.approx(3.72, abs=0.004)


def test_rule86_estimate_exceeds_rule882_expectation(api, manager_headers):
    """PRD §2.5: "The **Rule of 86** is the optimistic field estimate: it
    assumes no sugar is lost in the boil, so for a given sap input it produces
    a *higher* gallon estimate. The **Rule of 88.2** is the settlement
    convention: it accounts for roughly the sugar lost during boiling, so for
    the same input it produces a *lower* gallon figure."
    PRD §3.6: "For identical input, the estimate always exceeds the
    expectation."

    Design: Difficulty/dual_variant_calc/boil_off_rule86_vs_rule882
    """
    ctx = setup_batch_x_boiling()
    batch = ctx["batch"]
    assert batch["estimated_syrup_gallons"] is not None
    assert batch["expected_syrup_gallons"] is not None
    assert batch["estimated_syrup_gallons"] > batch["expected_syrup_gallons"]


def test_intake_effective_brix_stamped_with_deterioration(api, manager_headers):
    """PRD §3.6: "For each intake, the platform computes the whole hours
    between the contributing run's `collected_at` and the batch's
    `boil_started_at`, converts that to a number of full 24-hour days by
    discarding any partial day, and multiplies those full days by a
    deterioration rate of 0.2 brix per day, capped at a maximum total
    deterioration of 1.0 brix. The intake's `effective_brix` is then the run's
    `measured_brix` minus that deterioration, floored at 0.5 brix, and is
    stamped onto the intake record."
    (run1: 60h -> 2 days -> 2.0 - 0.4 = 1.6; run2: 36h -> 1 day -> 3.0 - 0.2 =
    2.8.)

    Design: Difficulty/combinatorial_formula/weighted_brix_with_deterioration
    """
    ctx = setup_batch_x_boiling()
    intakes, _ = validate_paginated(
        api.list_batch_intakes(ctx["batch"]["id"], manager_headers))
    by_run = {i["sap_run_id"]: i for i in intakes}
    assert by_run[ctx["run1"]["id"]]["effective_brix"] == pytest.approx(1.6, abs=0.004)
    assert by_run[ctx["run2"]["id"]]["effective_brix"] == pytest.approx(2.8, abs=0.004)


def test_input_brix_is_volume_weighted_average(api, manager_headers):
    """PRD §3.6: "The batch's `input_brix` is the volume-weighted average of
    these stamped values: the sum over intakes of `gallons_drawn` multiplied by
    `effective_brix`, divided by the sum of `gallons_drawn`, rounded to 2
    decimal places round half up. Downstream calculations consume this stored,
    rounded `input_brix`."
    ((100*1.6 + 60*2.8) / 160 = 328/160 = 2.05.)

    Design: Difficulty/combinatorial_formula/weighted_brix_with_deterioration
    """
    ctx = setup_batch_x_boiling()
    batch = validate_success(api.get_batch(ctx["batch"]["id"], manager_headers), 200)
    assert batch["input_brix"] == pytest.approx(2.05, abs=0.004)
    assert batch["sap_gallons_in"] == pytest.approx(160.0, abs=0.004)


def _single_run_boiling_batch(collected_at="2027-03-02T00:00:00Z",
                              boil_at="2027-03-02T12:00:00Z"):
    """10 gal @ 2.0 collected at 00:00, boiled at 12:00 the same day (12h -> 0
    full days -> no deterioration; input_brix 2.00, expected 0.23)."""
    ctx = setup_live_operation(open_window_at="2027-03-01T12:00:00Z")
    run = collect_confirmed_run(ctx, 10.0, 2.0, clock=collected_at)
    batch = create_filling_batch(ctx, capacity=50)
    draw_from_run(ctx, batch["id"], run["id"], 10.0)
    start_boil(ctx, batch["id"], clock=boil_at)
    ctx["run"], ctx["batch"] = run, batch
    return ctx


def test_finished_brix_66_exactly_is_legal(api, manager_headers):
    """PRD §3.6: "The finisher supplies `finished_brix` — the syrup density at
    draw-off, which must be at least 66.0 (a lower reading violates the legal
    minimum density for maple syrup and is rejected with
    `ERR_BRIX_BELOW_LEGAL`)" — exactly 66.0 satisfies "at least 66.0".

    Design: Difficulty/boundary_precision_check/finished_brix_66_exact_boundary
    """
    ctx = _single_run_boiling_batch()
    finished = finish_batch(ctx, ctx["batch"]["id"], 66.0, 0.20)
    assert finished["status"] == "FINISHED"
    assert finished["input_brix"] == pytest.approx(2.00, abs=0.004)
    assert finished["expected_syrup_gallons"] == pytest.approx(0.23, abs=0.004)
    # variance = round((0.20 - 0.23) / 0.23 * 100, 2) = -13.04 -> below the
    # 15.0 hold threshold, so the lot enters UNGRADED.
    lot = get_only_syrup_lot()
    assert lot["status"] == "UNGRADED"
    assert lot["quality_hold_auto"] is False


def test_finished_brix_65_9_rejected_below_legal(api, manager_headers):
    """PRD §3.6: "The finisher supplies `finished_brix` — the syrup density at
    draw-off, which must be at least 66.0 (a lower reading violates the legal
    minimum density for maple syrup and is rejected with
    `ERR_BRIX_BELOW_LEGAL`)"

    Design: Difficulty/boundary_precision_check/finished_brix_66_exact_boundary
    """
    ctx = _single_run_boiling_batch()
    res = api.finish_batch(ctx["batch"]["id"], create_finish_payload(65.9, 0.20),
                           make_sugarmaker_headers(ctx["boiler"]["id"]))
    validate_error(res, ApiErrorId.ERR_BRIX_BELOW_LEGAL)

    after = validate_success(api.get_batch(ctx["batch"]["id"], manager_headers), 200)
    assert after["status"] == "BOILING"
