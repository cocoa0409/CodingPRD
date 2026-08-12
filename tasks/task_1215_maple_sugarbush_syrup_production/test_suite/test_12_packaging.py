"""Packaging: graded-lot gate, retail eligibility vs volume priority, exact-fit
exhaustion, syrup conservation (PRD §2.7, §2.8, §2.9, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_syrup_conservation,
    create_packaging_run_payload,
    grade_lot,
    record_evaluation,
    setup_single_run_graded_lot,
    setup_ungraded_lot,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_packaging_create_requires_graded_lot(api, manager_headers):
    """PRD §3.9: "The referenced lot must be in `GRADED` (otherwise
    `ERR_LOT_NOT_GRADED`)."

    Design: Difficulty/cross_entity_state_dependency/packaging_requires_lot_graded
    """
    ctx = setup_ungraded_lot(measured_syrup_gallons=3.60)  # lot UNGRADED, no evals
    assert ctx["lot"]["status"] == "UNGRADED"

    res = api.create_packaging_run(
        create_packaging_run_payload(ctx["lot"]["id"], container_type="DRUM_55",
                                     units_planned=1),
        manager_headers)
    validate_error(res, ApiErrorId.ERR_LOT_NOT_GRADED)

    runs, _ = validate_paginated(api.list_packaging_runs(manager_headers))
    assert runs == [], "no PackagingRun is created against an UNGRADED lot"


def test_packaging_create_succeeds_after_grading(api, manager_headers):
    """PRD §3.9: "The referenced lot must be in `GRADED` (otherwise
    `ERR_LOT_NOT_GRADED`)." Once the lot is graded, the same creation succeeds
    and "A **PackagingRun** plans containers against a graded lot." begins in
    `PLANNED` (PRD §3.9: "No reservation is held at plan time: a `PLANNED` run
    holds nothing, which is why cancelling one (moving `PLANNED → CANCELLED`)
    requires no compensation.").

    Design: Difficulty/cross_entity_state_dependency/packaging_requires_lot_graded
    """
    ctx = setup_ungraded_lot(measured_syrup_gallons=3.60, with_grader=True)
    record_evaluation(ctx, ctx["lot"]["id"], 90)
    graded = grade_lot(ctx, ctx["lot"]["id"], 80.0)
    assert graded["status"] == "GRADED"
    assert graded["grade"] == "GOLDEN"

    planned = validate_success(
        api.create_packaging_run(
            create_packaging_run_payload(graded["id"],
                                         container_type="RETAIL_QUART",
                                         units_planned=1),
            manager_headers),
        201)
    assert planned["status"] == "PLANNED"
    assert planned["units_planned"] == 1


def test_exact_fit_fill_exhausts_lot(api, manager_headers):
    """PRD §3.9: "On fill, `units_filled` is set equal to `units_planned`,
    `filled_gallons` is computed as `units_planned` multiplied by the container
    capacity, and the lot's `unpackaged_gallons` is decreased by
    `filled_gallons`. When that subtraction leaves the lot at exactly zero
    unpackaged gallons, the lot automatically moves `GRADED → EXHAUSTED`."
    PRD §2.9: "Packaging uses three container types with fixed gallon
    capacities: `DRUM_55` holds 55.0 gallons, `RETAIL_QUART` holds 0.25
    gallons, and `RETAIL_PINT` holds 0.125 gallons."

    Design: Difficulty/boundary_precision_check/packaging_exact_fit_exhaustion
    """
    ctx = setup_single_run_graded_lot(measured_syrup_gallons=55.0)
    assert ctx["lot_at_finish"]["status"] == "HELD"
    assert ctx["lot_at_finish"]["quality_hold_auto"] is True
    assert ctx["lot"]["status"] == "GRADED"
    assert ctx["lot"]["unpackaged_gallons"] == pytest.approx(55.0, abs=0.004)

    run = validate_success(
        api.create_packaging_run(
            create_packaging_run_payload(ctx["lot"]["id"], container_type="DRUM_55",
                                         units_planned=1),
            manager_headers),
        201)
    filled = validate_success(api.fill_packaging_run(run["id"], manager_headers), 200)
    assert filled["status"] == "FILLED"
    assert filled["units_filled"] == 1
    assert filled["filled_gallons"] == pytest.approx(55.0, abs=0.004)

    lot = validate_success(api.get_syrup_lot(ctx["lot"]["id"], manager_headers), 200)
    assert lot["unpackaged_gallons"] == pytest.approx(0.0, abs=0.004)
    assert lot["status"] == "EXHAUSTED"


def test_one_unit_beyond_capacity_rejected(api, manager_headers):
    """PRD §3.9: "The planned volume — `units_planned` multiplied by the
    container's fixed capacity (§2.9) — may not exceed the lot's current
    `unpackaged_gallons` (otherwise `ERR_INSUFFICIENT_UNPACKAGED`); equality is
    allowed."

    Design: Difficulty/boundary_precision_check/packaging_exact_fit_exhaustion
    """
    ctx = setup_single_run_graded_lot(measured_syrup_gallons=55.0)
    res = api.create_packaging_run(
        create_packaging_run_payload(ctx["lot"]["id"], container_type="DRUM_55",
                                     units_planned=2),  # 110.0 > 55.00
        manager_headers)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_UNPACKAGED)

    lot = validate_success(api.get_syrup_lot(ctx["lot"]["id"], manager_headers), 200)
    assert lot["unpackaged_gallons"] == pytest.approx(55.0, abs=0.004)
    assert lot["status"] == "GRADED"


def test_retail_grade_eligibility_beats_volume_shortfall(api, manager_headers):
    """PRD §2.7: "When a single request violates several rules, the server
    reports the violation whose category has the lowest priority number" —
    category 8 ("8. **Structural constraints** — overlap, capacity,
    eligibility, spacing, and uniqueness constraints (`ERR_WINDOW_OVERLAP`,
    `ERR_NO_FREEZE_THAW`, `ERR_TAP_CAPACITY_EXCEEDED`, `ERR_BRIX_BELOW_LEGAL`,
    `ERR_GRADE_NOT_RETAIL_ELIGIBLE`, `ERR_AUDIT_TOO_CLOSE`, `ERR_LEASE_CONFLICT`,
    `ERR_SEASON_ALREADY_ACTIVE`).") beats category 10 ("10. **Quantity
    sufficiency** — draws and fills that exceed available quantity
    (`ERR_DRAW_EXCEEDS_REMAINING`, `ERR_INSUFFICIENT_UNPACKAGED`,
    `ERR_NO_SAP_AVAILABLE`).").
    PRD §3.9: "`RETAIL_QUART` and `RETAIL_PINT` runs may only be planned
    against lots whose `grade` is `GOLDEN` or `AMBER`; attempting retail
    packaging on a `DARK`, `VERY_DARK`, or `PROCESSING` lot is rejected with
    `ERR_GRADE_NOT_RETAIL_ELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/constraint_beats_fiscal_on_packaging_create
    """
    ctx = setup_ungraded_lot(measured_syrup_gallons=3.60, with_grader=True)
    record_evaluation(ctx, ctx["lot"]["id"], 80)
    graded = grade_lot(ctx, ctx["lot"]["id"], 30.0)  # >= 25.0, < 50.0 -> DARK
    assert graded["grade"] == "DARK"

    res = api.create_packaging_run(
        create_packaging_run_payload(graded["id"], container_type="RETAIL_QUART",
                                     units_planned=999),  # 249.75 > 3.60 too
        manager_headers)
    validate_error(res, ApiErrorId.ERR_GRADE_NOT_RETAIL_ELIGIBLE)


def test_insufficient_unpackaged_when_only_volume_violated(api, manager_headers):
    """PRD §3.9: "The planned volume — `units_planned` multiplied by the
    container's fixed capacity (§2.9) — may not exceed the lot's current
    `unpackaged_gallons` (otherwise `ERR_INSUFFICIENT_UNPACKAGED`); equality is
    allowed." With a non-retail container (no grade-eligibility rule for
    DRUM_55), the volume violation surfaces alone.

    Design: Difficulty/priority_pair_validation_conflict/constraint_beats_fiscal_on_packaging_create
    """
    ctx = setup_ungraded_lot(measured_syrup_gallons=3.60, with_grader=True)
    record_evaluation(ctx, ctx["lot"]["id"], 80)
    graded = grade_lot(ctx, ctx["lot"]["id"], 30.0)  # DARK
    assert graded["grade"] == "DARK"

    res = api.create_packaging_run(
        create_packaging_run_payload(graded["id"], container_type="DRUM_55",
                                     units_planned=999),  # 54945.0 > 3.60
        manager_headers)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_UNPACKAGED)


def test_drum_fill_conserves_syrup(api, manager_headers):
    """PRD §2.8: "A syrup lot's `unpackaged_gallons` equals its
    `measured_gallons` minus the total filled volume over its packaging runs in
    status `FILLED`, where each filled run contributes its `units_filled`
    multiplied by the container size."

    Design: Difficulty/compensating_invariant/packaging_fill_syrup_conservation
    """
    ctx = setup_single_run_graded_lot(measured_syrup_gallons=60.0)
    run = validate_success(
        api.create_packaging_run(
            create_packaging_run_payload(ctx["lot"]["id"], container_type="DRUM_55",
                                         units_planned=1),
            manager_headers),
        201)
    validate_success(api.fill_packaging_run(run["id"], manager_headers), 200)

    lot = validate_success(api.get_syrup_lot(ctx["lot"]["id"], manager_headers), 200)
    assert lot["unpackaged_gallons"] == pytest.approx(5.0, abs=0.004)
    assert lot["status"] == "GRADED"
    assert_syrup_conservation(lot, filled_gallons_total=55.0)


def test_retail_fills_exhaust_lot_and_conserve_syrup(api, manager_headers):
    """PRD §2.8: "A syrup lot's `unpackaged_gallons` equals its
    `measured_gallons` minus the total filled volume over its packaging runs in
    status `FILLED`, where each filled run contributes its `units_filled`
    multiplied by the container size."
    PRD §3.9: "When that subtraction leaves the lot at exactly zero unpackaged
    gallons, the lot automatically moves `GRADED → EXHAUSTED`."

    Design: Difficulty/compensating_invariant/packaging_fill_syrup_conservation
    """
    ctx = setup_single_run_graded_lot(measured_syrup_gallons=60.0)
    drum = validate_success(
        api.create_packaging_run(
            create_packaging_run_payload(ctx["lot"]["id"], container_type="DRUM_55",
                                         units_planned=1),
            manager_headers),
        201)
    validate_success(api.fill_packaging_run(drum["id"], manager_headers), 200)

    quarts = validate_success(
        api.create_packaging_run(
            create_packaging_run_payload(ctx["lot"]["id"],
                                         container_type="RETAIL_QUART",
                                         units_planned=20),  # 20 x 0.25 = 5.00
            manager_headers),
        201)
    validate_success(api.fill_packaging_run(quarts["id"], manager_headers), 200)

    lot = validate_success(api.get_syrup_lot(ctx["lot"]["id"], manager_headers), 200)
    assert lot["unpackaged_gallons"] == pytest.approx(0.0, abs=0.004)
    assert lot["status"] == "EXHAUSTED"
    assert_syrup_conservation(lot, filled_gallons_total=60.0)
