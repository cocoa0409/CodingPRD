"""Non-linear state shapes on two different aggregates.

A model run carries four status dimensions that move on four different triggers,
so its observable state is a 4-tuple rather than a point on one pipeline; an
experiment carries a genuine cycle whose reject arm returns to `DRAFT` and whose
accept arm reaches the terminal `CLOSED`, both through the same endpoint.

Every test builds its own preconditions from scratch: the harness relaunches the
API against an empty database before each one.
"""

from test_helpers import (
    assertions as a,
    factories as f,
    fixtures as fx,
    test_users as users,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


def _rejected_audience_split_experiment(api):
    """One AUDIENCE_SPLIT experiment on A_SEARCH carried to REJECTED.

    No data window and no model run are needed: the reject arm fires no cascade,
    and the clock is left past the experiment's end date so every later start and
    read-out clears its temporal gate immediately. The rejecting lead al-1 is a
    different operator from the designing ed-1.
    """
    ctx = fx.market_with_channels(api)
    experiment = fx.create_experiment(api, ctx)
    experiment = fx.locked_experiment(api, ctx, experiment=experiment)
    fx.set_clock(api, fx.CLOCK_EXPERIMENT_STARTED)
    experiment = validate_success(
        api.start_experiment(experiment["id"], users.EXPERIMENT_DESIGNER)
    )
    fx.set_clock(api, fx.CLOCK_EXPERIMENT_ELAPSED)
    experiment = validate_success(
        api.read_out_experiment(
            experiment["id"], f.read_out_payload(), users.EXPERIMENT_DESIGNER
        )
    )
    experiment = validate_success(
        api.reject_experiment(
            experiment["id"], f.reject_payload(), users.ANALYTICS_LEAD
        )
    )
    return ctx, experiment


def _relock_and_reject(api, experiment_id):
    """Carry a redesigned DRAFT back through lock, start, read-out and reject."""
    locked = validate_success(
        api.lock_design(experiment_id, users.EXPERIMENT_DESIGNER)
    )
    validate_success(api.start_experiment(experiment_id, users.EXPERIMENT_DESIGNER))
    validate_success(
        api.read_out_experiment(
            experiment_id, f.read_out_payload(), users.EXPERIMENT_DESIGNER
        )
    )
    rejected = validate_success(
        api.reject_experiment(experiment_id, f.reject_payload(), users.ANALYTICS_LEAD)
    )
    return locked, rejected


def test_validate_advances_only_the_validation_status_axis(api):
    """PRD §3.4: "Those four dimensions evolve independently on different
    triggers, and no movement in one implies a movement in another except where
    this document says so."
    PRD §3.5: "`validation_status` becomes `HOLDOUT_PASSED` when
    `holdout_mape_pct` is at most 12.00 and `HOLDOUT_FAILED` when it is above
    12.00."

    Design: Difficulty/non_linear_state_machine/model_run_four_parallel_state_dimensions
    """
    ctx = fx.fitted_run(api)
    run_before = ctx["run"]
    a.assert_run_state(
        run_before, "FITTED", "UNVALIDATED", "NOT_REQUIRED", "UNPUBLISHED"
    )

    run_after = validate_success(
        api.validate_model_run(run_before["id"], users.MODELER)
    )

    a.assert_run_state(
        run_after, "FITTED", "HOLDOUT_PASSED", "NOT_REQUIRED", "UNPUBLISHED"
    )
    assert run_after["holdout_mape_pct"] == fx.F1_EFFECT_HOLDOUT_MAPE_PCT, (
        "the backtest over the single trailing holdout period should score "
        f"{fx.F1_EFFECT_HOLDOUT_MAPE_PCT}, got {run_after['holdout_mape_pct']!r}"
    )
    assert run_after["publication_status"] == "UNPUBLISHED", (
        "validating a run must not touch the publication dimension"
    )
    assert run_after["previous_published_run_id"] is None, (
        "previous_published_run_id stays null until the run itself publishes"
    )


def test_publish_advances_only_the_publication_status_axis(api):
    """PRD §3.5: "A successful publication records `previous_published_run_id` as
    the identifier of the market's outgoing published run — null when there was
    none, and null forever for the market's first publication — sets
    `publication_status` to `PUBLISHED`, records the deciding operator in
    `published_by_user_id`, and increments `version`."
    PRD §3.5: "When there is none, this is the market's first publication:
    `stability_score` is recorded as exactly 1.0000, `refresh_generation` is 1,
    and the stability gate is skipped entirely."
    PRD §2.8: "Second: if the market has no model run whose `publication_status`
    is `PUBLISHED`, or that published run's `calibration_status` is `STALE`, or
    the market has no data window in `SEALED` status, the posture is
    `RESTRICTED`. Otherwise the posture is `OPEN`."

    Design: Difficulty/non_linear_state_machine/model_run_four_parallel_state_dimensions
    """
    ctx = fx.validated_run(api)
    run_before = ctx["run"]
    a.assert_run_state(
        run_before, "FITTED", "HOLDOUT_PASSED", "NOT_REQUIRED", "UNPUBLISHED"
    )

    run_after = validate_success(
        api.publish_model_run(run_before["id"], users.ANALYTICS_LEAD)
    )

    a.assert_run_state(
        run_after, "FITTED", "HOLDOUT_PASSED", "NOT_REQUIRED", "PUBLISHED"
    )
    assert run_after["previous_published_run_id"] is None, (
        "the market's first publication displaces nothing, so "
        "previous_published_run_id stays null"
    )
    assert run_after["refresh_generation"] == 1, (
        f"a first publication is generation 1, got {run_after['refresh_generation']!r}"
    )
    assert run_after["published_by_user_id"] == users.ANALYTICS_LEAD_ID, (
        "the deciding operator is recorded in published_by_user_id"
    )
    assert run_after["holdout_mape_pct"] == fx.F1_EFFECT_HOLDOUT_MAPE_PCT, (
        "publication must leave the validation axis and its stored error alone"
    )
    market = fx.refresh_market(api, ctx)
    assert market["published_model_run_id"] == run_after["id"], (
        "the market projects the single run whose publication_status is PUBLISHED"
    )
    assert market["data_posture"] == "OPEN", (
        "a sealed window plus a published, non-stale run lifts the posture to "
        f"OPEN, got {market['data_posture']!r}"
    )


def test_calibration_record_advances_only_the_calibration_status_axis(api):
    """PRD §3.7: "The parent run's `calibration_status` moves to
    `PENDING_CALIBRATION`, which it does from `NOT_REQUIRED`, from `CALIBRATED`,
    from `STALE`, and from `PENDING_CALIBRATION` itself when a second channel's
    record arrives."
    PRD §3.7: "`calibration_multiplier` is then `experiment_lift_pct` divided by
    `model_implied_lift_pct`, rounded half-up to four decimal places, and
    constrained to lie within the closed range from 0.25 to 4.00."
    PRD §3.4: "A row's `is_current` becomes false whenever its producing run's
    `fit_status` leaves `FITTED` or its `publication_status` becomes
    `SUPERSEDED`."

    Design: Difficulty/non_linear_state_machine/model_run_four_parallel_state_dimensions
    """
    ctx = fx.experiment_on_published_market(api)
    run_before = fx.refresh_run(api, ctx)
    a.assert_run_state(
        run_before, "FITTED", "HOLDOUT_PASSED", "NOT_REQUIRED", "PUBLISHED"
    )

    record = fx.file_calibration_record(api, ctx)

    run_after = fx.refresh_run(api, ctx)
    a.assert_run_state(
        run_after, "FITTED", "HOLDOUT_PASSED", "PENDING_CALIBRATION", "PUBLISHED"
    )
    assert record["experiment_lift_pct"] == fx.F1_DID_MEASURED_LIFT_PCT, (
        "experiment_lift_pct is copied from the readout's measured_lift_pct"
    )
    assert record["model_implied_lift_pct"] == fx.F1_MODEL_IMPLIED_LIFT_PCT, (
        f"expected model_implied_lift_pct {fx.F1_MODEL_IMPLIED_LIFT_PCT}, "
        f"got {record['model_implied_lift_pct']!r}"
    )
    assert record["calibration_multiplier"] == fx.F1_CALIBRATION_MULTIPLIER, (
        f"expected calibration_multiplier {fx.F1_CALIBRATION_MULTIPLIER}, "
        f"got {record['calibration_multiplier']!r}"
    )
    assert record["bias_direction"] == "OVER_ATTRIBUTED", (
        "a multiplier strictly below 0.95 is OVER_ATTRIBUTED, got "
        f"{record['bias_direction']!r}"
    )
    assert record["model_run_version_after"] == run_after["version"], (
        "model_run_version_after echoes the run version the write left behind"
    )
    market = fx.refresh_market(api, ctx)
    assert market["data_posture"] == "OPEN", (
        "PENDING_CALIBRATION is not STALE, so the posture ladder stays at OPEN, "
        f"got {market['data_posture']!r}"
    )
    contribution = a.rows_by(
        fx.contributions_of(api, run_after["id"]), "channel_id"
    )[ctx["a_search"]["id"]]
    assert contribution["is_current"] is True, (
        "the fit dimension never left FITTED, so the decomposition row is still "
        "current"
    )
    assert contribution["contribution_units"] == fx.F1_EFFECT_CONTRIBUTION_A_SEARCH, (
        "filing a record derives a correction but does not re-decompose the run"
    )


def test_release_cells_from_rejected_loops_back_to_draft_clearing_computed_fields(api):
    """PRD §3.6: "Releasing the cells is the last step of the lifecycle, and it is
    a single operation whose destination is chosen by the **source state**, not by
    anything in the request."
    PRD §3.6: "The loop increments `redesign_count`, clears `computed_power` and
    `power_index` back to null, clears all four conversion counts and all four
    lift fields — `measured_lift_pct`, `lift_ci_half_width_pct`,
    `lift_ci_low_pct` and `lift_ci_high_pct` — back to null, resets
    `treatment_population` and `control_population` to 0, and increments
    `version`."
    PRD §3.6: "The design parameters supplied at draft time survive the loop;
    everything the lifecycle computed does not."

    Design: Difficulty/non_linear_state_machine/experiment_reject_redesign_cycle_bounded_by_max_redesigns
    """
    ctx, rejected = _rejected_audience_split_experiment(api)
    assert rejected["status"] == "REJECTED", rejected["status"]
    assert rejected["redesign_count"] == 0, (
        "the reject itself does not consume a redesign, got "
        f"{rejected['redesign_count']!r}"
    )
    assert rejected["measured_lift_pct"] == fx.F1_DID_MEASURED_LIFT_PCT, (
        "the readout's lift is on the row before the loop clears it"
    )

    redrafted = validate_success(
        api.release_cells(rejected["id"], users.EXPERIMENT_DESIGNER)
    )

    assert redrafted["status"] == "DRAFT", (
        f"release-cells from REJECTED returns to DRAFT, got {redrafted['status']!r}"
    )
    assert redrafted["redesign_count"] == 1, (
        f"the loop increments redesign_count to 1, got {redrafted['redesign_count']!r}"
    )
    a.assert_draft_experiment_fields_cleared(redrafted)
    assert redrafted["version"] > rejected["version"], (
        "the loop increments version"
    )
    assert redrafted["minimum_detectable_effect_pct"] == 5.0, (
        "the design parameters supplied at draft time survive the loop"
    )
    assert redrafted["planned_treatment_population"] == f.EXPERIMENT_ARM_POPULATION, (
        "planned arm sizes are design parameters and survive the loop"
    )
    assert redrafted["planned_control_population"] == f.EXPERIMENT_ARM_POPULATION, (
        "planned arm sizes are design parameters and survive the loop"
    )


def test_second_redesign_loop_relocks_the_power_gate_and_reaches_count_two(api):
    """PRD §3.6: "From `REJECTED` it loops back to `DRAFT` for a redesign, but only
    while `redesign_count` is still below two — a third loop is refused with
    `ERR_REDESIGN_LIMIT_REACHED`."
    PRD §3.6: "A successful lock freezes `power_index` and `computed_power` onto
    the row, sets `status` to `DESIGN_LOCKED` and increments `version`. For an
    `AUDIENCE_SPLIT` design it also copies `planned_treatment_population` into
    `treatment_population` and `planned_control_population` into
    `control_population`, because that design has nothing further to enlist."
    PRD §3.6: "No other experiment on the same market and channel whose status is
    `DESIGN_LOCKED`, `CELLS_ASSIGNED`, `RUNNING`, `READ_OUT` or `ACCEPTED` may
    occupy an overlapping interval."

    Design: Difficulty/non_linear_state_machine/experiment_reject_redesign_cycle_bounded_by_max_redesigns
    """
    ctx, rejected = _rejected_audience_split_experiment(api)
    first_loop = validate_success(
        api.release_cells(rejected["id"], users.EXPERIMENT_DESIGNER)
    )
    assert first_loop["redesign_count"] == 1, first_loop["redesign_count"]

    relocked, rejected_again = _relock_and_reject(api, rejected["id"])

    assert relocked["status"] == "DESIGN_LOCKED", (
        "the redesigned draft locks again without colliding with itself on the "
        f"channel-window occupancy test, got {relocked['status']!r}"
    )
    assert relocked["power_index"] == fx.F1_POWER_INDEX_BOUNDARY, (
        f"the re-lock re-derives power_index {fx.F1_POWER_INDEX_BOUNDARY}, "
        f"got {relocked['power_index']!r}"
    )
    assert relocked["computed_power"] == fx.F1_COMPUTED_POWER_BOUNDARY, (
        f"the re-lock re-derives computed_power {fx.F1_COMPUTED_POWER_BOUNDARY}, "
        f"got {relocked['computed_power']!r}"
    )
    assert relocked["treatment_population"] == f.EXPERIMENT_ARM_POPULATION, (
        "the audience-split lock re-copies planned_treatment_population into "
        f"treatment_population, got {relocked['treatment_population']!r}"
    )
    assert relocked["control_population"] == f.EXPERIMENT_ARM_POPULATION, (
        "the audience-split lock re-copies planned_control_population into "
        f"control_population, got {relocked['control_population']!r}"
    )
    assert rejected_again["status"] == "REJECTED", rejected_again["status"]
    assert rejected_again["redesign_count"] == 1, (
        "walking the cycle again does not itself move redesign_count"
    )

    second_loop = validate_success(
        api.release_cells(rejected["id"], users.EXPERIMENT_DESIGNER)
    )

    assert second_loop["status"] == "DRAFT", second_loop["status"]
    assert second_loop["redesign_count"] == 2, (
        f"the second loop reaches redesign_count 2, got {second_loop['redesign_count']!r}"
    )
    a.assert_draft_experiment_fields_cleared(second_loop)


def test_third_redesign_loop_refused_once_redesign_count_reaches_the_limit(api):
    """PRD §3.6: "From `REJECTED` it loops back to `DRAFT` for a redesign, but only
    while `redesign_count` is still below two — a third loop is refused with
    `ERR_REDESIGN_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/experiment_reject_redesign_cycle_bounded_by_max_redesigns
    """
    ctx, rejected = _rejected_audience_split_experiment(api)
    experiment_id = rejected["id"]
    observed_counts = [rejected["redesign_count"]]

    first_loop = validate_success(
        api.release_cells(experiment_id, users.EXPERIMENT_DESIGNER)
    )
    observed_counts.append(first_loop["redesign_count"])
    _relock_and_reject(api, experiment_id)
    second_loop = validate_success(
        api.release_cells(experiment_id, users.EXPERIMENT_DESIGNER)
    )
    observed_counts.append(second_loop["redesign_count"])
    _, third_reject = _relock_and_reject(api, experiment_id)
    assert third_reject["redesign_count"] == 2, third_reject["redesign_count"]

    refused = api.release_cells(experiment_id, users.EXPERIMENT_DESIGNER)

    validate_error(refused, ApiErrorId.ERR_REDESIGN_LIMIT_REACHED.value, 422)
    after = validate_success(
        api.get_experiment(experiment_id, users.EXPERIMENT_DESIGNER)
    )
    assert after["status"] == "REJECTED", (
        "the refused loop leaves the experiment where it was, got "
        f"{after['status']!r}"
    )
    assert after["redesign_count"] == 2, (
        f"redesign_count never exceeds two, got {after['redesign_count']!r}"
    )
    a.assert_version_unchanged(third_reject, after)
    observed_counts.append(after["redesign_count"])
    assert observed_counts == [0, 1, 2, 2], (
        f"redesign_count should walk 0, 1, 2, 2, got {observed_counts}"
    )


def test_release_cells_from_accepted_reaches_the_terminal_closed_state(api):
    """PRD §3.6: "It is available from `ACCEPTED` and from `REJECTED`; from
    anywhere else it is `ERR_EXPERIMENT_INVALID_STATE`."
    PRD §3.6: "From `ACCEPTED` the experiment lands on `CLOSED` and its `version`
    increments; that is the end of its life."
    PRD §3.6: "`CLOSED` is terminal; every action invoked against a closed
    experiment answers `ERR_EXPERIMENT_INVALID_STATE`, as does any action invoked
    from a state that has no such transition."

    Design: Difficulty/non_linear_state_machine/experiment_reject_redesign_cycle_bounded_by_max_redesigns
    """
    ctx = fx.experiment_on_published_market(api)
    accepted = fx.accepted_experiment(api, ctx, experiment=ctx["experiment"])
    assert accepted["status"] == "ACCEPTED", accepted["status"]

    closed = validate_success(
        api.release_cells(accepted["id"], users.EXPERIMENT_DESIGNER)
    )

    assert closed["status"] == "CLOSED", (
        "the very same endpoint that returns a REJECTED experiment to DRAFT "
        f"closes an ACCEPTED one, got {closed['status']!r}"
    )
    assert closed["redesign_count"] == 0, (
        "the accept arm consumes no redesign, got " f"{closed['redesign_count']!r}"
    )
    assert closed["version"] > accepted["version"], (
        "reaching CLOSED increments version"
    )
    assert closed["measured_lift_pct"] == fx.F1_DID_MEASURED_LIFT_PCT, (
        "the accept arm keeps the readout it accepted rather than clearing it"
    )

    again = api.release_cells(accepted["id"], users.EXPERIMENT_DESIGNER)

    validate_error(again, ApiErrorId.ERR_EXPERIMENT_INVALID_STATE.value, 409)
