"""Endpoint behaviour on the marketing-mix modelling service.

Each test here exercises one endpoint at the point where its declared behaviour
is easiest to get subtly wrong — a partial update that must leave its siblings
alone, a bulk write that must be all-or-nothing, a cross-aggregate link that must
resolve both of its sides, a gate that opens and closes with a status dimension,
and a recomputation whose empty case is a success rather than an error.

The harness relaunches the API against an empty database before every test, so
each test builds its whole precondition chain through the declared endpoints.
"""

from decimal import Decimal
from typing import Any, Dict

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assertions as checks,
    factories as f,
    fixtures as fx,
    test_users as users,
    validate_error,
    validate_paginated,
    validate_success,
)


# A well-formed identifier that names nothing in the store.
ABSENT_ID = "00000000-0000-4000-8000-000000000000"


def _num(value: Any) -> Decimal:
    """A decimal answer compared exactly, whatever JSON type carries it."""
    return Decimal(str(value))


def _platform_lines(ctx: Dict[str, Any]) -> Any:
    """One platform line per channel the run decomposed."""
    return [
        f.platform_line(
            ctx["a_search"]["id"], f.PLATFORM_A_SEARCH_MATERIAL_CENTS
        ),
        f.platform_line(
            ctx["b_social"]["id"], f.PLATFORM_B_SOCIAL_MATERIAL_CENTS
        ),
    ]


def test_patching_a_channel_changes_only_the_fields_the_body_supplies(
    api: ApiClient,
) -> None:
    """A partial revision moves the named fields, the counter, and nothing else.

    "A `DataEngineer` may revise a channel later, supplying any subset of
    `status`, `adstock_decay_rate`, `adstock_max_lag_periods`,
    `saturation_half_point_cents`, `response_ceiling_units`, `min_spend_cents` and
    `max_spend_cents`." And: "Such a revision is never retroactive — it bumps the
    channel's `version` and changes what future fits and future optimizations
    read, but no model run that has already been fitted is altered by it."

    The counter itself is specified as: "`version` is an integer that starts at 1
    when the row is created and increments by one on every mutation of that row,
    including mutations caused indirectly by a cascade fired from another
    resource."

    Design: Corner/endpoints/patch_media_channel_updates_only_the_supplied_fields
    """
    fx.set_clock(api)
    market = fx.create_market(api)
    created = fx.create_channel(api, f.a_search_payload(market["id"]))
    assert created["version"] == 1

    first = validate_success(
        api.patch_media_channel(
            created["id"],
            {"min_spend_cents": 300000, "max_spend_cents": 2500000},
            users.DATA_ENGINEER,
        )
    )
    checks.assert_media_channel(first)
    assert first["min_spend_cents"] == 300000
    assert first["max_spend_cents"] == 2500000
    assert first["version"] == 2
    # Every field the body did not name is left where the create put it.
    assert _num(first["adstock_decay_rate"]) == Decimal("0.50")
    assert first["adstock_max_lag_periods"] == 2
    assert first["saturation_half_point_cents"] == 200000
    assert first["response_ceiling_units"] == 1200
    assert first["status"] == "ACTIVE"
    assert first["created_at"] == created["created_at"]
    assert first["channel_code"] == created["channel_code"]
    assert first["market_id"] == created["market_id"]

    second = validate_success(
        api.patch_media_channel(
            created["id"], {"status": "PAUSED"}, users.DATA_ENGINEER
        )
    )
    assert second["status"] == "PAUSED"
    assert second["version"] == 3
    assert second["min_spend_cents"] == 300000
    assert second["max_spend_cents"] == 2500000
    assert second["channel_code"] == created["channel_code"]
    assert second["market_id"] == created["market_id"]

    read_back = validate_success(api.get_media_channel(created["id"], users.AUDITOR))
    assert read_back["min_spend_cents"] == 300000
    assert read_back["max_spend_cents"] == 2500000
    assert read_back["status"] == "PAUSED"
    assert read_back["version"] == 3
    assert read_back["market_id"] == market["id"]
    assert read_back["channel_code"] == "A_SEARCH"


def test_assigning_cells_applies_the_whole_list_or_none_of_it(
    api: ApiClient,
) -> None:
    """One occupied cell in the body leaves the free cell in the same body alone.

    "Every listed cell must currently be `UNASSIGNED`; a cell already sitting in
    `TREATMENT`, `CONTROL` or `WASHOUT` is `ERR_GEO_CELL_UNAVAILABLE`, and that
    availability check outranks both the design-type check and the
    market-membership check, so a request that names an occupied cell on an
    `AUDIENCE_SPLIT` experiment answers `ERR_GEO_CELL_UNAVAILABLE`."

    The successful shape is: "On success, each cell named in `treatment_cell_ids`
    moves to `assignment_state` `TREATMENT` and each cell named in
    `control_cell_ids` moves to `CONTROL`, both recording the experiment in their
    `assigned_experiment_id`; each such cell adds its `population` to the market's
    `held_out_population`." And: "The experiment's `treatment_population` becomes
    the summed population of its treatment cells and its `control_population` the
    summed population of its control cells."

    Design: Corner/endpoints/assign_cells_bulk_rejects_the_whole_list_on_one_unavailable_cell
    """
    ctx = fx.market_with_channels(api)
    cells = fx.create_geo_cells(
        api,
        ctx["market"]["id"],
        [("GC01", 100000), ("GC02", 100000), ("GC03", 100000), ("GC04", 100000)],
    )
    incumbent = fx.locked_experiment(
        api, ctx, geo=True, planned_population=f.EXPERIMENT_ARM_POPULATION
    )
    incumbent = validate_success(
        api.assign_cells(
            incumbent["id"],
            f.assign_cells_payload([cells[0]["id"]], [cells[1]["id"]]),
            users.EXPERIMENT_DESIGNER,
        )
    )
    candidate = fx.locked_experiment(
        api,
        ctx,
        experiment=fx.create_experiment(
            api,
            ctx,
            channel_id=ctx["b_social"]["id"],
            geo=True,
            planned_population=f.EXPERIMENT_ARM_POPULATION,
        ),
    )

    # GC03 is free, GC02 is not; the two travel in one body.
    validate_error(
        api.assign_cells(
            candidate["id"],
            f.assign_cells_payload([cells[2]["id"]], [cells[1]["id"]]),
            users.EXPERIMENT_DESIGNER,
        ),
        ApiErrorId.ERR_GEO_CELL_UNAVAILABLE,
        409,
    )

    free_cell = validate_success(
        api.get_geo_cell(cells[2]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert free_cell["assignment_state"] == "UNASSIGNED"
    assert free_cell["assigned_experiment_id"] is None
    occupied = validate_success(
        api.get_geo_cell(cells[1]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert occupied["assignment_state"] == "CONTROL"
    assert occupied["assigned_experiment_id"] == incumbent["id"]

    market = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert market["held_out_population"] == 200000
    assert _num(market["held_out_population_pct"]) == Decimal("2.00")
    refused = validate_success(
        api.get_experiment(candidate["id"], users.EXPERIMENT_DESIGNER)
    )
    assert refused["status"] == "DESIGN_LOCKED"
    assert refused["treatment_population"] == 0
    assert refused["control_population"] == 0

    assigned = validate_success(
        api.assign_cells(
            candidate["id"],
            f.assign_cells_payload([cells[2]["id"]], [cells[3]["id"]]),
            users.EXPERIMENT_DESIGNER,
        )
    )
    assert assigned["status"] == "CELLS_ASSIGNED"
    assert assigned["treatment_population"] == 100000
    assert assigned["control_population"] == 100000

    market = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert market["held_out_population"] == 400000
    assert _num(market["held_out_population_pct"]) == Decimal("4.00")
    treatment = validate_success(
        api.get_geo_cell(cells[2]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert treatment["assignment_state"] == "TREATMENT"
    assert treatment["assigned_experiment_id"] == candidate["id"]
    control = validate_success(
        api.get_geo_cell(cells[3]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert control["assignment_state"] == "CONTROL"
    assert control["assigned_experiment_id"] == candidate["id"]


def test_a_calibration_record_needs_both_sides_of_the_link_to_exist(
    api: ApiClient,
) -> None:
    """The link resolves its experiment before it derives anything.

    "Foreign keys carried in a request body are resolved after the body's shape
    has been validated, and an unresolvable body reference yields the same
    collection-specific 404 — a `market_id` that names nothing gives
    `ERR_MARKET_NOT_FOUND`, a `channel_id`, an element of `included_channel_ids`
    or a channel named inside a platform line gives `ERR_MEDIA_CHANNEL_NOT_FOUND`,
    an element of `treatment_cell_ids` or `control_cell_ids` gives
    `ERR_GEO_CELL_NOT_FOUND`, a `data_window_id` gives
    `ERR_DATA_WINDOW_NOT_FOUND`, a `model_run_id` gives
    `ERR_MODEL_RUN_NOT_FOUND`, an `experiment_id` gives
    `ERR_EXPERIMENT_NOT_FOUND`, and a `budget_scenario_id` gives
    `ERR_BUDGET_SCENARIO_NOT_FOUND`."

    Once both sides resolve, the record derives its correction: "The model's own
    view of the same quantity, `model_implied_lift_pct`, is computed from the
    run's current decomposition row for that channel — the one whose `is_current`
    is true — as one hundred multiplied by that row's `contribution_units`,
    divided by the difference between the run's `modeled_sales_units` and that
    same `contribution_units`, rounded half-up to four decimal places."
    Then: "`calibration_multiplier` is then `experiment_lift_pct` divided by
    `model_implied_lift_pct`, rounded half-up to four decimal places, and
    constrained to lie within the closed range from 0.25 to 4.00." And: "From the
    multiplier the record derives `bias_direction`: `OVER_ATTRIBUTED` when the
    multiplier is strictly below 0.95, `UNDER_ATTRIBUTED` when it is strictly
    above 1.05, and `ALIGNED` when it sits anywhere in the closed band between
    those two bounds inclusive."

    The write also moves exactly one dimension of its parent: "The parent run's
    `calibration_status` moves to `PENDING_CALIBRATION`, which it does from
    `NOT_REQUIRED`, from `CALIBRATED`, from `STALE`, and from
    `PENDING_CALIBRATION` itself when a second channel's record arrives." And:
    "The post-write value is echoed on the record as `model_run_version_after`,
    the acting operator is captured in `created_by_user_id`, and the market's
    `data_posture` is recomputed, since a published run whose calibration has
    moved may change what the market permits."

    Design: Corner/endpoints/calibration_record_links_experiment_and_model_run
    """
    ctx = fx.experiment_on_published_market(api)
    fx.accepted_experiment(api, ctx, experiment=ctx["experiment"])
    run_id = ctx["run"]["id"]
    channel_id = ctx["a_search"]["id"]
    experiment_id = ctx["experiment"]["id"]

    before = validate_success(api.get_model_run(run_id, users.MODELER))
    assert before["calibration_status"] == "NOT_REQUIRED"
    version_before = before["version"]

    validate_error(
        api.create_calibration_record(
            f.calibration_record_payload(
                run_id, channel_id, ABSENT_ID, version_before
            ),
            users.MODELER,
        ),
        ApiErrorId.ERR_EXPERIMENT_NOT_FOUND,
        404,
    )
    untouched = validate_success(api.get_model_run(run_id, users.MODELER))
    assert untouched["calibration_status"] == "NOT_REQUIRED"
    assert untouched["version"] == version_before

    record = validate_success(
        api.create_calibration_record(
            f.calibration_record_payload(
                run_id, channel_id, experiment_id, version_before
            ),
            users.MODELER,
        ),
        201,
    )
    checks.assert_calibration_record(record)
    assert record["model_run_id"] == run_id
    assert record["channel_id"] == channel_id
    assert record["experiment_id"] == experiment_id
    assert _num(record["model_implied_lift_pct"]) == Decimal("18.8835")
    assert _num(record["experiment_lift_pct"]) == Decimal("10.00")
    assert _num(record["calibration_multiplier"]) == Decimal("0.5296")
    assert record["bias_direction"] == "OVER_ATTRIBUTED"
    assert record["superseded"] is False
    assert record["created_by_user_id"] == users.MODELER_ID
    assert record["model_run_version_after"] == version_before + 1

    after = validate_success(api.get_model_run(run_id, users.MODELER))
    assert after["calibration_status"] == "PENDING_CALIBRATION"
    assert after["fit_status"] == "FITTED"
    assert after["publication_status"] == "PUBLISHED"

    for query in ({"experiment_id": experiment_id}, {"model_run_id": run_id}):
        rows, meta = validate_paginated(
            api.list_calibration_records(users.MODELER, query)
        )
        assert meta["total_count"] == 1
        assert rows[0]["id"] == record["id"]


def test_a_report_waits_for_a_live_calibration_and_then_reports_on_it(
    api: ApiClient,
) -> None:
    """A stale correction blocks the report until a fresh record replaces it.

    "Filing is additionally gated on the market's `data_posture` not being
    `FROZEN`, or `ERR_MARKET_POSTURE_BLOCKED`, and on the run's
    `calibration_status` being `NOT_REQUIRED` or `CALIBRATED` — a report against a
    run whose calibration is `PENDING_CALIBRATION` or `STALE` is refused with
    `ERR_CALIBRATION_STALE`." Recalibration cannot clear that state directly:
    "It requires `fit_status` to be `FITTED`, or `ERR_MODEL_RUN_INVALID_STATE`,
    and requires `calibration_status` to be exactly `PENDING_CALIBRATION`; a run
    whose calibration is `NOT_REQUIRED`, already `CALIBRATED`, or `STALE` is
    refused with `ERR_CALIBRATION_NOT_PENDING`."

    A fresh record is the way out, and it retires its predecessor: "Any prior
    live record for the same run-and-channel pair has its `superseded` flag set to
    true, and superseded records are excluded from every downstream read — the
    recalibration step and every report see only the live record for a pair."
    Applying it: "On success `calibration_status` becomes `CALIBRATED`, the run's
    `version` increments, and the market's `data_posture` is recomputed — a
    published run that has just become `CALIBRATED` is often what restores a
    market from `RESTRICTED` to `OPEN`."

    The report then reads the corrected figures: "When the run's
    `calibration_status` is `CALIBRATED` the `basis` is `CALIBRATED` and each
    channel's model figure is its `calibrated_contribution_revenue_cents`; in
    every other admissible case the `basis` is `RAW` and the model figure is its
    `contribution_revenue_cents`." One of the two channels was never corrected:
    "For each channel that has no live record, both calibrated figures pass
    through unchanged: `calibrated_contribution_units` equals `contribution_units`
    and `calibrated_contribution_revenue_cents` equals
    `contribution_revenue_cents`." And the totals: "Three totals are then summed
    across the lines: `platform_reported_revenue_cents` from the platform figures,
    `model_attributed_revenue_cents` from the model figures, and
    `total_variance_cents` from the per-line variances." And: "A new report is
    created in `status` `CURRENT`."

    Design: Corner/endpoints/reconciliation_report_conditional_on_live_calibration
    """
    ctx = fx.experiment_on_published_market(api)
    fx.accepted_experiment(api, ctx, experiment=ctx["experiment"])
    run_id = ctx["run"]["id"]
    first_record = fx.file_calibration_record(api, ctx)
    validate_success(api.recalibrate_model_run(run_id, users.MODELER))

    # A second readout on the other channel is accepted, which makes the
    # correction the published run is carrying stale.
    second = fx.create_experiment(api, ctx, channel_id=ctx["b_social"]["id"])
    second = validate_success(
        api.lock_design(second["id"], users.EXPERIMENT_DESIGNER)
    )
    second = validate_success(
        api.start_experiment(second["id"], users.EXPERIMENT_DESIGNER)
    )
    second = validate_success(
        api.read_out_experiment(
            second["id"], f.read_out_payload(), users.EXPERIMENT_DESIGNER
        )
    )
    second = validate_success(
        api.accept_experiment(second["id"], users.ANALYTICS_LEAD)
    )
    assert second["status"] == "ACCEPTED"

    stale = validate_success(api.get_model_run(run_id, users.MODELER))
    assert stale["calibration_status"] == "STALE"

    report_body = f.reconciliation_report_payload(run_id, _platform_lines(ctx))
    validate_error(
        api.create_reconciliation_report(report_body, users.ANALYTICS_LEAD),
        ApiErrorId.ERR_CALIBRATION_STALE,
        409,
    )
    validate_error(
        api.recalibrate_model_run(run_id, users.MODELER),
        ApiErrorId.ERR_CALIBRATION_NOT_PENDING,
        409,
    )

    replacement = fx.file_calibration_record(api, ctx)
    assert _num(replacement["calibration_multiplier"]) == Decimal("0.5296")
    assert replacement["superseded"] is False
    retired = validate_success(
        api.get_calibration_record(first_record["id"], users.MODELER)
    )
    assert retired["superseded"] is True
    pending = validate_success(api.get_model_run(run_id, users.MODELER))
    assert pending["calibration_status"] == "PENDING_CALIBRATION"

    recalibrated = validate_success(
        api.recalibrate_model_run(run_id, users.MODELER)
    )
    assert recalibrated["calibration_status"] == "CALIBRATED"
    assert _num(recalibrated["baseline_sales_units"]) == Decimal("19050.9090")

    report = validate_success(
        api.create_reconciliation_report(report_body, users.ANALYTICS_LEAD), 201
    )
    checks.assert_reconciliation_report(report)
    assert report["basis"] == "CALIBRATED"
    assert report["status"] == "CURRENT"
    assert report["model_attributed_revenue_cents"] == 19848131
    assert report["platform_reported_revenue_cents"] == 32756000

    rows, meta = validate_paginated(
        api.list_reconciliation_reports(
            users.ANALYTICS_LEAD, {"model_run_id": run_id}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == report["id"]


def test_a_sweep_with_nothing_to_release_succeeds_and_changes_nothing(
    api: ApiClient,
) -> None:
    """The sweep's empty case is a successful no-op, not a refusal.

    "It examines every cell of the market in `WASHOUT` and, for each one whose
    quarantine has elapsed — that is, whose `washout_until_date` is at or before
    the current logical clock — sets `assignment_state` back to `UNASSIGNED`,
    clears `assigned_experiment_id` to null, clears `washout_until_date` to null,
    and subtracts that cell's `population` from the market's
    `held_out_population`." And: "Cells whose quarantine has not yet elapsed are
    skipped silently: they are left exactly as they were and their presence is not
    an error, so one sweep call routinely applies to some cells and not others."

    Every cell of the market below sits in `TREATMENT` or `CONTROL` rather than in
    `WASHOUT`, so the sweep's candidate set is empty.

    Design: Corner/endpoints/washout_sweep_with_no_washout_cells_is_a_noop
    """
    ctx = fx.market_with_channels(api)
    cells = fx.create_geo_cells(
        api, ctx["market"]["id"], [("GC01", 100000), ("GC02", 100000)]
    )
    experiment = fx.locked_experiment(
        api, ctx, geo=True, planned_population=f.EXPERIMENT_ARM_POPULATION
    )
    experiment = validate_success(
        api.assign_cells(
            experiment["id"],
            f.assign_cells_payload([cells[0]["id"]], [cells[1]["id"]]),
            users.EXPERIMENT_DESIGNER,
        )
    )

    swept = validate_success(
        api.washout_sweep(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert swept["held_out_population"] == 200000
    assert _num(swept["held_out_population_pct"]) == Decimal("2.00")

    treatment = validate_success(
        api.get_geo_cell(cells[0]["id"], users.EXPERIMENT_DESIGNER)
    )
    checks.assert_geo_cell(treatment)
    assert treatment["assignment_state"] == "TREATMENT"
    assert treatment["assigned_experiment_id"] == experiment["id"]
    assert treatment["washout_until_date"] is None
    control = validate_success(
        api.get_geo_cell(cells[1]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert control["assignment_state"] == "CONTROL"
    assert control["assigned_experiment_id"] == experiment["id"]

    for state in ("UNASSIGNED", "WASHOUT"):
        _, meta = validate_paginated(
            api.list_geo_cells(
                users.EXPERIMENT_DESIGNER,
                {"market_id": ctx["market"]["id"], "assignment_state": state},
            )
        )
        assert meta["total_count"] == 0, state

    still_assigned = validate_success(
        api.get_experiment(experiment["id"], users.EXPERIMENT_DESIGNER)
    )
    assert still_assigned["status"] == "CELLS_ASSIGNED"
