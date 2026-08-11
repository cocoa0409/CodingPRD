"""Packaging runs: drawing, the fan-in join, yield, and the emitted lot."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_label,
    assert_abv,
    assert_finished_lot,
    assert_liters,
    assert_packaging_run,
    assert_same_instant,
    assert_utc_date,
    batch_version,
    build_draft_run,
    build_held_lot,
    build_raw_and_pasteurized_lots,
    build_ready_batch,
    build_sourced_run,
    build_two_source_blend,
    create_source_draw_payload,
    draw_source,
    open_run,
    read_batch,
    read_lot,
    read_run,
    record_reading,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

OPERATOR = TEST_USERS["production_operator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# --------------------------------------------------------------------------
# The two ABV variants
# --------------------------------------------------------------------------
def test_the_projection_and_the_measurement_land_on_opposite_sides_of_the_line(api):
    """PRD 2.10: "An alcohol-by-volume figure **at or above 0.50 %** classifies the
    liquid as `ALCOHOLIC`; a figure **strictly below 0.50 %** classifies it as
    `NON_ALCOHOLIC`. Exactly 0.50 % is `ALCOHOLIC`."
    PRD 3.5: "Take `f1_measured_abv_pct`, add 0.06 percentage points for each day of
    `planned_f2_days`, add a further 0.0125 percentage points for each gram per liter
    of `f2_added_sugar_g_per_l`, and round the sum half up to 2 decimal places; the
    result is `projected_abv_pct`."
    PRD 3.6: "`measured_abv_pct` is the greatest `packaging_abv_pct` across the
    sources, rounded half up to 2 decimals."

    Design: Difficulty/dual_variant_calc/projected_and_measured_abv_land_on_opposite_sides_of_the_boundary
    """
    built = build_held_lot(
        api,
        intended_abv_class="ALCOHOLIC",
        style="JUN",
        f1_abvs=(0.10, 0.18, 0.26),
        packaging_abv=0.53,
        liters_drawn=400.0,
        max_units_requested=300,
    )
    batch = read_batch(api, built["batch"]["id"])
    lot = built["lot"]

    assert_abv(batch["projected_abv_pct"], 0.49, "projected_abv_pct")
    assert batch["projected_abv_class"] == "NON_ALCOHOLIC"
    assert_abv(batch["packaging_abv_pct"], 0.53, "packaging_abv_pct")
    assert_abv(lot["measured_abv_pct"], 0.53, "measured_abv_pct")
    assert lot["abv_class"] == "ALCOHOLIC", "the measured figure is the one with legal effect"


def test_the_completed_run_emits_a_held_lot_and_packages_its_exhausted_source(api):
    """PRD 3.6: "On a successful completion the run moves `IN_PROGRESS → COMPLETED`, a
    `FinishedLot` is emitted in `status` `HELD`, and the run's `finished_lot_id`
    mirrors it."
    PRD 3.5: "`PACKAGED` is reached only by the system, when a packaging run completes
    and consumes the last of a source batch's liters: a batch whose `remaining_liters`
    becomes exactly 0 after the run's draws moves `READY_TO_PACKAGE → PACKAGED`, while
    a batch with liters still left stays `READY_TO_PACKAGE` and can feed a second
    run."

    Design: Difficulty/dual_variant_calc/projected_and_measured_abv_land_on_opposite_sides_of_the_boundary
    """
    built = build_held_lot(
        api,
        intended_abv_class="ALCOHOLIC",
        style="JUN",
        f1_abvs=(0.10, 0.18, 0.26),
        packaging_abv=0.53,
        liters_drawn=400.0,
        max_units_requested=300,
    )
    run = read_run(api, built["run"]["id"])
    lot = built["lot"]
    batch = read_batch(api, built["batch"]["id"])

    assert_packaging_run(run)
    assert run["status"] == "COMPLETED"
    assert_liters(run["net_liters"], 388.0, "net_liters after the 3 % loss allowance")
    assert run["finished_lot_id"] == lot["id"]

    assert_finished_lot(lot)
    assert lot["status"] == "HELD"
    assert lot["units_produced"] == 300, "the request cap is the smaller of the two figures"
    assert lot["on_hand_units"] == 300

    assert_liters(batch["remaining_liters"], 0.0, "remaining_liters after the full draw")
    assert batch["ferment_stage"] == "PACKAGED"


# --------------------------------------------------------------------------
# Shelf life: raw versus pasteurized
# --------------------------------------------------------------------------
def test_a_raw_single_source_lot_expires_ninety_days_after_packaging(api):
    """PRD 3.6: "The shelf window is 270 days for a pasteurized run and 90 days for a
    raw one."
    PRD 3.6: "When `source_batch_count` is exactly 1, the base date is the UTC
    calendar date of `packaged_at`, so a batch that sat in a brite tank still gets its
    full window."
    PRD 3.6: "`cold_chain_max_c` is 21.0 degrees Celsius when the run was pasteurized
    and 4.0 degrees Celsius when it was not — raw product needs the cold chain,
    pasteurized product does not."

    Design: Difficulty/dual_variant_calc/raw_and_pasteurized_runs_from_one_batch_get_different_best_by_dates
    """
    built = build_raw_and_pasteurized_lots(api)
    lot = built["lot_raw"]

    assert_utc_date(lot["best_by_date"], "2026-08-08", "raw best_by_date")
    assert_abv(lot["cold_chain_max_c"], 4.0, "raw cold_chain_max_c")
    assert lot["pasteurized"] is False
    assert lot["units_produced"] == 258


def test_a_pasteurized_single_source_lot_expires_two_hundred_and_seventy_days_later(api):
    """PRD 3.6: "The shelf window is 270 days for a pasteurized run and 90 days for a
    raw one."
    PRD 3.6: "`best_by_date` is that base date advanced by the shelf window in whole
    days and normalised to `00:00:00.000Z`."
    PRD 2.11: "For every batch, `pitched_liters` always equals `remaining_liters` plus
    `drawn_liters` plus `loss_liters`."

    Design: Difficulty/dual_variant_calc/raw_and_pasteurized_runs_from_one_batch_get_different_best_by_dates
    """
    built = build_raw_and_pasteurized_lots(api)
    lot = built["lot_pasteurized"]

    assert_utc_date(lot["best_by_date"], "2027-02-04", "pasteurized best_by_date")
    assert_abv(lot["cold_chain_max_c"], 21.0, "pasteurized cold_chain_max_c")
    assert lot["pasteurized"] is True
    assert lot["units_produced"] == 258

    batch = built["batch"]
    assert_liters(batch["drawn_liters"], 200.0, "drawn_liters after both runs")
    assert_liters(batch["remaining_liters"], 200.0, "remaining_liters after both runs")


# --------------------------------------------------------------------------
# Yield
# --------------------------------------------------------------------------
def _two_runs_ready_to_start(api):
    ready = build_ready_batch(api, vessel_code="FV-3", batch_code="B-3001", culture_label="Mother C")
    label = approve_label(api, ready["recipe"]["id"], abv_class="NON_ALCOHOLIC", pasteurized=False)
    run_big = open_run(
        api, ready["recipe"]["id"], label["id"], run_code="PR-BIG", fmt="BOTTLE",
        pasteurized=False, max_units_requested=300,
    )
    run_cap = open_run(
        api, ready["recipe"]["id"], label["id"], run_code="PR-CAP", fmt="BOTTLE",
        pasteurized=False, max_units_requested=200,
    )
    draw_source(api, run_big["id"], ready["batch"]["id"], 100.0)
    draw_source(api, run_cap["id"], ready["batch"]["id"], 100.0)
    set_clock(api, "2026-05-10T00:00:00.000Z")
    record_reading(
        api, ready["batch"]["id"], reading_type="PACKAGING",
        reading_at="2026-05-10T00:00:00.000Z", ph=3.25, temperature_c=20.0,
        brix=3.0, abv_pct=0.44,
    )
    return ready, run_big, run_cap


def test_the_yield_floors_the_container_count_from_the_rounded_net_liters(api):
    """PRD 3.6: "Take `gross_liters`, the rounded sum of the draws. Deduct the 3 %
    packaging loss allowance — multiply `gross_liters` by 97 and divide by 100 — and
    round that result half up to 2 decimal places to obtain `net_liters`."
    PRD 3.6: "Select the container size by format: 19.5 liters for `KEG`, 0.375 liters
    for `BOTTLE`, 0.355 liters for `CAN`."
    PRD 3.6: "The scaffold's worked example: two draws of 60.00 L and 40.00 L in
    `BOTTLE` format with `max_units_requested` 300 give `gross_liters` 100.00,
    `net_liters` 97.00, a capacity of 258 whole bottles, and therefore
    `units_produced` 258."

    Design: Difficulty/combinatorial_formula/packaging_yield_nested_floor_then_min_against_the_request_cap
    """
    _, run_big, _ = _two_runs_ready_to_start(api)

    started = validate_success(api.start_packaging_run(run_big["id"], OPERATOR))

    assert_liters(started["gross_liters"], 100.0, "gross_liters")
    assert_liters(started["net_liters"], 97.0, "net_liters")
    assert started["units_produced"] == 258, "floor(97.00 / 0.375) is 258 whole bottles"
    assert started["status"] == "IN_PROGRESS"


def test_the_yield_takes_the_request_cap_when_it_is_the_smaller_figure(api):
    """PRD 3.6: "Divide `net_liters` by that container size and discard the fractional
    part to get the capacity in whole units, then take `units_produced` as the smaller
    of that capacity and `max_units_requested`."

    Design: Difficulty/combinatorial_formula/packaging_yield_nested_floor_then_min_against_the_request_cap
    """
    _, run_big, run_cap = _two_runs_ready_to_start(api)
    validate_success(api.start_packaging_run(run_big["id"], OPERATOR))

    started = validate_success(api.start_packaging_run(run_cap["id"], OPERATOR))

    assert_liters(started["net_liters"], 97.0, "net_liters")
    assert started["units_produced"] == 200, "the 200-unit request cap is the smaller figure"


# --------------------------------------------------------------------------
# The half-percent boundary
# --------------------------------------------------------------------------
def test_a_measured_abv_of_exactly_half_a_percent_is_alcoholic(api):
    """PRD 2.10: "An alcohol-by-volume figure **at or above 0.50 %** classifies the
    liquid as `ALCOHOLIC`; a figure **strictly below 0.50 %** classifies it as
    `NON_ALCOHOLIC`. Exactly 0.50 % is `ALCOHOLIC`."

    Design: Difficulty/boundary_precision_check/measured_abv_of_exactly_half_a_percent_is_alcoholic
    """
    built = build_held_lot(
        api,
        intended_abv_class="ALCOHOLIC",
        style="JUN",
        f1_abvs=(0.10, 0.18, 0.26),
        packaging_abv=0.50,
        liters_drawn=100.0,
        run_code="PR-11",
        vessel_code="FV-11",
        batch_code="B-11001",
    )
    lot = built["lot"]

    assert_abv(lot["measured_abv_pct"], 0.50, "measured_abv_pct")
    assert lot["abv_class"] == "ALCOHOLIC", "exactly 0.50 sits on the alcoholic side"
    assert read_run(api, built["run"]["id"])["status"] == "COMPLETED"


def test_the_projection_stays_non_alcoholic_when_the_measurement_reaches_the_line(api):
    """PRD 2.10: "Before the fill, a batch carries `projected_abv_pct` — a
    forward-looking estimate that models a secondary fermentation which has not
    happened yet — and the class implied by it is stored as `projected_abv_class`."
    PRD 2.10: "An alcohol-by-volume figure **at or above 0.50 %** classifies the
    liquid as `ALCOHOLIC`; a figure **strictly below 0.50 %** classifies it as
    `NON_ALCOHOLIC`. Exactly 0.50 % is `ALCOHOLIC`."

    Design: Difficulty/boundary_precision_check/measured_abv_of_exactly_half_a_percent_is_alcoholic
    """
    built = build_held_lot(
        api,
        intended_abv_class="ALCOHOLIC",
        style="JUN",
        f1_abvs=(0.10, 0.18, 0.26),
        packaging_abv=0.50,
        liters_drawn=100.0,
        run_code="PR-11",
        vessel_code="FV-11",
        batch_code="B-11001",
    )
    batch = read_batch(api, built["batch"]["id"])

    assert_abv(batch["projected_abv_pct"], 0.49, "projected_abv_pct one hundredth below the line")
    assert batch["projected_abv_class"] == "NON_ALCOHOLIC"
    assert built["lot"]["abv_class"] == "ALCOHOLIC", "the two figures are allowed to disagree"


# --------------------------------------------------------------------------
# The zero-source boundary
# --------------------------------------------------------------------------
def test_starting_a_run_with_no_draws_is_a_blend_rule_violation(api):
    """PRD 3.6: "The state gate deliberately admits a `DRAFT` run so that the
    zero-draw case is reachable, and a run with no draws then fails on the very next
    rung with `ERR_BLEND_RULE_VIOLATION`."

    Design: Difficulty/boundary_precision_check/starting_a_run_with_an_empty_source_set_is_refused
    """
    built = build_draft_run(api, run_code="PR-EMPTY")

    response = api.start_packaging_run(built["run"]["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_BLEND_RULE_VIOLATION.value, 422)


def test_the_refused_empty_start_leaves_the_run_in_draft_with_no_yield(api):
    """PRD 3.6: "The run opens in `status` `DRAFT` with `created_by_user_id` set to
    the acting `X-User-ID`, an empty `source_draws` list, `source_batch_count` 0,
    `gross_liters` 0 and `units_produced` 0."
    PRD 2.8: "(4) the run's `status` is `DRAFT` or `SOURCED`, else `ERR_INVALID_STATE`
    — a `DRAFT` run is deliberately admitted by this rung so that the zero-source
    boundary is reachable, and it then always fails the next one; (5)
    `source_batch_count` is at least 1, else `ERR_BLEND_RULE_VIOLATION`"

    Design: Difficulty/boundary_precision_check/starting_a_run_with_an_empty_source_set_is_refused
    """
    built = build_draft_run(api, run_code="PR-EMPTY")

    response = api.start_packaging_run(built["run"]["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_BLEND_RULE_VIOLATION.value, 422)

    run = read_run(api, built["run"]["id"])
    assert run["status"] == "DRAFT"
    assert run["source_batch_count"] == 0
    assert_liters(run["gross_liters"], 0.0, "gross_liters on a never-sourced run")
    assert run["units_produced"] == 0


# --------------------------------------------------------------------------
# The label must still be current when the run starts
# --------------------------------------------------------------------------
def _sourced_run_on_a_stale_label(api):
    ready = build_ready_batch(api, vessel_code="FV-13", batch_code="B-13001", culture_label="Mother M")
    label = approve_label(api, ready["recipe"]["id"], abv_class="NON_ALCOHOLIC", pasteurized=False)
    validate_success(
        api.revise_recipe(ready["recipe"]["id"], {"change_note": "Tea blend changed"}, OPERATOR)
    )
    run = open_run(
        api, ready["recipe"]["id"], label["id"], run_code="PR-13", fmt="BOTTLE",
        pasteurized=False, max_units_requested=300,
    )
    draw_source(api, run["id"], ready["batch"]["id"], 100.0)
    return ready, label, run


def test_starting_a_run_whose_label_went_stale_is_refused(api):
    """PRD 3.6: "Then the label is tested three ways: its `status` must be `APPROVED`,
    where a `STALE` revision answers `ERR_LABEL_STALE` and a `DRAFT` or `SUBMITTED`
    one answers `ERR_INVALID_STATE`; its `approved_recipe_version_number` must still
    equal the recipe's current `recipe_version_number`, and a mismatch is
    `ERR_LABEL_STALE`; and its `pasteurized` must equal the run's `pasteurized`, with
    a mismatch answering `ERR_LABEL_CLASS_MISMATCH`."

    Design: Difficulty/cross_entity_state_dependency/starting_a_run_whose_label_predates_the_current_recipe_version_is_refused
    """
    _, _, run = _sourced_run_on_a_stale_label(api)

    response = api.start_packaging_run(run["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_LABEL_STALE.value, 409)

    after = read_run(api, run["id"])
    assert after["status"] == "SOURCED", "the refused start leaves the run where it was"
    assert after["units_produced"] == 0


def test_the_stale_label_keeps_the_recipe_version_it_captured_at_approval(api):
    """PRD 3.1: "On success the revision moves `SUBMITTED → APPROVED`,
    `approved_recipe_version_number` captures the recipe's `recipe_version_number` at
    that instant, `approved_by_user_id` records the approver and `approved_at` the
    logical clock, the recipe's `active_label_approval_id` is pointed at this
    revision, and any *other* revision of the same recipe that was `APPROVED` is
    pushed to `STALE` with `stale_reason` `RECIPE_REVISED`."
    PRD 2.9: "The packaging run's label revision is `APPROVED` and its
    `approved_recipe_version_number` equals the recipe's current
    `recipe_version_number`, checked when the run is started — otherwise
    `ERR_LABEL_STALE` (409)."

    Design: Difficulty/cross_entity_state_dependency/starting_a_run_whose_label_predates_the_current_recipe_version_is_refused
    """
    ready, label, run = _sourced_run_on_a_stale_label(api)

    validate_error(
        api.start_packaging_run(run["id"], OPERATOR), ApiErrorId.ERR_LABEL_STALE.value, 409
    )

    labels = validate_success(
        api.list_recipe_label_approvals(ready["recipe"]["id"], COMPLIANCE)
    )
    revision = [row for row in labels if row["id"] == label["id"]][0]
    assert revision["status"] == "STALE"
    assert revision["approved_recipe_version_number"] == 1
    assert validate_success(
        api.get_recipe(ready["recipe"]["id"], OPERATOR)
    )["recipe_version_number"] == 2


# --------------------------------------------------------------------------
# Aborting a run is a true compensation
# --------------------------------------------------------------------------
def test_aborting_a_run_returns_every_drawn_liter_to_its_source_batch(api):
    """PRD 3.6: "It is a true compensation: for every entry in `source_draws`, the
    batch's `drawn_liters` is decreased and its `remaining_liters` increased by
    exactly that entry's liters, and each affected batch's `version` is incremented."
    PRD 2.11: "Drawing liters into a packaging run and then aborting that run must
    restore the batch to its exact prior split."

    Design: Difficulty/compensating_invariant/aborting_a_run_returns_every_drawn_liter_to_the_batch
    """
    built = build_sourced_run(
        api, liters_drawn=137.5, run_code="PR-15", vessel_code="FV-15", batch_code="B-15001"
    )

    aborted = validate_success(
        api.abort_packaging_run(built["run"]["id"], {"reason": "Filler breakdown"}, OPERATOR)
    )

    assert aborted["status"] == "ABORTED"
    assert aborted["source_batch_count"] == 1, "source_draws are retained for audit"

    batch = read_batch(api, built["batch"]["id"])
    assert_liters(batch["drawn_liters"], 0.0, "drawn_liters restored to exactly zero")
    assert_liters(batch["remaining_liters"], 400.0, "remaining_liters restored")
    assert_liters(batch["loss_liters"], 0.0, "loss_liters untouched by the abort")
    assert_liters(batch["pitched_liters"], 400.0, "pitched_liters never moves")
    assert batch["ferment_stage"] == "READY_TO_PACKAGE"


def test_an_aborted_run_emits_no_finished_lot(api):
    """PRD 3.6: "`source_draws` itself is retained for audit, and no `FinishedLot` is
    created."
    PRD 3.6: "A batch that was drawn and then returned by an abort is not a source of
    any lot, and an `ABORTED` run is never touched by the recall cascade — it emitted
    nothing to recall."

    Design: Difficulty/compensating_invariant/aborting_a_run_returns_every_drawn_liter_to_the_batch
    """
    built = build_sourced_run(
        api, liters_drawn=137.5, run_code="PR-15", vessel_code="FV-15", batch_code="B-15001"
    )

    aborted = validate_success(
        api.abort_packaging_run(built["run"]["id"], {"reason": "Filler breakdown"}, OPERATOR)
    )
    assert aborted["finished_lot_id"] is None

    rows, meta = validate_paginated(
        api.list_finished_lots(OPERATOR, params={"packaging_run_id": built["run"]["id"]})
    )
    assert meta["total_count"] == 0 and rows == []


# --------------------------------------------------------------------------
# The blend
# --------------------------------------------------------------------------
def test_a_blend_inherits_the_highest_abv_and_the_earliest_shelf_clock(api):
    """PRD 3.6: "`measured_abv_pct` is the greatest `packaging_abv_pct` across the
    sources, rounded half up to 2 decimals."
    PRD 3.6: "When `source_batch_count` is 2 or more, the base date is the **earliest**
    UTC calendar date among the `f2_completed_at` values of the run's source batches,
    so a blend inherits the oldest liquid's remaining life and expires sooner than
    either single-source variant would."

    Design: Corner/calculations/a_blended_lot_inherits_the_highest_abv_and_the_earliest_shelf_clock
    """
    built = build_two_source_blend(api)

    run = validate_success(api.complete_packaging_run(built["run"]["id"], OPERATOR))
    lot = read_lot(api, run["finished_lot_id"])

    assert run["source_batch_count"] == 2
    assert_liters(run["gross_liters"], 100.0, "gross_liters")
    assert_liters(run["net_liters"], 97.0, "net_liters")
    assert lot["units_produced"] == 258
    assert_abv(lot["measured_abv_pct"], 0.45, "the maximum of 0.42 and 0.45")
    assert lot["abv_class"] == "NON_ALCOHOLIC"
    assert_utc_date(lot["best_by_date"], "2026-08-07", "blended best_by_date")
    assert_same_instant(lot["packaged_at"], "2026-05-12T00:00:00.000Z", "packaged_at")

    assert_liters(
        read_batch(api, built["batch_one"]["id"])["remaining_liters"], 340.0, "first source"
    )
    assert_liters(
        read_batch(api, built["batch_two"]["id"])["remaining_liters"], 360.0, "second source"
    )


def test_the_divergence_rung_outranks_the_label_class_rung(api):
    """PRD 3.6: "First, the divergence test: the lot's measured ABV may exceed the
    greatest `projected_abv_pct` across the source batches by at most 0.05 percentage
    points, inclusive — a divergence of exactly 0.05 is accepted, strictly more is
    `ERR_ABV_CLASS_DIVERGENCE`."
    PRD 3.6: "When a single request would trip both, the divergence answers first — a
    measured figure that has run away from its projection is a measurement-integrity
    problem, and the label mismatch it produces is merely the symptom."

    Design: Corner/errors/divergence_outranks_class_mismatch_when_the_measured_abv_runs_away
    """
    ready = build_ready_batch(
        api, vessel_code="FV-37", batch_code="B-37001", culture_label="Mother AF",
        f1_abvs=(0.10, 0.18, 0.26), f2_abv=0.40,
    )
    label = approve_label(api, ready["recipe"]["id"], abv_class="NON_ALCOHOLIC", pasteurized=False)
    run_a = open_run(
        api, ready["recipe"]["id"], label["id"], run_code="PR-37A", fmt="BOTTLE",
        pasteurized=False, max_units_requested=300,
    )
    run_b = open_run(
        api, ready["recipe"]["id"], label["id"], run_code="PR-37B", fmt="BOTTLE",
        pasteurized=False, max_units_requested=300,
    )
    draw_source(api, run_a["id"], ready["batch"]["id"], 60.0)
    draw_source(api, run_b["id"], ready["batch"]["id"], 40.0)
    set_clock(api, "2026-05-10T00:00:00.000Z")
    record_reading(
        api, ready["batch"]["id"], reading_type="PACKAGING",
        reading_at="2026-05-10T00:00:00.000Z", ph=3.25, temperature_c=20.0,
        brix=3.0, abv_pct=0.53,
    )
    validate_success(api.start_packaging_run(run_a["id"], OPERATOR))
    validate_success(api.start_packaging_run(run_b["id"], OPERATOR))

    # 0.53 against a 0.49 projection stays inside the 0.05 tolerance, so the
    # alcoholic measurement collides with the non-alcoholic artwork instead.
    validate_error(
        api.complete_packaging_run(run_a["id"], OPERATOR),
        ApiErrorId.ERR_LABEL_CLASS_MISMATCH.value,
        422,
    )

    set_clock(api, "2026-05-12T00:00:00.000Z")
    record_reading(
        api, ready["batch"]["id"], reading_type="PACKAGING",
        reading_at="2026-05-12T00:00:00.000Z", ph=3.22, temperature_c=20.0,
        brix=2.9, abv_pct=0.60,
    )
    validate_error(
        api.complete_packaging_run(run_b["id"], OPERATOR),
        ApiErrorId.ERR_ABV_CLASS_DIVERGENCE.value,
        422,
    )

    batch = read_batch(api, ready["batch"]["id"])
    assert_abv(batch["projected_abv_pct"], 0.49, "projected_abv_pct")
    assert_abv(batch["packaging_abv_pct"], 0.60, "packaging_abv_pct after the second reading")
    assert read_run(api, run_a["id"])["status"] == "IN_PROGRESS"
    assert read_run(api, run_b["id"])["status"] == "IN_PROGRESS"
    assert read_run(api, run_a["id"])["finished_lot_id"] is None
    assert read_run(api, run_b["id"])["finished_lot_id"] is None


def test_the_blend_minimum_and_the_batch_remainder_rungs_answer_their_own_codes(api):
    """PRD 3.6: "A run may hold at most 4 draws — `source_batch_count` must be
    strictly below 4 before a new one is appended — and each individual draw must be
    at or above 20.0 liters; violating either is `ERR_BLEND_RULE_VIOLATION`."
    PRD 3.6: "The draw may not exceed the batch's `remaining_liters`, and exceeding it
    is `ERR_INSUFFICIENT_BATCH_VOLUME`."

    Design: Corner/errors/blend_minimum_and_batch_remainder_rungs_fire_in_the_declared_order
    """
    ready = build_ready_batch(
        api, vessel_code="FV-38", batch_code="B-38001", culture_label="Mother AG"
    )
    label = approve_label(api, ready["recipe"]["id"], abv_class="NON_ALCOHOLIC", pasteurized=False)
    run = open_run(
        api, ready["recipe"]["id"], label["id"], run_code="PR-38", fmt="BOTTLE",
        pasteurized=False, max_units_requested=300,
    )
    version = batch_version(api, ready["batch"]["id"])

    too_small = api.add_packaging_run_source(
        run["id"], create_source_draw_payload(ready["batch"]["id"], 19.9, version), OPERATOR
    )
    validate_error(too_small, ApiErrorId.ERR_BLEND_RULE_VIOLATION.value, 422)

    too_large = api.add_packaging_run_source(
        run["id"], create_source_draw_payload(ready["batch"]["id"], 500.0, version), OPERATOR
    )
    validate_error(too_large, ApiErrorId.ERR_INSUFFICIENT_BATCH_VOLUME.value, 422)

    after_run = read_run(api, run["id"])
    assert after_run["status"] == "DRAFT"
    assert after_run["source_batch_count"] == 0

    batch = read_batch(api, ready["batch"]["id"])
    assert_liters(batch["drawn_liters"], 0.0, "no refused draw moves drawn_liters")
    assert_liters(batch["remaining_liters"], 400.0, "remaining_liters")


def test_a_second_draw_carrying_the_pre_draw_batch_version_is_rejected(api):
    """PRD 2.6: "Adding a source draw to a packaging run
    (`POST /packaging-runs/{id}/sources`) requires `expected_batch_version`, which
    must equal the current `version` of the `Batch` named by `batch_id`. If another
    writer has advanced that batch's `version` since the client last read it, the draw
    is rejected with `ERR_STALE_VERSION` (HTTP 412) — the client believes liters are
    still there that have already been drawn."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_batch_version_rejects_a_second_source_draw
    """
    ready = build_ready_batch(
        api, vessel_code="FV-31", batch_code="B-31001", culture_label="Mother AB"
    )
    label = approve_label(api, ready["recipe"]["id"], abv_class="NON_ALCOHOLIC", pasteurized=False)
    run = open_run(
        api, ready["recipe"]["id"], label["id"], run_code="PR-31", fmt="BOTTLE",
        pasteurized=False, max_units_requested=300,
    )
    stale_version = batch_version(api, ready["batch"]["id"])
    validate_success(
        api.add_packaging_run_source(
            run["id"],
            create_source_draw_payload(ready["batch"]["id"], 60.0, stale_version),
            OPERATOR,
        )
    )

    rejected = api.add_packaging_run_source(
        run["id"],
        create_source_draw_payload(ready["batch"]["id"], 40.0, stale_version),
        OPERATOR,
    )
    validate_error(rejected, ApiErrorId.ERR_STALE_VERSION.value, 412)

    midway = read_run(api, run["id"])
    assert midway["source_batch_count"] == 1
    assert_liters(midway["gross_liters"], 60.0, "gross_liters after the rejected draw")

    accepted = draw_source(api, run["id"], ready["batch"]["id"], 40.0)
    assert accepted["source_batch_count"] == 2
    assert_liters(accepted["gross_liters"], 100.0, "gross_liters after the fresh-token draw")

    batch = read_batch(api, ready["batch"]["id"])
    assert_liters(batch["drawn_liters"], 100.0, "drawn_liters")
    assert_liters(batch["remaining_liters"], 300.0, "remaining_liters")
