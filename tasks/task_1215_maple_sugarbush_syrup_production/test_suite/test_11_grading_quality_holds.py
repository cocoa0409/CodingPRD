"""Grading, flavor evaluations, quality holds, lot lookup (PRD §3.6, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    collect_confirmed_run,
    create_filling_batch,
    create_grade_payload,
    draw_from_run,
    finish_batch,
    get_only_syrup_lot,
    grade_lot,
    make_sugarmaker_headers,
    record_evaluation,
    set_clock,
    setup_batch_x_boiling,
    setup_live_operation,
    setup_two_lots_for_grade_boundary,
    setup_ungraded_lot,
    start_boil,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_grade_without_evaluation_rejected(api, manager_headers):
    """PRD §3.8: "Grading a lot — from either `UNGRADED` or `HELD` — takes the
    optical reading `light_transmittance_pct` (0 to 100) and requires at least
    one evaluation to exist (otherwise `ERR_LOT_NOT_GRADABLE`)."

    Design: Corner/errors/grade_without_evaluation_rejected
    """
    ctx = setup_ungraded_lot(measured_syrup_gallons=3.60, with_grader=True)
    res = api.grade_syrup_lot(
        ctx["lot"]["id"], create_grade_payload(76.0),
        make_sugarmaker_headers(ctx["boiler"]["id"]))
    validate_error(res, ApiErrorId.ERR_LOT_NOT_GRADABLE)


def test_grade_transmittance_boundaries(api, manager_headers):
    """PRD §3.8: "Otherwise the transmittance thresholds classify: at least
    75.0 yields `GOLDEN` (exactly 75.0 is golden; 74.9 is not); at least 50.0
    yields `AMBER`; at least 25.0 yields `DARK`; anything below that is
    `VERY_DARK`."

    Design: Corner/calculations/grade_transmittance_boundaries
    """
    ctx = setup_two_lots_for_grade_boundary()
    lot_a = grade_lot(ctx, ctx["lot_a"]["id"], 75.0)
    assert lot_a["grade"] == "GOLDEN"
    assert lot_a["status"] == "GRADED"

    lot_b = grade_lot(ctx, ctx["lot_b"]["id"], 74.9)
    assert lot_b["grade"] == "AMBER"
    assert lot_b["status"] == "GRADED"


def test_lot_auto_held_on_high_variance(api, manager_headers):
    """PRD §3.6: "When the absolute value of `yield_variance_pct` is at least
    15.0 — exactly 15.0 triggers the hold — the new lot enters `HELD` with
    `quality_hold_auto` set to true; otherwise it enters `UNGRADED` with
    `quality_hold_auto` false."
    (expected 3.72, measured 3.10 -> variance -16.67%.)

    Design: Corner/state_machines/lot_auto_held_on_high_variance
    """
    ctx = setup_batch_x_boiling()
    finished = finish_batch(ctx, ctx["batch"]["id"], 66.2, 3.10)
    assert finished["yield_variance_pct"] == pytest.approx(-16.67, abs=0.004)

    lot = get_only_syrup_lot()
    assert lot["status"] == "HELD"
    assert lot["quality_hold_auto"] is True


def test_syrup_lot_lookup_by_batch_id(api, manager_headers):
    """PRD §3.6: "Finishing creates the batch's **SyrupLot** — one lot per
    batch, carrying the batch's `batch_id` and denormalized `season_id`, with
    `measured_gallons` equal to the batch's `measured_syrup_gallons`,
    `finished_brix` equal to the batch's `finished_brix`, and
    `unpackaged_gallons` initialized to `measured_gallons`."
    PRD §4: "| GET | /sugarhouse/syrup-lots | List syrup lots (filters:
    `batch_id`, `season_id`, `status`) | SugarhouseManager, FieldCrew,
    SugarMaker, CertInspector |"

    Design: Corner/endpoints/syrup_lot_lookup_by_batch_id
    """
    ctx = setup_live_operation()
    run = collect_confirmed_run(ctx, 20.0, 2.0)
    batch_a = create_filling_batch(ctx, capacity=50)
    draw_from_run(ctx, batch_a["id"], run["id"], 10.0)
    start_boil(ctx, batch_a["id"])
    finish_batch(ctx, batch_a["id"], 66.5, 0.22)
    batch_b = create_filling_batch(ctx, capacity=50)  # FILLING, no lot

    lots_a, _ = validate_paginated(
        api.list_syrup_lots(manager_headers, params={"batch_id": batch_a["id"]}))
    assert len(lots_a) == 1
    assert lots_a[0]["measured_gallons"] == pytest.approx(0.22, abs=0.004)

    lots_b, _ = validate_paginated(
        api.list_syrup_lots(manager_headers, params={"batch_id": batch_b["id"]}))
    assert lots_b == []


def test_lot_hold_regrade_cycle_flips_grade(api, manager_headers):
    """PRD §3.8: "A manager may place a lot on quality hold — `UNGRADED → HELD`
    or `GRADED → HELD`" and "A lot graded from `HELD` has its `grade`
    recomputed from the latest evaluation in the same way." and "If the latest
    evaluation has a non-empty `defect_flags` list, or its `flavor_score` is
    below 70, the `grade` is `PROCESSING` regardless of transmittance."

    Design: Difficulty/non_linear_state_machine/syrup_lot_hold_regrade_cycle
    """
    ctx = setup_ungraded_lot(measured_syrup_gallons=3.60, with_grader=True)
    lot = ctx["lot"]
    assert lot["status"] == "UNGRADED"
    assert lot["quality_hold_auto"] is False

    record_evaluation(ctx, lot["id"], 80)
    graded = grade_lot(ctx, lot["id"], 76.0)
    assert graded["status"] == "GRADED"
    assert graded["grade"] == "GOLDEN"  # 76.0 >= 75.0

    held = validate_success(api.hold_syrup_lot(lot["id"], manager_headers), 200)
    assert held["status"] == "HELD"

    # A later evaluation with flavor below 70 becomes the latest one.
    set_clock("2027-03-05T08:00:00Z")
    record_evaluation(ctx, lot["id"], 60)
    regraded = grade_lot(ctx, lot["id"], 76.0)
    assert regraded["status"] == "GRADED"
    assert regraded["grade"] == "PROCESSING", (
        "identical transmittance 76.0 but latest flavor_score 60 < 70")


def test_lot_hold_regrade_cycle_state_path(api, manager_headers):
    """PRD §3.8: "Grading a lot — from either `UNGRADED` or `HELD` — takes the
    optical reading `light_transmittance_pct` (0 to 100) and requires at least
    one evaluation to exist (otherwise `ERR_LOT_NOT_GRADABLE`). The grade is
    computed from that transmittance and the latest evaluation (ordered by
    `evaluated_at`, ties broken by `created_at`)."

    Design: Difficulty/non_linear_state_machine/syrup_lot_hold_regrade_cycle
    """
    ctx = setup_ungraded_lot(measured_syrup_gallons=3.60, with_grader=True)
    lot = ctx["lot"]

    record_evaluation(ctx, lot["id"], 80)
    grade_lot(ctx, lot["id"], 76.0)
    after_grade = validate_success(api.get_syrup_lot(lot["id"], manager_headers), 200)
    assert after_grade["status"] == "GRADED"
    assert after_grade["grade"] == "GOLDEN"

    validate_success(api.hold_syrup_lot(lot["id"], manager_headers), 200)
    after_hold = validate_success(api.get_syrup_lot(lot["id"], manager_headers), 200)
    assert after_hold["status"] == "HELD"

    # The cycle is semantically live: a newer, worse evaluation drives the
    # re-grade from HELD to PROCESSING at the same transmittance.
    set_clock("2027-03-05T08:00:00Z")
    record_evaluation(ctx, lot["id"], 60)
    grade_lot(ctx, lot["id"], 76.0)
    final = validate_success(api.get_syrup_lot(lot["id"], manager_headers), 200)
    assert final["status"] == "GRADED"
    assert final["grade"] == "PROCESSING"
