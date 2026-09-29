"""Refusals: the requests the contract turns away, and the ones it lets through.

Every case here drives one operation into a rule it breaks, checks the exact
error identifier the contract names for that breach, and then checks that
nothing moved — no counter, no version, no status, no child row. Where a
refusal has an adjacent satisfaction case, the same fixture is walked one step
further so the rule is falsifiable rather than merely observed: the sealed
window is reopened and the same body then succeeds, the retired channel is
paused and the same fit then converges, the unpublished run is published and a
different rule answers, the empty scenario gets its rows and optimizes.
"""

from decimal import Decimal
from typing import Any, Dict, List

import pytest

from test_helpers import (
    ApiClient,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as expect
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId

# ---------------------------------------------------------------------------
# Literals the cases below need, stated once
# ---------------------------------------------------------------------------

# The reason carried on the reopen that lifts the sealed-window gate.
_REOPEN_REASON = "Publisher restated August search spend."

# A restatement of the first A_SEARCH week: same window, same channel, same
# period, a different amount.
_RESTATED_SPEND_CENTS = 450_000
_RESTATED_IMPRESSIONS = 4_500

# What the canonical sealed window holds before any of these writes.
_SEALED_SALES_PERIOD_COUNT = 4
_SEALED_SPEND_OBSERVATION_COUNT = 8
_VERSION_AFTER_REOPEN = 15
_VERSION_AFTER_RESTATEMENT = 16

# A window carrying only three of its four expected weekly sales periods.
_INCOMPLETE_SALES_PERIOD_COUNT = 3
_INCOMPLETE_LAG_COMPLETENESS_PCT = 75.00
_COMPLETE_LAG_COMPLETENESS_PCT = 100.00
_VERSION_AFTER_THREE_SALES = 4
_VERSION_AFTER_FOURTH_SALES = 5
_VERSION_AFTER_LATE_SEAL = 6
_FOURTH_PERIOD_AVG_PRICE_CENTS = 5000
_CLOCK_INSIDE_WINDOW = "2026-08-10T00:00:00Z"

# A perfectly flat readout: identical conversions in all four cells, which
# leaves the measured effect at zero with an interval straddling zero.
_FLAT_CONVERSIONS = 4900
_FLAT_MEASURED_LIFT_PCT = 0.00
_FLAT_CI_HALF_WIDTH_PCT = 3.92
_FLAT_CI_LOW_PCT = -3.92
_FLAT_CI_HIGH_PCT = 3.92

# A clock inside the experiment's half-open range: started, not yet elapsed.
_CLOCK_INSIDE_EXPERIMENT = "2026-09-08T00:00:00Z"

# Conversion counts above the 245000-person realised arms.
_OVER_ARM_TREATMENT_CONVERSIONS = 300000
_OVER_ARM_PRE_TREATMENT_CONVERSIONS = 250000

# Two same-sized cells in the canonical market, and one in a foreign market.
_CELL_POPULATION = 100_000
_ASSIGNED_HELD_OUT_POPULATION = 200_000

# The second, deliberately tiny scenario: a four-week December horizon whose
# whole budget is below the floors of the channels enrolled into it.
_TIGHT_PLANNING_START = "2026-12-01T00:00:00Z"
_TIGHT_PLANNING_END = "2026-12-29T00:00:00Z"
_TIGHT_TOTAL_BUDGET_CENTS = 100_000
_TIGHT_BASELINE_CENTS = 60_000

# A platform figure for the third channel, which the run never included.
_C_VIDEO_PLATFORM_CENTS = 5_000_000

# A readout whose one-percent measured lift is far under the model's own
# 18.8835 percent, so the quotient falls below the multiplier floor.
_WEAK_TREATMENT_CONVERSIONS = 4704
_WEAK_MEASURED_LIFT_PCT = 1.00


def _num(value: Any) -> Decimal:
    """A decimal-valued field, compared at its stated scale rather than in binary."""
    return Decimal(str(value))


def _window(api: ApiClient, window_id: str) -> Dict[str, Any]:
    """Re-read a data window as the engineer who owns it."""
    return validate_success(api.get_data_window(window_id, users.DATA_ENGINEER))


def _sales_body(ctx: Dict[str, Any], index: int = 0) -> Dict[str, Any]:
    """The exact sales body that was already accepted for one weekly period."""
    row = f.F1_SALES_ROWS[index]
    return f.sales_observation_payload(
        ctx["window"]["id"],
        f.WINDOW_PERIODS[index],
        row["units_sold"],
        row["revenue_cents"],
    )


def _restated_spend_body(ctx: Dict[str, Any], version: int) -> Dict[str, Any]:
    """A restatement of the first A_SEARCH week, carrying a window version."""
    return f.spend_observation_payload(
        ctx["window"]["id"],
        ctx["a_search"]["id"],
        f.WINDOW_PERIODS[0],
        _RESTATED_SPEND_CENTS,
        version,
        impressions=_RESTATED_IMPRESSIONS,
    )


def _flat_readout() -> Dict[str, int]:
    """Four identical conversion counts, one per readout cell."""
    return {
        "treatment_conversions": _FLAT_CONVERSIONS,
        "control_conversions": _FLAT_CONVERSIONS,
        "pre_treatment_conversions": _FLAT_CONVERSIONS,
        "pre_control_conversions": _FLAT_CONVERSIONS,
    }


def _total_count(response: Any) -> int:
    """The `total_count` a list response reports."""
    _, meta = validate_paginated(response)
    return meta["total_count"]


def _contribution_units_by_code(
    api: ApiClient, run_id: str, ctx: Dict[str, Any]
) -> Dict[str, Any]:
    """The run's contribution rows keyed by the channel each one decomposes."""
    rows = fx.contributions_of(api, run_id)
    by_channel = expect.rows_by(rows, "channel_id")
    return {
        "A_SEARCH": by_channel.get(ctx["a_search"]["id"]),
        "B_SOCIAL": by_channel.get(ctx["b_social"]["id"]),
    }


def _line_bodies(channel_ids: List[str], amounts: List[int]) -> List[Dict[str, Any]]:
    """One platform line per channel named, in the order given."""
    return [
        f.platform_line(channel_id, amount)
        for channel_id, amount in zip(channel_ids, amounts)
    ]


def test_sales_write_into_a_sealed_window_is_refused_as_sealed(api: ApiClient):
    """PRD 3.2: "An `OPEN` window accepts observation writes, and so does a
    `REOPENED` one; a `SEALED` window accepts neither a new observation nor a
    restatement, and an attempt to file into one is `ERR_DATA_WINDOW_SEALED`."
    PRD 3.2: "**Sales** are filed at market level, one row per period, and here
    uniqueness *is* enforced: a period of a window may carry at most one sales
    row, and a second attempt is `ERR_DUPLICATE_RESOURCE`."
    PRD 2.12: "After existence comes the separation-of-duties comparison, then
    optimistic-concurrency version matching, then the target resource's own state
    precondition, then cross-entity state preconditions that reach into a related
    row."

    Design: Corner/errors/observation_writes_to_sealed_window_rejected
    """
    ctx = fx.sealed_window(api)
    assert ctx["window"]["status"] == "SEALED"
    assert ctx["window"]["version"] == fx.F1_WINDOW_VERSION_AFTER_SEAL

    # This body was already accepted once, so it breaks the per-period
    # uniqueness rule as well; the window's own state answers first.
    response = api.create_sales_observation(_sales_body(ctx), users.DATA_ENGINEER)
    validate_error(response, ApiErrorId.ERR_DATA_WINDOW_SEALED.value, 409)
    assert (
        response.json()["data"]["error_id"] != ApiErrorId.ERR_DUPLICATE_RESOURCE.value
    ), "the duplicate rule must not pre-empt the sealed-window refusal"

    after = _window(api, ctx["window"]["id"])
    assert after["status"] == "SEALED"
    assert after["version"] == fx.F1_WINDOW_VERSION_AFTER_SEAL
    assert after["sales_period_count"] == _SEALED_SALES_PERIOD_COUNT
    assert after["spend_observation_count"] == _SEALED_SPEND_OBSERVATION_COUNT


def test_spend_write_into_a_sealed_window_is_refused_not_stale(api: ApiClient):
    """PRD 3.2: "An `OPEN` window accepts observation writes, and so does a
    `REOPENED` one; a `SEALED` window accepts neither a new observation nor a
    restatement, and an attempt to file into one is `ERR_DATA_WINDOW_SEALED`."
    PRD 2.7: "If that value does not equal the window's current `version`, the
    write is rejected with `ERR_STALE_DATA_WINDOW_VERSION` (HTTP 412) and nothing
    is persisted."

    Design: Corner/errors/observation_writes_to_sealed_window_rejected
    """
    ctx = fx.sealed_window(api)
    current_version = fx.window_version(api, ctx["window"]["id"])
    assert current_version == fx.F1_WINDOW_VERSION_AFTER_SEAL

    # The concurrency token is deliberately current, so the version check has
    # nothing to complain about and the sealed-window rule is the one reached.
    response = api.create_spend_observation(
        _restated_spend_body(ctx, current_version), users.DATA_ENGINEER
    )
    validate_error(response, ApiErrorId.ERR_DATA_WINDOW_SEALED.value, 409)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_STALE_DATA_WINDOW_VERSION.value
    ), "a current version token must not be reported as stale"

    after = _window(api, ctx["window"]["id"])
    assert after["version"] == fx.F1_WINDOW_VERSION_AFTER_SEAL
    assert after["spend_observation_count"] == _SEALED_SPEND_OBSERVATION_COUNT
    assert after["sales_period_count"] == _SEALED_SALES_PERIOD_COUNT
    incumbent = validate_success(
        api.get_spend_observation(ctx["spend"][0]["id"], users.DATA_ENGINEER)
    )
    assert incumbent["superseded_by_id"] is None, (
        "a refused restatement must not supersede the incumbent"
    )


def test_reopening_lifts_the_sealed_gate_and_the_next_rule_down_answers(
    api: ApiClient,
):
    """PRD 3.3: "The transition sets `status` to `REOPENED`, increases
    `reopen_count` by one, and bumps `version`."
    PRD 3.2: "**Sales** are filed at market level, one row per period, and here
    uniqueness *is* enforced: a period of a window may carry at most one sales
    row, and a second attempt is `ERR_DUPLICATE_RESOURCE`."
    PRD 3.2: "The incumbent's `superseded_by_id` is set to the new row's
    identifier, and the new row's `is_restatement` becomes true."
    PRD 3.2: "Every accepted spend write recomputes the parent window's
    `spend_observation_count` over its non-superseded rows only, increments the
    window's `version`, and stamps the observation's `data_window_version_after`
    with the post-write value."

    Design: Corner/errors/observation_writes_to_sealed_window_rejected
    """
    ctx = fx.sealed_window(api)

    reopened = validate_success(
        api.reopen_data_window(
            ctx["window"]["id"], f.reopen_payload(_REOPEN_REASON), users.DATA_ENGINEER
        )
    )
    assert reopened["status"] == "REOPENED"
    assert reopened["reopen_count"] == 1
    assert reopened["reopen_reason"] == _REOPEN_REASON
    assert reopened["version"] == _VERSION_AFTER_REOPEN

    # The sales body is still a duplicate of an accepted period, and now that
    # the window's own state permits writes, that is the rule that speaks.
    duplicate = api.create_sales_observation(_sales_body(ctx), users.DATA_ENGINEER)
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_RESOURCE.value, 409)

    # Spend carries no such uniqueness, so the identical channel-period is a
    # restatement of the incumbent rather than a duplicate.
    restatement = validate_success(
        api.create_spend_observation(
            _restated_spend_body(ctx, _VERSION_AFTER_REOPEN), users.DATA_ENGINEER
        ),
        201,
    )
    assert restatement["is_restatement"] is True
    assert restatement["superseded_by_id"] is None
    assert restatement["data_window_version_after"] == _VERSION_AFTER_RESTATEMENT

    incumbent = validate_success(
        api.get_spend_observation(ctx["spend"][0]["id"], users.DATA_ENGINEER)
    )
    assert incumbent["superseded_by_id"] == restatement["id"]

    after = _window(api, ctx["window"]["id"])
    assert after["spend_observation_count"] == _SEALED_SPEND_OBSERVATION_COUNT, (
        "the counter walks non-superseded rows only, so a restatement is flat"
    )
    assert after["version"] == _VERSION_AFTER_RESTATEMENT


def _partial_window(api: ApiClient) -> Dict[str, Any]:
    """A window carrying three of its four expected weekly sales periods."""
    ctx = fx.market_with_channels(api)
    window = fx.create_data_window(api, ctx["market"]["id"])
    fx.file_sales_rows(
        api, window["id"], f.WINDOW_PERIODS[:3], f.F1_SALES_ROWS[:3]
    )
    ctx["window"] = window
    return ctx


def test_seal_before_the_window_elapses_is_refused_as_not_elapsed(api: ApiClient):
    """PRD 3.3: "The window must have elapsed — the current logical clock must be
    at or after `window_end_date`, otherwise the request is refused with
    `ERR_DATA_WINDOW_NOT_ELAPSED`."
    PRD 3.3: "A failure of either of the last two conditions is
    `ERR_DATA_WINDOW_INCOMPLETE`."
    PRD 2.12: "Below the state layer sit the safety gates — the market posture
    check first, then the experiment power gate — followed by
    referential-coherence checks (whether a referenced channel or cell belongs to
    the right market, whether a design type matches the action, whether a required
    set of child rows exists, whether the supplied platform lines match the run's
    contributions), then aggregate and boundary constraints (holdout share,
    conversion counts against arm populations, lift significance, redesign limits,
    scoped uniqueness, non-negative baseline, calibration-multiplier range, model
    stability), then temporal constraints (channel-window occupancy, window
    overlap, elapsed windows, experiment start and end, period alignment, clock
    monotonicity), then completeness constraints (window completeness, lag
    identifiability, spend floors against budget), and finally the fiscal checks
    (market budget ceiling, then baseline-versus-budget reconciliation)."

    Design: Corner/errors/seal_temporal_and_completeness_gates_rejected
    """
    ctx = _partial_window(api)
    fx.set_clock(api, _CLOCK_INSIDE_WINDOW)

    # The window is both un-elapsed and incomplete; the temporal rung answers.
    response = api.seal_data_window(ctx["window"]["id"], users.DATA_ENGINEER)
    validate_error(response, ApiErrorId.ERR_DATA_WINDOW_NOT_ELAPSED.value, 409)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_DATA_WINDOW_INCOMPLETE.value
    ), "the completeness check must not pre-empt the elapsed-window check"

    after = _window(api, ctx["window"]["id"])
    assert after["status"] == "OPEN"
    assert after["sales_period_count"] == _INCOMPLETE_SALES_PERIOD_COUNT
    assert after["version"] == _VERSION_AFTER_THREE_SALES


def test_seal_of_an_incomplete_window_is_refused_until_the_last_period_arrives(
    api: ApiClient,
):
    """PRD 3.3: "The window must carry at least four sales periods, that is a
    `sales_period_count` of four or more."
    PRD 3.3: "And it must be complete: `lag_completeness_pct` must be exactly
    100.00, meaning every expected period of the window has its sales row."
    PRD 3.3: "A failure of either of the last two conditions is
    `ERR_DATA_WINDOW_INCOMPLETE`."
    PRD 3.3: "Sealing sets `status` to `SEALED`, bumps the window's `version`, and
    recomputes the market's posture."

    Design: Corner/errors/seal_temporal_and_completeness_gates_rejected
    """
    ctx = _partial_window(api)
    fx.set_clock(api, fx.CLOCK_WINDOW_ELAPSED)

    refused = api.seal_data_window(ctx["window"]["id"], users.DATA_ENGINEER)
    validate_error(refused, ApiErrorId.ERR_DATA_WINDOW_INCOMPLETE.value, 422)

    incomplete = _window(api, ctx["window"]["id"])
    assert incomplete["status"] == "OPEN"
    assert incomplete["sales_period_count"] == _INCOMPLETE_SALES_PERIOD_COUNT
    assert _num(incomplete["lag_completeness_pct"]) == _num(
        _INCOMPLETE_LAG_COMPLETENESS_PCT
    )
    assert incomplete["version"] == _VERSION_AFTER_THREE_SALES

    fourth = validate_success(
        api.create_sales_observation(
            _sales_body(ctx, 3), users.DATA_ENGINEER
        ),
        201,
    )
    assert fourth["avg_price_cents"] == _FOURTH_PERIOD_AVG_PRICE_CENTS

    complete = _window(api, ctx["window"]["id"])
    assert complete["sales_period_count"] == _SEALED_SALES_PERIOD_COUNT
    assert _num(complete["lag_completeness_pct"]) == _num(
        _COMPLETE_LAG_COMPLETENESS_PCT
    )
    assert complete["version"] == _VERSION_AFTER_FOURTH_SALES

    sealed = validate_success(
        api.seal_data_window(ctx["window"]["id"], users.DATA_ENGINEER)
    )
    assert sealed["status"] == "SEALED"
    assert sealed["version"] == _VERSION_AFTER_LATE_SEAL
    assert sealed["spend_observation_count"] == 0, (
        "completeness is a sales notion; sealing never demanded a spend row"
    )


def test_fit_including_a_retired_channel_is_refused_not_skipped(api: ApiClient):
    """PRD 3.4: "Every included channel must have a `status` of either `ACTIVE` or
    `PAUSED`; a `RETIRED` channel in the inclusion list is `ERR_CHANNEL_RETIRED`,
    and it is rejected rather than skipped."

    Design: Corner/errors/fit_with_retired_channel_rejected
    """
    ctx = fx.sealed_window(api)
    run = fx.create_run(api, ctx)
    assert run["fit_status"] == "PENDING"

    # The channel was ACTIVE when the run was declared, so the inclusion list is
    # re-checked against current channel status at fit time.
    retired = validate_success(
        api.patch_media_channel(
            ctx["b_social"]["id"], {"status": "RETIRED"}, users.DATA_ENGINEER
        )
    )
    assert retired["status"] == "RETIRED"

    response = api.fit_model_run(run["id"], users.MODELER)
    validate_error(response, ApiErrorId.ERR_CHANNEL_RETIRED.value, 409)

    after = validate_success(api.get_model_run(run["id"], users.MODELER))
    assert after["fit_status"] == "PENDING", "a refused fit leaves the run unfitted"
    assert (
        _total_count(
            api.list_channel_contributions(
                users.MODELER, {"model_run_id": run["id"]}
            )
        )
        == 0
    ), "a refused fit writes no decomposition rows at all"


def test_pausing_the_channel_lets_the_same_fit_converge(api: ApiClient):
    """PRD 3.1: "A `PAUSED` channel keeps all of its history and may still
    participate in a fit, but the budget optimizer skips it."
    PRD 3.4: "`modeled_sales_units` is the sum of their `units_sold`."
    PRD 3.4: "`unit_price_cents` is the sum of their `revenue_cents` divided by
    the sum of their `units_sold`, rounded half-up to a whole cent."
    PRD 3.4: "`baseline_sales_units` is `modeled_sales_units` minus the sum of
    every included channel's `contribution_units`, rounded half-up to four decimal
    places, so that the channel contributions plus the baseline reconstruct the
    modelled sales total exactly."

    Design: Corner/errors/fit_with_retired_channel_rejected
    """
    ctx = fx.sealed_window(api)
    run = fx.create_run(api, ctx)
    validate_success(
        api.patch_media_channel(
            ctx["b_social"]["id"], {"status": "RETIRED"}, users.DATA_ENGINEER
        )
    )
    validate_error(
        api.fit_model_run(run["id"], users.MODELER),
        ApiErrorId.ERR_CHANNEL_RETIRED.value,
        409,
    )

    paused = validate_success(
        api.patch_media_channel(
            ctx["b_social"]["id"], {"status": "PAUSED"}, users.DATA_ENGINEER
        )
    )
    assert paused["status"] == "PAUSED"

    fitted = validate_success(api.fit_model_run(run["id"], users.MODELER))
    assert fitted["fit_status"] == "FITTED"
    assert fitted["modeled_sales_units"] == fx.F1_MODELED_SALES_UNITS
    assert fitted["unit_price_cents"] == fx.F1_UNIT_PRICE_CENTS
    assert _num(fitted["baseline_sales_units"]) == _num(fx.F1_EFFECT_BASELINE_UNITS)

    assert (
        _total_count(
            api.list_channel_contributions(
                users.MODELER, {"model_run_id": run["id"]}
            )
        )
        == 2
    )
    rows = _contribution_units_by_code(api, run["id"], ctx)
    assert _num(rows["A_SEARCH"]["contribution_units"]) == _num(
        fx.F1_EFFECT_CONTRIBUTION_A_SEARCH
    )
    assert _num(rows["B_SOCIAL"]["contribution_units"]) == _num(
        fx.F1_EFFECT_CONTRIBUTION_B_SOCIAL
    ), "a paused channel still earns its own decomposition row"


def test_accept_without_a_published_run_is_refused_before_the_lift_is_judged(
    api: ApiClient,
):
    """PRD 3.6: "Accepting additionally requires that the market has a model run
    with `publication_status` `PUBLISHED` to calibrate — there is nothing to
    correct otherwise, and the absence answers `ERR_NO_PUBLISHED_MODEL_RUN`."
    PRD 3.6: "It also requires that the measured effect is significantly positive:
    `lift_ci_low_pct` must be strictly greater than 0.00, and a readout whose
    interval straddles or touches zero is refused with `ERR_LIFT_NOT_SIGNIFICANT`."

    Design: Corner/errors/accept_requires_published_run_then_significant_lift
    """
    ctx = fx.validated_run(api)
    assert ctx["run"]["publication_status"] == "UNPUBLISHED"

    experiment = fx.read_out_experiment(
        api, ctx, readout_overrides=_flat_readout()
    )
    assert _num(experiment["measured_lift_pct"]) == _num(_FLAT_MEASURED_LIFT_PCT)
    assert _num(experiment["lift_ci_half_width_pct"]) == _num(_FLAT_CI_HALF_WIDTH_PCT)
    assert _num(experiment["lift_ci_low_pct"]) == _num(_FLAT_CI_LOW_PCT)
    assert _num(experiment["lift_ci_high_pct"]) == _num(_FLAT_CI_HIGH_PCT)
    assert experiment["synthetic_control_weight"] is None

    # The interval touches neither side of zero cleanly, so the significance rule
    # is broken too; the missing published run is the one that answers.
    response = api.accept_experiment(experiment["id"], users.ANALYTICS_LEAD)
    validate_error(response, ApiErrorId.ERR_NO_PUBLISHED_MODEL_RUN.value, 409)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_LIFT_NOT_SIGNIFICANT.value
    ), "the significance gate must not pre-empt the missing-published-run refusal"

    after = validate_success(api.get_experiment(experiment["id"], users.ANALYTICS_LEAD))
    assert after["status"] == "READ_OUT"
    assert after["decided_by_user_id"] is None
    run = fx.refresh_run(api, ctx)
    assert run["calibration_status"] == "NOT_REQUIRED", (
        "a refused accept cascades nothing onto the run"
    )


def test_publishing_the_run_reaches_the_significance_gate_on_a_flat_readout(
    api: ApiClient,
):
    """PRD 3.6: "It also requires that the measured effect is significantly
    positive: `lift_ci_low_pct` must be strictly greater than 0.00, and a readout
    whose interval straddles or touches zero is refused with
    `ERR_LIFT_NOT_SIGNIFICANT`."
    PRD 3.5: "A successful publication records `previous_published_run_id` as the
    identifier of the market's outgoing published run — null when there was none,
    and null forever for the market's first publication — sets `publication_status`
    to `PUBLISHED`, records the deciding operator in `published_by_user_id`, and
    increments `version`."

    Design: Corner/errors/accept_requires_published_run_then_significant_lift
    """
    ctx = fx.validated_run(api)
    experiment = fx.read_out_experiment(
        api, ctx, readout_overrides=_flat_readout()
    )
    validate_error(
        api.accept_experiment(experiment["id"], users.ANALYTICS_LEAD),
        ApiErrorId.ERR_NO_PUBLISHED_MODEL_RUN.value,
        409,
    )

    fx.published_run(api, ctx)
    assert ctx["run"]["publication_status"] == "PUBLISHED"

    # Same experiment, same numbers, one precondition satisfied: the next rule up
    # the ladder is now the one that speaks.
    response = api.accept_experiment(experiment["id"], users.ANALYTICS_LEAD)
    validate_error(response, ApiErrorId.ERR_LIFT_NOT_SIGNIFICANT.value, 422)

    after = validate_success(api.get_experiment(experiment["id"], users.ANALYTICS_LEAD))
    assert after["status"] == "READ_OUT"
    assert after["decided_by_user_id"] is None
    assert _num(after["lift_ci_low_pct"]) == _num(_FLAT_CI_LOW_PCT)
    run = fx.refresh_run(api, ctx)
    assert run["calibration_status"] == "NOT_REQUIRED"


def test_start_before_the_start_date_is_refused_as_not_started(api: ApiClient):
    """PRD 3.6: "Either way the current logical clock must have reached
    `start_date`; earlier than that is `ERR_EXPERIMENT_NOT_STARTED`."
    PRD 3.6: "Success sets `status` to `RUNNING` and increments `version`."

    Design: Corner/errors/experiment_temporal_gates_and_conversion_ceiling_rejected
    """
    ctx = fx.market_with_channels(api)
    experiment = fx.locked_experiment(api, ctx)
    assert experiment["status"] == "DESIGN_LOCKED"

    # The clock still sits before the inclusive start of the in-market period.
    response = api.start_experiment(experiment["id"], users.EXPERIMENT_DESIGNER)
    validate_error(response, ApiErrorId.ERR_EXPERIMENT_NOT_STARTED.value, 409)

    after = validate_success(
        api.get_experiment(experiment["id"], users.EXPERIMENT_DESIGNER)
    )
    assert after["status"] == "DESIGN_LOCKED", "a refused start moves nothing"
    expect.assert_version_unchanged(experiment, after)


def test_read_out_before_the_end_date_is_refused_as_not_elapsed(api: ApiClient):
    """PRD 3.6: "Reading out is available only from `RUNNING`, or
    `ERR_EXPERIMENT_INVALID_STATE`, and only once the logical clock has reached
    `end_date`; earlier than that is `ERR_EXPERIMENT_NOT_ELAPSED`."
    PRD 3.6: "An `AUDIENCE_SPLIT` experiment reaches `RUNNING` straight from
    `DESIGN_LOCKED`, and that step (re)asserts `treatment_population` from
    `planned_treatment_population` and `control_population` from
    `planned_control_population`."

    Design: Corner/errors/experiment_temporal_gates_and_conversion_ceiling_rejected
    """
    ctx = fx.market_with_channels(api)
    running = fx.running_experiment(api, ctx, clock=_CLOCK_INSIDE_EXPERIMENT)
    assert running["status"] == "RUNNING"
    assert running["treatment_population"] == f.EXPERIMENT_ARM_POPULATION
    assert running["control_population"] == f.EXPERIMENT_ARM_POPULATION

    # The clock is inside the in-market period, so the exclusive end has not
    # been reached yet.
    response = api.read_out_experiment(
        running["id"], f.read_out_payload(), users.EXPERIMENT_DESIGNER
    )
    validate_error(response, ApiErrorId.ERR_EXPERIMENT_NOT_ELAPSED.value, 409)

    after = validate_success(
        api.get_experiment(running["id"], users.EXPERIMENT_DESIGNER)
    )
    assert after["status"] == "RUNNING"
    assert after["measured_lift_pct"] is None
    assert after["treatment_conversions"] is None
    expect.assert_version_unchanged(running, after)


@pytest.mark.parametrize(
    "field,count",
    [
        ("treatment_conversions", _OVER_ARM_TREATMENT_CONVERSIONS),
        ("pre_treatment_conversions", _OVER_ARM_PRE_TREATMENT_CONVERSIONS),
    ],
)
def test_conversions_above_the_realised_arm_are_refused(
    api: ApiClient, field: str, count: int
):
    """PRD 3.6: "Any of the four exceeding its arm's realised population is
    `ERR_CONVERSIONS_EXCEED_POPULATION`."

    Design: Corner/errors/experiment_temporal_gates_and_conversion_ceiling_rejected
    """
    ctx = fx.market_with_channels(api)
    running = fx.running_experiment(api, ctx, clock=_CLOCK_INSIDE_EXPERIMENT)
    assert running["treatment_population"] == f.EXPERIMENT_ARM_POPULATION
    assert count > f.EXPERIMENT_ARM_POPULATION, (
        "the probe must genuinely exceed the arm it is counted against"
    )
    fx.set_clock(api, fx.CLOCK_EXPERIMENT_ELAPSED)

    response = api.read_out_experiment(
        running["id"],
        f.read_out_payload(**{field: count}),
        users.EXPERIMENT_DESIGNER,
    )
    validate_error(response, ApiErrorId.ERR_CONVERSIONS_EXCEED_POPULATION.value, 422)

    after = validate_success(
        api.get_experiment(running["id"], users.EXPERIMENT_DESIGNER)
    )
    assert after["status"] == "RUNNING"
    assert after["measured_lift_pct"] is None
    assert after[field] is None
    expect.assert_version_unchanged(running, after)


def test_legal_counts_on_the_end_date_read_out(api: ApiClient):
    """PRD 3.6: "The four counts are stored, the four lift fields are set,
    `status` becomes `READ_OUT` and `version` increments."
    PRD 3.6: "Reading out is available only from `RUNNING`, or
    `ERR_EXPERIMENT_INVALID_STATE`, and only once the logical clock has reached
    `end_date`; earlier than that is `ERR_EXPERIMENT_NOT_ELAPSED`."

    Design: Corner/errors/experiment_temporal_gates_and_conversion_ceiling_rejected
    """
    ctx = fx.market_with_channels(api)
    running = fx.running_experiment(api, ctx, clock=_CLOCK_INSIDE_EXPERIMENT)
    validate_error(
        api.read_out_experiment(
            running["id"], f.read_out_payload(), users.EXPERIMENT_DESIGNER
        ),
        ApiErrorId.ERR_EXPERIMENT_NOT_ELAPSED.value,
        409,
    )

    # The clock now sits exactly on the experiment's end date, which the rule
    # names as reached rather than as still to come.
    fx.set_clock(api, fx.CLOCK_EXPERIMENT_ELAPSED)
    read_out = validate_success(
        api.read_out_experiment(
            running["id"], f.read_out_payload(), users.EXPERIMENT_DESIGNER
        )
    )
    assert read_out["status"] == "READ_OUT"
    assert _num(read_out["measured_lift_pct"]) == _num(fx.F1_DID_MEASURED_LIFT_PCT)
    assert read_out["treatment_conversions"] == f.READOUT_TREATMENT_CONVERSIONS
    assert read_out["control_conversions"] == f.READOUT_CONTROL_CONVERSIONS
    assert read_out["pre_treatment_conversions"] == f.READOUT_PRE_TREATMENT_CONVERSIONS
    assert read_out["pre_control_conversions"] == f.READOUT_PRE_CONTROL_CONVERSIONS


def _two_markets_with_a_geo_design(api: ApiClient) -> Dict[str, Any]:
    """A locked geo design in one market, plus an unrelated cell in another."""
    ctx = fx.market_with_channels(api)
    home_cells = fx.create_geo_cells(
        api,
        ctx["market"]["id"],
        [("GC01", _CELL_POPULATION), ("GC02", _CELL_POPULATION)],
    )
    foreign_market = fx.create_second_market(api)
    # The same cell_code is legal here because cell codes are scoped per market.
    foreign_cell = fx.create_geo_cell(
        api, foreign_market["id"], "GC01", _CELL_POPULATION
    )
    ctx["home_cells"] = home_cells
    ctx["foreign_market"] = foreign_market
    ctx["foreign_cell"] = foreign_cell
    ctx["experiment"] = fx.locked_experiment(
        api, ctx, geo=True, planned_population=f.EXPERIMENT_ARM_POPULATION
    )
    return ctx


def test_assign_cells_naming_a_foreign_market_cell_is_refused_not_missing(
    api: ApiClient,
):
    """PRD 3.6: "Below it, the design must actually be `GEO_HOLDOUT` or the answer
    is `ERR_DESIGN_TYPE_MISMATCH`, and every listed cell must belong to the
    experiment's market or the answer is `ERR_GEO_CELL_NOT_IN_MARKET`."
    PRD 3.6: "Every listed cell must resolve, or `ERR_GEO_CELL_NOT_FOUND`."

    Design: Corner/errors/assign_cells_with_foreign_market_cell_rejected
    """
    ctx = _two_markets_with_a_geo_design(api)
    home_cell = ctx["home_cells"][0]
    foreign_cell = ctx["foreign_cell"]

    # The foreign cell resolves perfectly well; it simply belongs elsewhere.
    response = api.assign_cells(
        ctx["experiment"]["id"],
        f.assign_cells_payload([home_cell["id"]], [foreign_cell["id"]]),
        users.EXPERIMENT_DESIGNER,
    )
    validate_error(response, ApiErrorId.ERR_GEO_CELL_NOT_IN_MARKET.value, 422)
    assert (
        response.json()["data"]["error_id"] != ApiErrorId.ERR_GEO_CELL_NOT_FOUND.value
    ), "a resolvable cell in the wrong market is a coherence failure, not a miss"

    for cell in (home_cell, foreign_cell):
        after = validate_success(
            api.get_geo_cell(cell["id"], users.EXPERIMENT_DESIGNER)
        )
        assert after["assignment_state"] == "UNASSIGNED"
        assert after["assigned_experiment_id"] is None

    home = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    foreign = validate_success(
        api.get_market(ctx["foreign_market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert home["held_out_population"] == 0
    assert foreign["held_out_population"] == 0


def test_two_home_market_cells_assign_and_hold_out_only_their_own_market(
    api: ApiClient,
):
    """PRD 3.6: "On success, each cell named in `treatment_cell_ids` moves to
    `assignment_state` `TREATMENT` and each cell named in `control_cell_ids` moves
    to `CONTROL`, both recording the experiment in their `assigned_experiment_id`;
    each such cell adds its `population` to the market's `held_out_population`."
    PRD 3.6: "The experiment's `treatment_population` becomes the summed
    population of its treatment cells and its `control_population` the summed
    population of its control cells."
    PRD 3.6: "The market's `held_out_population` and `held_out_population_pct` are
    recomputed, the experiment moves to `CELLS_ASSIGNED`, and its `version`
    increments."

    Design: Corner/errors/assign_cells_with_foreign_market_cell_rejected
    """
    ctx = _two_markets_with_a_geo_design(api)
    home_cell, second_cell = ctx["home_cells"]
    validate_error(
        api.assign_cells(
            ctx["experiment"]["id"],
            f.assign_cells_payload([home_cell["id"]], [ctx["foreign_cell"]["id"]]),
            users.EXPERIMENT_DESIGNER,
        ),
        ApiErrorId.ERR_GEO_CELL_NOT_IN_MARKET.value,
        422,
    )

    assigned = validate_success(
        api.assign_cells(
            ctx["experiment"]["id"],
            f.assign_cells_payload([home_cell["id"]], [second_cell["id"]]),
            users.EXPERIMENT_DESIGNER,
        )
    )
    assert assigned["status"] == "CELLS_ASSIGNED"
    assert assigned["treatment_population"] == _CELL_POPULATION
    assert assigned["control_population"] == _CELL_POPULATION

    home = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    foreign = validate_success(
        api.get_market(ctx["foreign_market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert home["held_out_population"] == _ASSIGNED_HELD_OUT_POPULATION
    assert foreign["held_out_population"] == 0, (
        "the held-out counter is scoped to the market that owns the cells"
    )
    foreign_cell = validate_success(
        api.get_geo_cell(ctx["foreign_cell"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert foreign_cell["assignment_state"] == "UNASSIGNED"


def test_optimize_with_no_allocation_rows_is_refused(api: ApiClient):
    """PRD 3.8: "It further requires that the referenced run is still `PUBLISHED`
    and `FITTED`, or `ERR_MODEL_RUN_NOT_PUBLISHED`; that the market's
    `data_posture` is exactly `OPEN` — the strictest posture requirement anywhere
    in the service — or `ERR_MARKET_POSTURE_BLOCKED`; that at least one allocation
    row exists, or `ERR_NO_ALLOCATIONS`; that the sum of the enrolled channels'
    `min_spend_cents` is at most `total_budget_cents`, or
    `ERR_FLOORS_EXCEED_BUDGET`; and that the sum of the rows'
    `baseline_spend_cents` equals `total_budget_cents` exactly, or
    `ERR_BASELINE_BUDGET_MISMATCH`."
    PRD 3.8: "A newly created scenario is in `DRAFT` with `reallocation_fee_cents`,
    `allocated_total_cents`, `unallocated_cents` and `shifted_total_cents` all at
    0, and with the acting operator captured in `created_by_user_id` as the
    approval comparand."

    Design: Corner/errors/optimize_allocation_gates_rejected
    """
    ctx = fx.published_run(api)
    assert ctx["run"]["publication_status"] == "PUBLISHED"
    assert ctx["market"]["data_posture"] == "OPEN"

    scenario = fx.create_scenario(api, ctx)
    assert scenario["status"] == "DRAFT"
    assert (
        _total_count(
            api.list_budget_allocations(
                users.BRAND_PLANNER, {"budget_scenario_id": scenario["id"]}
            )
        )
        == 0
    )

    response = api.optimize_budget_scenario(scenario["id"], users.BRAND_PLANNER)
    validate_error(response, ApiErrorId.ERR_NO_ALLOCATIONS.value, 422)

    after = validate_success(
        api.get_budget_scenario(scenario["id"], users.BRAND_PLANNER)
    )
    assert after["status"] == "DRAFT"
    assert after["reallocation_fee_cents"] == 0
    assert after["allocated_total_cents"] == 0
    assert after["unallocated_cents"] == 0
    assert after["shifted_total_cents"] == 0
    expect.assert_version_unchanged(scenario, after)


def test_baselines_short_of_the_budget_are_refused_then_completed_and_optimized(
    api: ApiClient,
):
    """PRD 3.8: "Optimizing is available only from `DRAFT`, or
    `ERR_BUDGET_SCENARIO_INVALID_STATE`."
    PRD 3.8: "It further requires that the referenced run is still `PUBLISHED` and
    `FITTED`, or `ERR_MODEL_RUN_NOT_PUBLISHED`; that the market's `data_posture` is
    exactly `OPEN` — the strictest posture requirement anywhere in the service — or
    `ERR_MARKET_POSTURE_BLOCKED`; that at least one allocation row exists, or
    `ERR_NO_ALLOCATIONS`; that the sum of the enrolled channels' `min_spend_cents`
    is at most `total_budget_cents`, or `ERR_FLOORS_EXCEED_BUDGET`; and that the
    sum of the rows' `baseline_spend_cents` equals `total_budget_cents` exactly, or
    `ERR_BASELINE_BUDGET_MISMATCH`."
    PRD 3.8: "The scenario moves to `OPTIMIZED` and its `version` increments, and
    the identity that `allocated_total_cents` plus `reallocation_fee_cents` plus
    `unallocated_cents` equals `total_budget_cents` is directly checkable off the
    response."

    Design: Corner/errors/optimize_allocation_gates_rejected
    """
    ctx = fx.published_run(api)
    scenario = fx.create_scenario(api, ctx)
    fx.add_allocation(
        api, scenario["id"], ctx["a_search"]["id"], f.BASELINE_A_SEARCH_CENTS
    )

    # One row exists, and the floors are comfortably inside the budget, so the
    # baseline reconciliation is the rung that answers.
    before = validate_success(
        api.get_budget_scenario(scenario["id"], users.BRAND_PLANNER)
    )
    response = api.optimize_budget_scenario(scenario["id"], users.BRAND_PLANNER)
    validate_error(response, ApiErrorId.ERR_BASELINE_BUDGET_MISMATCH.value, 422)
    still_draft = validate_success(
        api.get_budget_scenario(scenario["id"], users.BRAND_PLANNER)
    )
    assert still_draft["status"] == "DRAFT"
    # The refused optimize wrote nothing, so every cent bucket reads exactly as it
    # did before the request, and the fee the optimizer would have priced is absent.
    expect.assert_version_unchanged(before, still_draft)
    expect.assert_same_row(
        before,
        still_draft,
        "reallocation_fee_cents",
        "allocated_total_cents",
        "unallocated_cents",
        "shifted_total_cents",
    )
    assert still_draft["reallocation_fee_cents"] == 0
    assert still_draft["shifted_total_cents"] == 0

    fx.add_allocation(
        api, scenario["id"], ctx["b_social"]["id"], f.BASELINE_B_SOCIAL_CENTS
    )
    optimized = validate_success(
        api.optimize_budget_scenario(scenario["id"], users.BRAND_PLANNER)
    )
    assert optimized["status"] == "OPTIMIZED"
    assert optimized["reallocation_fee_cents"] == fx.F1_REALLOCATION_FEE_CENTS
    assert optimized["allocated_total_cents"] == fx.F1_ALLOCATED_TOTAL_CENTS
    assert optimized["unallocated_cents"] == fx.F1_UNALLOCATED_CENTS
    expect.assert_budget_conservation(optimized)

    rows = expect.rows_by(fx.allocations_of(api, scenario["id"]), "channel_id")
    a_search = rows[ctx["a_search"]["id"]]
    b_social = rows[ctx["b_social"]["id"]]
    assert a_search["allocated_cents"] == fx.F1_ALLOCATED_A_SEARCH_CENTS
    assert b_social["allocated_cents"] == fx.F1_ALLOCATED_B_SOCIAL_CENTS
    assert a_search["constraint_binding"] == "NONE"
    assert b_social["constraint_binding"] == "NONE"


def test_floors_above_the_whole_budget_outrank_the_baseline_reconciliation(
    api: ApiClient,
):
    """PRD 3.8: "Those five sit at different rungs of the precedence ladder, so a
    request breaking several of them is answered in that order: run state first,
    then posture, then the missing-rows check, then the floors check, then the
    baseline reconciliation."
    PRD 3.8: "Each channel is seeded at its own `min_spend_cents`."

    Design: Corner/errors/optimize_allocation_gates_rejected
    """
    ctx = fx.published_run(api)
    tight = fx.create_scenario(
        api,
        ctx,
        total_budget_cents=_TIGHT_TOTAL_BUDGET_CENTS,
        planning_start_date=_TIGHT_PLANNING_START,
        planning_end_date=_TIGHT_PLANNING_END,
    )
    fx.add_allocation(
        api, tight["id"], ctx["a_search"]["id"], _TIGHT_BASELINE_CENTS
    )
    assert ctx["a_search"]["min_spend_cents"] > _TIGHT_TOTAL_BUDGET_CENTS, (
        "the single enrolled floor must genuinely exceed the whole budget"
    )
    assert _TIGHT_BASELINE_CENTS != _TIGHT_TOTAL_BUDGET_CENTS, (
        "the baseline reconciliation must be broken at the same time"
    )

    before = validate_success(
        api.get_budget_scenario(tight["id"], users.BRAND_PLANNER)
    )
    response = api.optimize_budget_scenario(tight["id"], users.BRAND_PLANNER)
    validate_error(response, ApiErrorId.ERR_FLOORS_EXCEED_BUDGET.value, 422)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_BASELINE_BUDGET_MISMATCH.value
    ), "the baseline reconciliation must not pre-empt the floors check"

    after = validate_success(api.get_budget_scenario(tight["id"], users.BRAND_PLANNER))
    assert after["status"] == "DRAFT"
    # Nothing at all was written by the refused optimize.
    expect.assert_same_row(
        before,
        after,
        "reallocation_fee_cents",
        "allocated_total_cents",
        "unallocated_cents",
        "shifted_total_cents",
    )
    assert after["reallocation_fee_cents"] == 0
    assert after["shifted_total_cents"] == 0
    expect.assert_version_unchanged(before, after)


def _published_run_plus_unmodelled_channel(api: ApiClient) -> Dict[str, Any]:
    """A published two-channel run, and a third channel it never included."""
    ctx = fx.published_run(api)
    ctx["c_video"] = fx.create_channel(api, f.c_video_payload(ctx["market"]["id"]))
    return ctx


def test_report_missing_a_line_for_a_current_contribution_is_refused(api: ApiClient):
    """PRD 3.9: "The array must match the run's decomposition exactly: there must
    be precisely one line per decomposition row of the run whose `is_current` is
    true, and no line for any other channel."
    PRD 3.9: "A missing channel, a duplicated channel, or a channel that has no
    current contribution row on that run all yield `ERR_PLATFORM_LINE_MISMATCH`."

    Design: Corner/errors/reconciliation_report_platform_line_mismatch_rejected
    """
    ctx = _published_run_plus_unmodelled_channel(api)
    assert len(ctx["contributions"]) == 2

    response = api.create_reconciliation_report(
        f.reconciliation_report_payload(
            ctx["run"]["id"],
            _line_bodies(
                [ctx["a_search"]["id"]], [f.PLATFORM_A_SEARCH_MATERIAL_CENTS]
            ),
        ),
        users.ANALYTICS_LEAD,
    )
    validate_error(response, ApiErrorId.ERR_PLATFORM_LINE_MISMATCH.value, 422)
    assert (
        _total_count(
            api.list_reconciliation_reports(
                users.ANALYTICS_LEAD, {"model_run_id": ctx["run"]["id"]}
            )
        )
        == 0
    ), "a refused filing leaves no report behind"


def test_report_with_a_surplus_line_for_an_unmodelled_channel_is_refused(
    api: ApiClient,
):
    """PRD 3.9: "A missing channel, a duplicated channel, or a channel that has no
    current contribution row on that run all yield `ERR_PLATFORM_LINE_MISMATCH`."
    PRD 3.9: "The array must match the run's decomposition exactly: there must be
    precisely one line per decomposition row of the run whose `is_current` is true,
    and no line for any other channel."

    Design: Corner/errors/reconciliation_report_platform_line_mismatch_rejected
    """
    ctx = _published_run_plus_unmodelled_channel(api)

    # C_VIDEO exists and resolves, so this is not a missing-channel refusal; it
    # simply has no decomposition row on this run.
    response = api.create_reconciliation_report(
        f.reconciliation_report_payload(
            ctx["run"]["id"],
            _line_bodies(
                [ctx["a_search"]["id"], ctx["b_social"]["id"], ctx["c_video"]["id"]],
                [
                    f.PLATFORM_A_SEARCH_MATERIAL_CENTS,
                    f.PLATFORM_B_SOCIAL_MATERIAL_CENTS,
                    _C_VIDEO_PLATFORM_CENTS,
                ],
            ),
        ),
        users.ANALYTICS_LEAD,
    )
    validate_error(response, ApiErrorId.ERR_PLATFORM_LINE_MISMATCH.value, 422)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_MEDIA_CHANNEL_NOT_FOUND.value
    ), "a resolvable channel with no contribution row is a mismatch, not a miss"
    assert (
        _total_count(
            api.list_reconciliation_reports(
                users.ANALYTICS_LEAD, {"model_run_id": ctx["run"]["id"]}
            )
        )
        == 0
    )


def test_exactly_one_line_per_current_contribution_files_on_the_raw_basis(
    api: ApiClient,
):
    """PRD 3.9: "When the run's `calibration_status` is `CALIBRATED` the `basis` is
    `CALIBRATED` and each channel's model figure is its
    `calibrated_contribution_revenue_cents`; in every other admissible case the
    `basis` is `RAW` and the model figure is its `contribution_revenue_cents`."
    PRD 3.9: "A new report is created in `status` `CURRENT`."
    PRD 3.9: "The lines are processed in ascending `channel_code` order of the
    channel they name."
    PRD 3.9: "Three totals are then summed across the lines:
    `platform_reported_revenue_cents` from the platform figures,
    `model_attributed_revenue_cents` from the model figures, and
    `total_variance_cents` from the per-line variances."

    Design: Corner/errors/reconciliation_report_platform_line_mismatch_rejected
    """
    ctx = _published_run_plus_unmodelled_channel(api)
    validate_error(
        api.create_reconciliation_report(
            f.reconciliation_report_payload(
                ctx["run"]["id"],
                _line_bodies(
                    [ctx["a_search"]["id"]], [f.PLATFORM_A_SEARCH_MATERIAL_CENTS]
                ),
            ),
            users.ANALYTICS_LEAD,
        ),
        ApiErrorId.ERR_PLATFORM_LINE_MISMATCH.value,
        422,
    )

    report = validate_success(
        api.create_reconciliation_report(
            f.reconciliation_report_payload(
                ctx["run"]["id"],
                _line_bodies(
                    [ctx["a_search"]["id"], ctx["b_social"]["id"]],
                    [
                        f.PLATFORM_A_SEARCH_MATERIAL_CENTS,
                        f.PLATFORM_B_SOCIAL_MATERIAL_CENTS,
                    ],
                ),
            ),
            users.ANALYTICS_LEAD,
        ),
        201,
    )
    assert report["basis"] == "RAW"
    assert report["status"] == "CURRENT"
    assert (
        report["platform_reported_revenue_cents"]
        == fx.F1_RAW_PLATFORM_REPORTED_CENTS
    )
    assert report["model_attributed_revenue_cents"] == fx.F1_RAW_MODEL_ATTRIBUTED_CENTS
    expect.assert_reconciliation_report(report)
    assert [line["channel_id"] for line in report["variance_lines"]] == [
        ctx["a_search"]["id"],
        ctx["b_social"]["id"],
    ], "the lines follow ascending channel_code, which is A_SEARCH then B_SOCIAL"


def test_calibration_multiplier_below_the_floor_is_refused_not_clamped(api: ApiClient):
    """PRD 3.7: "`calibration_multiplier` is then `experiment_lift_pct` divided by
    `model_implied_lift_pct`, rounded half-up to four decimal places, and
    constrained to lie within the closed range from 0.25 to 4.00."
    PRD 3.7: "A raw quotient falling outside that range is not silently clamped
    into it: the record is refused with
    `ERR_CALIBRATION_MULTIPLIER_OUT_OF_RANGE` and nothing is created, on the
    reasoning that a discrepancy of more than fourfold in either direction
    indicates a broken specification rather than an attribution bias worth
    correcting."
    PRD 3.7: "The model's own view of the same quantity, `model_implied_lift_pct`,
    is computed from the run's current decomposition row for that channel — the one
    whose `is_current` is true — as one hundred multiplied by that row's
    `contribution_units`, divided by the difference between the run's
    `modeled_sales_units` and that same `contribution_units`, rounded half-up to
    four decimal places."

    Design: Corner/errors/calibration_multiplier_out_of_range_rejected
    """
    ctx = fx.published_run(api)
    experiment = fx.read_out_experiment(
        api,
        ctx,
        readout_overrides={"treatment_conversions": _WEAK_TREATMENT_CONVERSIONS},
    )
    assert _num(experiment["measured_lift_pct"]) == _num(_WEAK_MEASURED_LIFT_PCT)
    assert _num(experiment["measured_lift_pct"]) < _num(
        fx.F1_MODEL_IMPLIED_LIFT_PCT
    ) * _num(k.CALIBRATION_MULTIPLIER_FLOOR), (
        "the readout must genuinely fall under the floor of the closed range"
    )

    # A current concurrency token, so the version check cannot mask the range one.
    version_before = fx.run_version(api, ctx["run"]["id"])
    response = api.create_calibration_record(
        f.calibration_record_payload(
            ctx["run"]["id"],
            ctx["a_search"]["id"],
            experiment["id"],
            version_before,
        ),
        users.MODELER,
    )
    validate_error(
        response, ApiErrorId.ERR_CALIBRATION_MULTIPLIER_OUT_OF_RANGE.value, 422
    )
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_STALE_MODEL_RUN_VERSION.value
    ), "a current version token must not be reported as stale"

    assert (
        _total_count(
            api.list_calibration_records(
                users.MODELER, {"model_run_id": ctx["run"]["id"]}
            )
        )
        == 0
    ), "the refused record was not created"

    run = fx.refresh_run(api, ctx)
    assert run["calibration_status"] == "NOT_REQUIRED"
    assert run["version"] == version_before
    assert _num(run["baseline_sales_units"]) == _num(fx.F1_EFFECT_BASELINE_UNITS)

    rows = _contribution_units_by_code(api, ctx["run"]["id"], ctx)
    assert _num(rows["A_SEARCH"]["contribution_units"]) == _num(
        fx.F1_EFFECT_CONTRIBUTION_A_SEARCH
    ), "nothing was recalibrated"
    market = fx.refresh_market(api, ctx)
    assert market["data_posture"] == "OPEN"
