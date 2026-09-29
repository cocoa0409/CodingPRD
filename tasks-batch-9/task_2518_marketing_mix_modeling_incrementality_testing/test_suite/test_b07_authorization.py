"""Who may do what: the six roles, the identity gate and the two duty splits.

Three separate gates decide whether a request is allowed to run at all, and this
module keeps them apart. The identity gate asks only whether the two headers are
present and non-empty. The role gate asks whether the role named in the header is
listed for the endpoint, and the endpoint table is exhaustive, so a role outside
the list is refused before any state or posture is consulted. The duty gate is
different in kind: it compares the acting operator identifier against a value
stored on the row when it was set up, so the same human wearing a second role is
still refused while a different human under the same role is allowed.

Every test builds its own state from scratch: the harness relaunches the API
against an empty database before each individual test.
"""

from typing import Callable, Dict, List, Tuple

import pytest

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
from test_helpers.constants import (
    ROLE_ANALYTICS_LEAD,
    ROLE_AUDITOR,
    ROLE_BRAND_PLANNER,
    ROLE_DATA_ENGINEER,
    ROLE_EXPERIMENT_DESIGNER,
    ROLE_MODELER,
)

# The five identity header shapes that carry no usable operator or no usable
# role: absent entirely, one of the two missing, or one of the two empty.
_REJECTED_IDENTITIES: List[Tuple[str, Dict[str, str]]] = [
    ("no_headers", users.NO_HEADERS),
    ("missing_user_id", users.MISSING_USER_ID),
    ("missing_role", users.MISSING_ROLE),
    ("empty_user_id", users.EMPTY_USER_ID),
    ("empty_role", users.EMPTY_ROLE),
]


def _market_count(api: ApiClient) -> int:
    """How many markets exist, read back through the list endpoint."""
    _, meta = validate_paginated(api.list_markets(users.AUDITOR))
    return meta["total_count"]


def _data_engineer_exclusive_operations(api: ApiClient) -> None:
    """Register a market, open a training window on it and seal that window."""
    fx.set_clock(api)
    market = validate_success(
        api.create_market(f.market_payload(), users.DATA_ENGINEER), 201
    )
    window = validate_success(
        api.create_data_window(
            f.data_window_payload(market["id"]), users.DATA_ENGINEER
        ),
        201,
    )
    fx.set_clock(api, fx.CLOCK_WINDOW_ELAPSED)
    fx.file_sales_rows(api, window["id"])
    sealed = validate_success(
        api.seal_data_window(window["id"], users.DATA_ENGINEER), 200
    )
    assert sealed["status"] == "SEALED", sealed["status"]


def _modeler_exclusive_operations(api: ApiClient) -> None:
    """Specify a run over the sealed window and fit it."""
    ctx = fx.sealed_window(api)
    run = validate_success(
        api.create_model_run(
            f.model_run_payload(
                ctx["market"]["id"], ctx["window"]["id"], ctx["channel_ids"]
            ),
            users.MODELER,
        ),
        201,
    )
    assert run["fit_status"] == "PENDING", run["fit_status"]
    fitted = validate_success(api.fit_model_run(run["id"], users.MODELER), 200)
    assert fitted["fit_status"] == "FITTED", fitted["fit_status"]
    assert fitted["fitted_by_user_id"] == users.MODELER_ID, fitted


def _experiment_designer_exclusive_operations(api: ApiClient) -> None:
    """Draft an experiment and lock its design."""
    ctx = fx.market_with_channels(api)
    experiment = validate_success(
        api.create_experiment(
            f.experiment_payload(ctx["market"]["id"], ctx["a_search"]["id"]),
            users.EXPERIMENT_DESIGNER,
        ),
        201,
    )
    assert experiment["designed_by_user_id"] == users.EXPERIMENT_DESIGNER_ID, experiment
    locked = validate_success(
        api.lock_design(experiment["id"], users.EXPERIMENT_DESIGNER), 200
    )
    assert locked["status"] == "DESIGN_LOCKED", locked["status"]


def _analytics_lead_exclusive_operations(api: ApiClient) -> None:
    """Publish the validated run — the decision no modelling role may take."""
    ctx = fx.validated_run(api)
    published = validate_success(
        api.publish_model_run(
            ctx["run"]["id"], users.ANALYTICS_LEAD, f.publish_payload()
        ),
        200,
    )
    assert published["publication_status"] == "PUBLISHED", published
    assert published["published_by_user_id"] == users.ANALYTICS_LEAD_ID, published


def _brand_planner_exclusive_operations(api: ApiClient) -> None:
    """Open a scenario, enrol both channels and run the optimizer."""
    ctx = fx.scenario_with_allocations(api)
    assert ctx["scenario"]["created_by_user_id"] == users.BRAND_PLANNER_ID, ctx["scenario"]
    optimized = validate_success(
        api.optimize_budget_scenario(ctx["scenario"]["id"], users.BRAND_PLANNER), 200
    )
    assert optimized["status"] == "OPTIMIZED", optimized["status"]


def _auditor_shared_operations(api: ApiClient) -> None:
    """The Auditor holds no exclusive operation at all; it reads."""
    fx.set_clock(api)
    market = fx.create_market(api)
    stored = validate_success(api.get_market(market["id"], users.AUDITOR), 200)
    assert stored["id"] == market["id"], stored["id"]
    rows, meta = validate_paginated(api.list_markets(users.AUDITOR))
    assert meta["total_count"] == 1, meta
    assert [row["id"] for row in rows] == [market["id"]], rows


_EXCLUSIVE_OPERATIONS: Dict[str, Callable[[ApiClient], None]] = {
    ROLE_DATA_ENGINEER: _data_engineer_exclusive_operations,
    ROLE_MODELER: _modeler_exclusive_operations,
    ROLE_EXPERIMENT_DESIGNER: _experiment_designer_exclusive_operations,
    ROLE_ANALYTICS_LEAD: _analytics_lead_exclusive_operations,
    ROLE_BRAND_PLANNER: _brand_planner_exclusive_operations,
    ROLE_AUDITOR: _auditor_shared_operations,
}


@pytest.mark.parametrize("role", sorted(_EXCLUSIVE_OPERATIONS), ids=sorted(_EXCLUSIVE_OPERATIONS))
def test_each_role_performs_its_own_exclusive_operations(
    api: ApiClient, role: str
) -> None:
    """PRD 2.1: "A `DataEngineer` owns the data-collection surface: registering markets, declaring media channels and revising their curve parameters, adding geographic cells, opening training windows, sealing and reopening them, and filing spend and sales observations."
    PRD 2.1: "A `Modeler` specifies model runs, fits them, validates them against their holdout, files calibration records and applies those records through recalibration; a `Modeler` cannot publish a run — publication is a decision, not a modelling step — and cannot touch source data."
    PRD 2.1: "An `ExperimentDesigner` drafts experiments, locks their designs, enlists geographic cells into arms, starts them in market, posts their read-outs, releases their cells, and runs the market washout sweep; an `ExperimentDesigner` cannot decide the outcome of a readout."
    PRD 2.1: "An `AnalyticsLead` is the sole decision authority: publishing model runs, accepting or rejecting experiment readouts, approving budget scenarios, and filing reconciliation reports."
    PRD 2.1: "A `BrandPlanner` builds budget scenarios, enrols channels into them with baseline spend, runs the optimizer and reverts an optimization, but can never approve a scenario — not even one another planner created."
    PRD 2.1: "An `Auditor` is strictly read-only: it may read every collection, including superseded observations and stale reports, and may perform no mutation whatsoever, not even advancing the logical clock."
    PRD 2.1: "All six roles may issue every read operation under `/mmm`. The five non-`Auditor` roles may also set the logical clock."

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
    """
    _EXCLUSIVE_OPERATIONS[role](api)


def test_five_role_relay_records_a_different_operator_on_each_decision(
    api: ApiClient,
) -> None:
    """PRD 2.1: "The server records it on rows where an audit trail matters — as `fitted_by_user_id` and `published_by_user_id` on a model run, as `designed_by_user_id` and `decided_by_user_id` on an experiment, and as `created_by_user_id` and `approved_by_user_id` on a budget scenario, and as `created_by_user_id` on a calibration record — but it never compares `X-User-ID` to any entity's `id`, and no resource is "owned" by an operator for access-control purposes."
    PRD 2.1: "A `Modeler` specifies model runs, fits them, validates them against their holdout, files calibration records and applies those records through recalibration; a `Modeler` cannot publish a run — publication is a decision, not a modelling step — and cannot touch source data."
    PRD 2.1: "An `AnalyticsLead` is the sole decision authority: publishing model runs, accepting or rejecting experiment readouts, approving budget scenarios, and filing reconciliation reports."
    PRD 2.1: "An `Auditor` is strictly read-only: it may read every collection, including superseded observations and stale reports, and may perform no mutation whatsoever, not even advancing the logical clock."
    PRD 3.6: "The draft is created in `DRAFT` with `redesign_count` 0 and with the acting operator captured in `designed_by_user_id` — the comparand every later decision on this experiment is measured against."
    PRD 3.8: "A newly created scenario is in `DRAFT` with `reallocation_fee_cents`, `allocated_total_cents`, `unallocated_cents` and `shifted_total_cents` all at 0, and with the acting operator captured in `created_by_user_id` as the approval comparand."

    Design: Corner/rbac/each_role_performs_its_own_exclusive_operations
    """
    # Every data-collection write of the chain belongs to one DataEngineer.
    ctx = fx.sealed_window(api)
    assert ctx["window"]["status"] == "SEALED", ctx["window"]["status"]

    # The Modeler declares, fits and backtests; it never publishes.
    run = fx.create_run(api, ctx)
    run = validate_success(api.fit_model_run(run["id"], users.MODELER), 200)
    run = validate_success(api.validate_model_run(run["id"], users.MODELER), 200)
    assert run["validation_status"] == "HOLDOUT_PASSED", run["validation_status"]

    # The AnalyticsLead publishes — a decision, not a modelling step.
    run = validate_success(
        api.publish_model_run(run["id"], users.ANALYTICS_LEAD, f.publish_payload()), 200
    )
    ctx["run"] = run

    # The ExperimentDesigner drafts and locks; the decision arm stays untouched.
    experiment = fx.create_experiment(api, ctx)
    experiment = validate_success(
        api.lock_design(experiment["id"], users.EXPERIMENT_DESIGNER), 200
    )

    # The BrandPlanner opens the plan, enrols the channels and optimizes.
    scenario = fx.create_scenario(api, ctx)
    fx.add_allocation(
        api, scenario["id"], ctx["a_search"]["id"], f.BASELINE_A_SEARCH_CENTS
    )
    fx.add_allocation(
        api, scenario["id"], ctx["b_social"]["id"], f.BASELINE_B_SOCIAL_CENTS
    )
    scenario = validate_success(
        api.optimize_budget_scenario(scenario["id"], users.BRAND_PLANNER), 200
    )

    # Two different operators are recorded on the same model-run row.
    stored_run = validate_success(api.get_model_run(run["id"], users.AUDITOR), 200)
    assert stored_run["fitted_by_user_id"] == users.MODELER_ID, stored_run
    assert stored_run["published_by_user_id"] == users.ANALYTICS_LEAD_ID, stored_run
    assert stored_run["fitted_by_user_id"] != stored_run["published_by_user_id"], stored_run
    assert stored_run["publication_status"] == "PUBLISHED", stored_run

    stored_experiment = validate_success(
        api.get_experiment(experiment["id"], users.AUDITOR), 200
    )
    assert stored_experiment["designed_by_user_id"] == users.EXPERIMENT_DESIGNER_ID, (
        stored_experiment
    )
    assert stored_experiment["decided_by_user_id"] is None, stored_experiment

    stored_scenario = validate_success(
        api.get_budget_scenario(scenario["id"], users.AUDITOR), 200
    )
    assert stored_scenario["created_by_user_id"] == users.BRAND_PLANNER_ID, stored_scenario
    assert stored_scenario["approved_by_user_id"] is None, stored_scenario
    assert stored_scenario["status"] == "OPTIMIZED", stored_scenario["status"]

    # Read-only means every row, not fewer rows: the Auditor sees the whole
    # observation history including the eight spend writes.
    published_rows, published_meta = validate_paginated(
        api.list_model_runs(
            users.AUDITOR,
            {"market_id": ctx["market"]["id"], "publication_status": "PUBLISHED"},
        )
    )
    assert published_meta["total_count"] == 1, published_meta
    assert [row["id"] for row in published_rows] == [run["id"]], published_rows

    _, spend_meta = validate_paginated(
        api.list_spend_observations(
            users.AUDITOR,
            {"data_window_id": ctx["window"]["id"], "include_superseded": "true"},
        )
    )
    assert spend_meta["total_count"] == 8, spend_meta


@pytest.mark.parametrize(
    "label,headers", _REJECTED_IDENTITIES, ids=[label for label, _ in _REJECTED_IDENTITIES]
)
def test_unauthenticated_request_without_identity_headers_rejected(
    api: ApiClient, label: str, headers: Dict[str, str]
) -> None:
    """PRD 2.1: "Every request to this service must carry two headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, naming the capability set that operator is acting under. If either header is absent or present but empty, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing occurs."
    PRD 2.12: "Authentication comes first: missing or empty headers give `ERR_UNAUTHENTICATED`, then an unknown or unpermitted role gives `ERR_UNAUTHORIZED`."
    PRD 3.1: "A second market claiming an existing `market_code` is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/rbac/unauthenticated_request_without_identity_headers_rejected
    """
    market = fx.create_market(api)
    assert _market_count(api) == 1

    # A read of an existing row still needs both headers.
    validate_error(api.get_market(market["id"], headers), ApiErrorId.ERR_UNAUTHENTICATED)

    # So does a write that would otherwise be admissible.
    validate_error(
        api.create_market(f.market_payload(market_code=f.SECOND_MARKET_CODE), headers),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )

    # The identity gate runs before the uniqueness check, so a body that would
    # collide on `market_code` is still answered as an authentication failure.
    validate_error(
        api.create_market(f.market_payload(), headers),
        ApiErrorId.ERR_UNAUTHENTICATED,
    )

    # Nothing was created by any of the three refused calls.
    assert _market_count(api) == 1
    still_there = validate_success(api.get_market(market["id"], users.AUDITOR), 200)
    expect.assert_version_unchanged(market, still_there)


def _auditor_create_market(api: ApiClient, ctx: Dict[str, object]) -> None:
    validate_error(
        api.create_market(f.second_market_payload(), users.AUDITOR),
        ApiErrorId.ERR_UNAUTHORIZED,
    )


def _auditor_seal_window(api: ApiClient, ctx: Dict[str, object]) -> None:
    window = ctx["window"]
    validate_error(
        api.seal_data_window(window["id"], users.AUDITOR),
        ApiErrorId.ERR_UNAUTHORIZED,
    )


def _auditor_set_clock(api: ApiClient, ctx: Dict[str, object]) -> None:
    validate_error(
        api.set_clock(fx.CLOCK_WINDOW_ELAPSED, users.AUDITOR),
        ApiErrorId.ERR_UNAUTHORIZED,
    )


_AUDITOR_MUTATIONS: Dict[str, Callable[[ApiClient, Dict[str, object]], None]] = {
    "create_market": _auditor_create_market,
    "seal_data_window": _auditor_seal_window,
    "set_clock": _auditor_set_clock,
}


@pytest.mark.parametrize("mutation", sorted(_AUDITOR_MUTATIONS), ids=sorted(_AUDITOR_MUTATIONS))
def test_auditor_cannot_perform_any_mutation(api: ApiClient, mutation: str) -> None:
    """PRD 2.1: "An `Auditor` is strictly read-only: it may read every collection, including superseded observations and stale reports, and may perform no mutation whatsoever, not even advancing the logical clock."
    PRD 2.9: "All roles except `Auditor` may advance the clock; an `Auditor` attempting it receives `ERR_UNAUTHORIZED`."
    PRD 2.1: "If `X-User-Role` is a string that is not one of the six declared role names, or is a valid role that is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD 2.8: "The window must have elapsed — the current logical clock must be at or after `window_end_date`, otherwise the request is refused with `ERR_DATA_WINDOW_NOT_ELAPSED`."

    Design: Corner/rbac/auditor_cannot_perform_any_mutation
    """
    fx.set_clock(api)
    market = fx.create_market(api)
    window = fx.create_data_window(api, market["id"])
    assert window["status"] == "OPEN", window["status"]

    _AUDITOR_MUTATIONS[mutation](api, {"market": market, "window": window})

    # Reads are permitted, and they show the refused mutation left no trace.
    stored_window = validate_success(
        api.get_data_window(window["id"], users.AUDITOR), 200
    )
    assert stored_window["status"] == "OPEN", stored_window["status"]
    expect.assert_version_unchanged(window, stored_window)

    restricted, restricted_meta = validate_paginated(
        api.list_markets(users.AUDITOR, {"data_posture": "RESTRICTED"})
    )
    assert restricted_meta["total_count"] == 1, restricted_meta
    assert [row["id"] for row in restricted] == [market["id"]], restricted

    # The refused clock call did not advance time: the window's exclusive end is
    # still in the future, so even the role that may seal is told it has not elapsed.
    validate_error(
        api.seal_data_window(window["id"], users.DATA_ENGINEER),
        ApiErrorId.ERR_DATA_WINDOW_NOT_ELAPSED,
    )


def test_modeler_cannot_publish_and_analytics_lead_cannot_fit(api: ApiClient) -> None:
    """PRD 2.1: "A `Modeler` specifies model runs, fits them, validates them against their holdout, files calibration records and applies those records through recalibration; a `Modeler` cannot publish a run — publication is a decision, not a modelling step — and cannot touch source data."
    PRD 3.4: "Fitting is the `Modeler`'s core operation and it moves `fit_status` from `PENDING` to `FITTED`, or from `STALE_FIT` back to `FITTED`."
    PRD 3.5: "Publication is an `AnalyticsLead` decision and the only writer of the `publication_status` dimension."
    PRD 3.4: "A newly created run reports `fit_status` `PENDING`, `validation_status` `UNVALIDATED`, `calibration_status` `NOT_REQUIRED` and `publication_status` `UNPUBLISHED`."
    PRD 4: "The Authorized Role(s) column is exhaustive: a request from an authenticated operator whose `X-User-Role` is not listed for that endpoint is refused with `ERR_UNAUTHORIZED`, and an operator-identity or posture check never runs before that role check."
    PRD 3.4: "The run then sets `fit_status` to `FITTED`, resets `validation_status` to `UNVALIDATED`, clears `holdout_mape_pct` to null, records the acting operator in `fitted_by_user_id`, and increments its `version`."

    Design: Corner/rbac/modeler_cannot_publish_and_analytics_lead_cannot_fit
    """
    ctx = fx.sealed_window(api)
    run = fx.create_run(api, ctx)
    assert run["fit_status"] == "PENDING", run["fit_status"]
    assert run["validation_status"] == "UNVALIDATED", run["validation_status"]
    assert run["publication_status"] == "UNPUBLISHED", run["publication_status"]

    # The decision role may not fit.
    validate_error(
        api.fit_model_run(run["id"], users.ANALYTICS_LEAD),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    # The modelling role may not publish. The run is also unpublishable at this
    # moment, but the role check answers before any state precondition.
    validate_error(
        api.publish_model_run(run["id"], users.MODELER, f.publish_payload()),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    # A third role can do neither half.
    validate_error(
        api.publish_model_run(run["id"], users.BRAND_PLANNER, f.publish_payload()),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    # Every denial left all four dimensions where they were.
    unchanged = validate_success(api.get_model_run(run["id"], users.AUDITOR), 200)
    assert unchanged["fit_status"] == "PENDING", unchanged["fit_status"]
    assert unchanged["validation_status"] == "UNVALIDATED", unchanged["validation_status"]
    assert unchanged["publication_status"] == "UNPUBLISHED", unchanged["publication_status"]
    assert unchanged["fitted_by_user_id"] is None, unchanged
    assert unchanged["published_by_user_id"] is None, unchanged
    expect.assert_version_unchanged(run, unchanged)

    # Each half succeeds for the role that owns it.
    fitted = validate_success(api.fit_model_run(run["id"], users.MODELER), 200)
    assert fitted["fit_status"] == "FITTED", fitted["fit_status"]
    assert fitted["fitted_by_user_id"] == users.MODELER_ID, fitted

    validated = validate_success(api.validate_model_run(run["id"], users.MODELER), 200)
    assert validated["validation_status"] == "HOLDOUT_PASSED", validated["validation_status"]

    published = validate_success(
        api.publish_model_run(run["id"], users.ANALYTICS_LEAD, f.publish_payload()), 200
    )
    assert published["publication_status"] == "PUBLISHED", published["publication_status"]
    assert published["published_by_user_id"] == users.ANALYTICS_LEAD_ID, published


def test_brand_planner_cannot_approve_budget_scenario(api: ApiClient) -> None:
    """PRD 2.1: "A `BrandPlanner` builds budget scenarios, enrols channels into them with baseline spend, runs the optimizer and reverts an optimization, but can never approve a scenario — not even one another planner created."
    PRD 2.1: "An `AnalyticsLead` is the sole decision authority: publishing model runs, accepting or rejecting experiment readouts, approving budget scenarios, and filing reconciliation reports."
    PRD 3.8: "Approval is an `AnalyticsLead` decision available only from `OPTIMIZED`, or `ERR_BUDGET_SCENARIO_INVALID_STATE`."
    PRD 3.8: "On success the scenario becomes `APPROVED`, records `approved_by_user_id`, and increments `version`."
    PRD 2.10: "The first is fiscal: for every budget scenario, the sum of `allocated_total_cents`, `reallocation_fee_cents` and `unallocated_cents` equals `total_budget_cents` at every observable moment."

    Design: Corner/rbac/brand_planner_cannot_approve_budget_scenario
    """
    ctx = fx.optimized_scenario(api)
    scenario = ctx["scenario"]
    assert scenario["status"] == "OPTIMIZED", scenario["status"]

    # Reverting is the planner's own operation; the decision role may not do it.
    validate_error(
        api.revert_optimization(scenario["id"], users.ANALYTICS_LEAD),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    # Approving is the lead's own decision; the planner who built the plan — and
    # any other planner — may not take it.
    validate_error(
        api.approve_budget_scenario(scenario["id"], users.BRAND_PLANNER),
        ApiErrorId.ERR_UNAUTHORIZED,
    )
    validate_error(
        api.approve_budget_scenario(scenario["id"], users.BRAND_PLANNER_2),
        ApiErrorId.ERR_UNAUTHORIZED,
    )

    # Neither denial touched the optimizer's output or the approval field.
    intact = validate_success(api.get_budget_scenario(scenario["id"], users.AUDITOR), 200)
    assert intact["status"] == "OPTIMIZED", intact["status"]
    assert intact["allocated_total_cents"] == fx.F1_ALLOCATED_TOTAL_CENTS, intact
    assert intact["reallocation_fee_cents"] == fx.F1_REALLOCATION_FEE_CENTS, intact
    assert intact["unallocated_cents"] == fx.F1_UNALLOCATED_CENTS, intact
    assert intact["approved_by_user_id"] is None, intact
    expect.assert_version_unchanged(scenario, intact)
    expect.assert_budget_conservation(intact)

    # The lead's approval succeeds and records the deciding operator.
    approved = validate_success(
        api.approve_budget_scenario(scenario["id"], users.ANALYTICS_LEAD), 200
    )
    assert approved["status"] == "APPROVED", approved["status"]
    assert approved["approved_by_user_id"] == users.ANALYTICS_LEAD_ID, approved

    # Approval freezes the plan; it does not recompute it.
    allocations = expect.rows_by(fx.allocations_of(api, scenario["id"]), "channel_id")
    assert allocations[ctx["a_search"]["id"]]["allocated_cents"] == (
        fx.F1_ALLOCATED_A_SEARCH_CENTS
    ), allocations
    assert allocations[ctx["b_social"]["id"]]["allocated_cents"] == (
        fx.F1_ALLOCATED_B_SOCIAL_CENTS
    ), allocations


def test_analytics_lead_cannot_decide_a_readout_it_designed(api: ApiClient) -> None:
    """PRD 2.11: "Accepting or rejecting an experiment readout requires that the acting `X-User-ID` differs from the `designed_by_user_id` recorded when the experiment was drafted."
    PRD 2.11: "In either case a match yields `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 2.11: "Two decisions in this service may not be made by the operator who set them up, and both checks compare opaque identifiers rather than roles."
    PRD 3.6: "Both arms require the experiment to be in `READ_OUT`, and both require that the acting `X-User-ID` differs from the experiment's `designed_by_user_id` — a match is `ERR_SEGREGATION_OF_DUTIES`, and because the duty check outranks the state check, an operator who both designed the experiment and invokes a decision from the wrong state is told about the duty conflict rather than about the state."
    PRD 3.6: "On success the experiment moves to `ACCEPTED`, records the deciding operator in `decided_by_user_id`, and increments `version` — and then a three-hop cascade reprices the market's whole analytical posture."

    Design: Corner/rbac/analytics_lead_cannot_decide_a_readout_it_designed
    """
    ctx = fx.experiment_on_published_market(api)
    experiment = ctx["experiment"]
    assert experiment["status"] == "READ_OUT", experiment["status"]
    assert experiment["designed_by_user_id"] == users.EXPERIMENT_DESIGNER_ID, experiment

    # The designer changing hats to the deciding role is still the same operator,
    # and the duty check reads the operator identifier, not the role.
    validate_error(
        api.accept_experiment(experiment["id"], users.DESIGNER_AS_ANALYTICS_LEAD),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    # The guard is symmetric across the two arms of the fork.
    validate_error(
        api.reject_experiment(
            experiment["id"], f.reject_payload(), users.DESIGNER_AS_ANALYTICS_LEAD
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    # Neither refused decision was recorded.
    intact = validate_success(api.get_experiment(experiment["id"], users.AUDITOR), 200)
    assert intact["status"] == "READ_OUT", intact["status"]
    assert intact["decided_by_user_id"] is None, intact
    assert intact["rejection_reason"] is None, intact
    expect.assert_version_unchanged(experiment, intact)

    # A different operator under the same role is admitted, and the decision is
    # attributed to it.
    accepted = validate_success(
        api.accept_experiment(experiment["id"], users.ANALYTICS_LEAD), 200
    )
    assert accepted["status"] == "ACCEPTED", accepted["status"]
    assert accepted["decided_by_user_id"] == users.ANALYTICS_LEAD_ID, accepted
    assert accepted["version"] == intact["version"] + 1, accepted


def test_approver_cannot_be_the_scenario_creator(api: ApiClient) -> None:
    """PRD 2.11: "Approving a budget scenario requires that the acting `X-User-ID` differs from the `created_by_user_id` recorded when the scenario was opened."
    PRD 2.11: "In either case a match yields `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD 3.8: "The acting `X-User-ID` must differ from the scenario's `created_by_user_id`, or `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.8: "Approval is an `AnalyticsLead` decision available only from `OPTIMIZED`, or `ERR_BUDGET_SCENARIO_INVALID_STATE`."
    PRD 3.8: "On success the scenario becomes `APPROVED`, records `approved_by_user_id`, and increments `version`."

    Design: Corner/rbac/approver_cannot_be_the_scenario_creator
    """
    ctx = fx.optimized_scenario(api)
    scenario = ctx["scenario"]
    assert scenario["created_by_user_id"] == users.BRAND_PLANNER_ID, scenario
    assert scenario["status"] == "OPTIMIZED", scenario["status"]

    # The planner who opened the plan cannot approve it by changing hats: the
    # comparison is against the stored operator identifier, not the role.
    validate_error(
        api.approve_budget_scenario(scenario["id"], users.PLANNER_AS_ANALYTICS_LEAD),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )

    intact = validate_success(api.get_budget_scenario(scenario["id"], users.AUDITOR), 200)
    assert intact["status"] == "OPTIMIZED", intact["status"]
    assert intact["approved_by_user_id"] is None, intact
    expect.assert_version_unchanged(scenario, intact)

    # A different operator under the deciding role is admitted.
    approved = validate_success(
        api.approve_budget_scenario(scenario["id"], users.ANALYTICS_LEAD), 200
    )
    assert approved["status"] == "APPROVED", approved["status"]
    assert approved["approved_by_user_id"] == users.ANALYTICS_LEAD_ID, approved
    assert approved["version"] == intact["version"] + 1, approved

    # APPROVED is terminal, and from there the state precondition answers first.
    validate_error(
        api.approve_budget_scenario(scenario["id"], users.ANALYTICS_LEAD),
        ApiErrorId.ERR_BUDGET_SCENARIO_INVALID_STATE,
    )
