"""Serialization tokens and the counters that have to agree with each other.

Two writes in this contract carry the version of a parent row as a precondition:
a spend observation carries the data window's version, and a calibration record
carries the model run's version. Both refuse a token that is one write behind,
both echo the post-write version so a client can chain writes without re-reading
the parent, and neither leaves anything behind when it refuses.

The third rule here is a counter agreement rather than a token: a market's
population aggregates are written by two different operations — creating a cell
and enlisting cells into an experiment's arms — and the two counters have to
reconcile against the cells themselves after both have run.

Every test builds its own state from scratch: the harness relaunches the API
against an empty database before each individual test.
"""

from typing import Dict, List

from test_helpers import (
    ApiClient,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as expect
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users


def _spend_body(
    window_id: str,
    channel_id: str,
    period: str,
    spend_cents: int,
    impressions: int,
    expected_version: int,
) -> Dict[str, object]:
    """One spend-observation body carrying an explicit window-version token."""
    return f.spend_observation_payload(
        window_id,
        channel_id,
        period,
        spend_cents,
        expected_version,
        impressions=impressions,
    )


def _window_of(api: ApiClient, window_id: str) -> Dict[str, object]:
    return validate_success(api.get_data_window(window_id, users.DATA_ENGINEER), 200)


def _record_ids(rows: List[Dict[str, object]]) -> List[object]:
    return [row["id"] for row in rows]


def test_spend_observation_stale_data_window_version_rejected(api: ApiClient) -> None:
    """PRD 2.7: "Filing a spend observation requires `expected_data_window_version` in the request body."
    PRD 2.7: "If that value does not equal the window's current `version`, the write is rejected with `ERR_STALE_DATA_WINDOW_VERSION` (HTTP 412) and nothing is persisted."
    PRD 2.7: "Every accepted spend-observation write increments the parent window's `version`, and the response echoes the post-write value in the observation's `data_window_version_after`, so a client filing a series of observations can chain its writes without re-reading the window between them."
    PRD 2.6: "A body that fails to parse, omits a required field, carries an enum value outside its declared set, carries a numeric value outside its declared range, or carries a date that is not an ISO 8601 UTC-midnight instant is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD 3.2: "The incumbent's `superseded_by_id` is set to the new row's identifier, and the new row's `is_restatement` becomes true."
    PRD 3.2: "Every accepted spend write recomputes the parent window's `spend_observation_count` over its non-superseded rows only, increments the window's `version`, and stamps the observation's `data_window_version_after` with the post-write value."

    Design: Corner/complexity_layers/spend_observation_stale_data_window_version_rejected
    """
    ctx = fx.market_with_channels(api)
    window = fx.create_data_window(api, ctx["market"]["id"])
    channel_id = ctx["a_search"]["id"]

    # The token the client last observed, before any observation exists.
    v0 = window["version"]
    assert v0 == fx.F1_WINDOW_VERSION_AFTER_CREATE, window

    first = validate_success(
        api.create_spend_observation(
            _spend_body(window["id"], channel_id, f.WINDOW_PERIODS[0], 400000, 4000, v0),
            users.DATA_ENGINEER,
        ),
        201,
    )
    v1 = first["data_window_version_after"]
    assert v1 == v0 + 1, first

    # A second write presenting the pre-write token is one write behind.
    validate_error(
        api.create_spend_observation(
            _spend_body(window["id"], channel_id, f.WINDOW_PERIODS[1], 600000, 6000, v0),
            users.DATA_ENGINEER,
        ),
        ApiErrorId.ERR_STALE_DATA_WINDOW_VERSION,
    )

    # The same body with the token omitted entirely is malformed: the token is
    # required on every write, not only on a restatement.
    validate_error(
        api.create_spend_observation(
            f.without(
                _spend_body(
                    window["id"], channel_id, f.WINDOW_PERIODS[1], 600000, 6000, v1
                ),
                "expected_data_window_version",
            ),
            users.DATA_ENGINEER,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    # Neither refusal persisted anything or moved the window.
    after_refusals = _window_of(api, window["id"])
    assert after_refusals["version"] == v1, after_refusals
    assert after_refusals["spend_observation_count"] == 1, after_refusals

    # The current token is accepted and the response hands back the next one.
    second = validate_success(
        api.create_spend_observation(
            _spend_body(window["id"], channel_id, f.WINDOW_PERIODS[1], 600000, 6000, v1),
            users.DATA_ENGINEER,
        ),
        201,
    )
    v2 = second["data_window_version_after"]
    assert v2 == v1 + 1, second
    assert second["is_restatement"] is False, second
    assert second["superseded_by_id"] is None, second
    chained = _window_of(api, window["id"])
    assert chained["version"] == v2, chained
    assert chained["spend_observation_count"] == 2, chained

    # A restatement of the first period supersedes the incumbent and is itself
    # serialized on the token the previous write handed back.
    restatement = validate_success(
        api.create_spend_observation(
            _spend_body(window["id"], channel_id, f.WINDOW_PERIODS[0], 450000, 4500, v2),
            users.DATA_ENGINEER,
        ),
        201,
    )
    v3 = restatement["data_window_version_after"]
    assert v3 == v2 + 1, restatement
    assert restatement["is_restatement"] is True, restatement

    incumbent = validate_success(
        api.get_spend_observation(first["id"], users.DATA_ENGINEER), 200
    )
    assert incumbent["superseded_by_id"] == restatement["id"], incumbent

    # The version moved on every accepted write, while the live count did not,
    # because a restatement replaces its incumbent rather than adding to it.
    final = _window_of(api, window["id"])
    assert final["version"] == v3, final
    assert final["spend_observation_count"] == 2, final

    # Exactly the three accepted writes exist, and no row for either refusal.
    rows, meta = validate_paginated(
        api.list_spend_observations(
            users.DATA_ENGINEER,
            {"data_window_id": window["id"], "include_superseded": "true"},
        )
    )
    assert meta["total_count"] == 3, meta
    assert sorted(_record_ids(rows)) == sorted(
        [first["id"], second["id"], restatement["id"]]
    ), rows


def test_calibration_record_stale_model_run_version_rejected(api: ApiClient) -> None:
    """PRD 2.7: "Filing a calibration record requires `expected_model_run_version` in the request body, likewise non-optional, carrying the `version` of the parent model run as the client last observed it."
    PRD 2.7: "A value that does not equal the run's current `version` is rejected with `ERR_STALE_MODEL_RUN_VERSION` (HTTP 412) and no record is created."
    PRD 2.7: "Every accepted calibration record increments the run's `version`, and the response echoes the post-write value in the record's `model_run_version_after` for the same chaining reason."
    PRD 3.7: "Any prior live record for the same run-and-channel pair has its `superseded` flag set to true, and superseded records are excluded from every downstream read — the recalibration step and every report see only the live record for a pair."
    PRD 3.7: "The run's `version` increments — and this is exactly the bump the optimistic-concurrency rule for calibration records observes, which is why two records filed for the same pair from the same read cannot both succeed."
    PRD 3.7: "The parent run's `calibration_status` moves to `PENDING_CALIBRATION`, which it does from `NOT_REQUIRED`, from `CALIBRATED`, from `STALE`, and from `PENDING_CALIBRATION` itself when a second channel's record arrives."

    Design: Corner/complexity_layers/calibration_record_stale_model_run_version_rejected
    """
    ctx = fx.experiment_on_published_market(api)
    experiment = fx.accepted_experiment(api, ctx, experiment=ctx["experiment"])
    assert experiment["status"] == "ACCEPTED", experiment["status"]
    ctx["experiment"] = experiment

    run_id = ctx["run"]["id"]
    channel_id = ctx["a_search"]["id"]

    # The token the client last observed on the run.
    rv0 = fx.run_version(api, run_id)

    first = validate_success(
        api.create_calibration_record(
            f.calibration_record_payload(run_id, channel_id, experiment["id"], rv0),
            users.MODELER,
        ),
        201,
    )
    assert first["calibration_multiplier"] == fx.F1_CALIBRATION_MULTIPLIER, first
    assert first["superseded"] is False, first
    assert first["model_run_version_after"] == rv0 + 1, first

    # A second record for the same pair from the same read presents a token the
    # first write already consumed.
    validate_error(
        api.create_calibration_record(
            f.calibration_record_payload(run_id, channel_id, experiment["id"], rv0),
            users.MODELER,
        ),
        ApiErrorId.ERR_STALE_MODEL_RUN_VERSION,
    )

    # The refused write created nothing and superseded nothing.
    rows, meta = validate_paginated(
        api.list_calibration_records(users.MODELER, {"model_run_id": run_id})
    )
    assert meta["total_count"] == 1, meta
    assert _record_ids(rows) == [first["id"]], rows
    assert expect.only(rows)["superseded"] is False, rows

    # Re-reading the run yields the token the first write left behind, and the
    # calibration dimension has moved on that same bump.
    run_after_first = validate_success(api.get_model_run(run_id, users.MODELER), 200)
    rv1 = run_after_first["version"]
    assert rv1 == rv0 + 1, run_after_first
    assert run_after_first["calibration_status"] == "PENDING_CALIBRATION", run_after_first

    second = validate_success(
        api.create_calibration_record(
            f.calibration_record_payload(run_id, channel_id, experiment["id"], rv1),
            users.MODELER,
        ),
        201,
    )
    assert second["superseded"] is False, second
    assert second["calibration_multiplier"] == fx.F1_CALIBRATION_MULTIPLIER, second
    assert second["model_run_version_after"] == rv1 + 1, second

    # The first record is now the superseded one, and only the second is live.
    superseded = validate_success(
        api.get_calibration_record(first["id"], users.MODELER), 200
    )
    assert superseded["superseded"] is True, superseded

    live_rows, live_meta = validate_paginated(
        api.list_calibration_records(
            users.MODELER, {"model_run_id": run_id, "superseded": "false"}
        )
    )
    assert live_meta["total_count"] == 1, live_meta
    assert _record_ids(live_rows) == [second["id"]], live_rows

    # The second record replaced the first without applying anything.
    run_after_second = validate_success(api.get_model_run(run_id, users.MODELER), 200)
    assert run_after_second["version"] == rv1 + 1, run_after_second
    assert run_after_second["calibration_status"] == "PENDING_CALIBRATION", (
        run_after_second
    )


def test_market_population_counters_reconcile_after_cell_create_and_assign(
    api: ApiClient,
) -> None:
    """PRD 3.1: "`celled_population` is the summed `population` of every geographic cell belonging to the market, regardless of assignment."
    PRD 3.1: "`held_out_population` is the summed `population` of only those cells whose `assignment_state` is `TREATMENT`, `CONTROL` or `WASHOUT`."
    PRD 3.1: "Alongside it, `held_out_population_pct` is reported as one hundred multiplied by `held_out_population`, divided by `total_population`, rounded half-up to two decimal places; this percentage is for human reporting only and is never the quantity a holdout-share rule compares against."
    PRD 3.1: "Adding a cell adds its population to the market's `celled_population` and bumps the market's `version`."
    PRD 3.1: "A new cell starts with `assignment_state` `UNASSIGNED`, a null `assigned_experiment_id` and a null `washout_until_date`."
    PRD 3.6: "On success, each cell named in `treatment_cell_ids` moves to `assignment_state` `TREATMENT` and each cell named in `control_cell_ids` moves to `CONTROL`, both recording the experiment in their `assigned_experiment_id`; each such cell adds its `population` to the market's `held_out_population`."
    PRD 3.6: "The experiment's `treatment_population` becomes the summed population of its treatment cells and its `control_population` the summed population of its control cells."
    PRD 3.6: "The market's `held_out_population` and `held_out_population_pct` are recomputed, the experiment moves to `CELLS_ASSIGNED`, and its `version` increments."

    Design: Corner/complexity_layers/market_population_counters_reconcile_after_cell_create_and_assign
    """
    ctx = fx.market_with_channels(api)
    market = ctx["market"]
    assert market["celled_population"] == 0, market
    assert market["held_out_population"] == 0, market
    assert market["held_out_population_pct"] == 0.00, market

    experiment = fx.locked_experiment(api, ctx, geo=True, planned_population=500_000)
    assert experiment["status"] == "DESIGN_LOCKED", experiment["status"]

    # Creating a cell moves the celled sum and the market's own version, and
    # holds nothing out.
    before_first = validate_success(api.get_market(market["id"], users.AUDITOR), 200)
    first_cell = fx.create_geo_cell(api, market["id"], "GC01", 100_000)
    assert first_cell["assignment_state"] == "UNASSIGNED", first_cell
    assert first_cell["assigned_experiment_id"] is None, first_cell

    after_first = validate_success(api.get_market(market["id"], users.AUDITOR), 200)
    assert after_first["celled_population"] == 100_000, after_first
    assert after_first["held_out_population"] == 0, after_first
    assert after_first["held_out_population_pct"] == 0.00, after_first
    assert after_first["version"] == before_first["version"] + 1, after_first

    second_cell = fx.create_geo_cell(api, market["id"], "GC02", 150_000)
    after_second = validate_success(api.get_market(market["id"], users.AUDITOR), 200)
    assert after_second["celled_population"] == 250_000, after_second
    assert after_second["held_out_population"] == 0, after_second
    assert after_second["held_out_population_pct"] == 0.00, after_second
    assert after_second["version"] == after_first["version"] + 1, after_second
    expect.assert_celled_population(after_second, [first_cell, second_cell])
    expect.assert_holdout_conservation(after_second, [first_cell, second_cell])

    # Enlisting the cells into the arms is the event that holds population out.
    assigned = validate_success(
        api.assign_cells(
            experiment["id"],
            f.assign_cells_payload([first_cell["id"]], [second_cell["id"]]),
            users.EXPERIMENT_DESIGNER,
        ),
        200,
    )
    assert assigned["status"] == "CELLS_ASSIGNED", assigned["status"]
    assert assigned["treatment_population"] == 100_000, assigned
    assert assigned["control_population"] == 150_000, assigned
    assert assigned["version"] == experiment["version"] + 1, assigned

    # The two sums are reconciled independently over the same child rows: the
    # celled sum is unmoved while the held-out sum has caught up with it.
    final_market = validate_success(api.get_market(market["id"], users.AUDITOR), 200)
    assert final_market["celled_population"] == 250_000, final_market
    assert final_market["held_out_population"] == 250_000, final_market
    assert final_market["held_out_population_pct"] == 2.50, final_market

    cells, cells_meta = validate_paginated(
        api.list_geo_cells(users.AUDITOR, {"market_id": market["id"]})
    )
    assert cells_meta["total_count"] == 2, cells_meta
    expect.assert_celled_population(final_market, cells)
    expect.assert_holdout_conservation(final_market, cells)
    states = {row["cell_code"]: row["assignment_state"] for row in cells}
    assert states == {"GC01": "TREATMENT", "GC02": "CONTROL"}, cells
    for row in cells:
        assert row["assigned_experiment_id"] == experiment["id"], row
