"""Which error a single request gets when it breaks two rules at once.

The contract fixes one ladder for the whole service and calls out the collisions
that a single well-formed request can reach. Two of them live here: opening a
budget scenario against an unpublished run with a budget above the market's
ceiling, and locking an experiment design that is both underpowered and over the
holdout-share ceiling. Each collision is tested twice over — once with both rules
broken, to see which error is reported, and once with only the losing rule
broken, so that the ordering claim is falsifiable rather than vacuous.
"""

from decimal import Decimal

from test_helpers import (
    ApiClient,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import assertions as expect
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId

# A budget one thousand million cents above the canonical market's
# `annual_budget_ceiling_cents` of 5000000000.
_OVER_CEILING_BUDGET_CENTS = 6_000_000_000

# Arms of this size are 30 percent of the canonical ten-million-person market,
# so the planned holdout is over the twenty-percent ceiling.
_OVER_SHARE_ARM_POPULATION = 1_500_000

# Arms of this size land the planned holdout exactly on the ceiling.
_ON_CAP_ARM_POPULATION = 1_000_000

# A relative effect this small leaves the design underpowered whatever the arms.
_UNDERPOWERED_MDE_PCT = 1.0

# A relative effect this large clears the power gate on the arms above.
_POWERED_MDE_PCT = 5.0

# What the on-cap, adequately powered design freezes onto the row.
_ON_CAP_POWER_INDEX = 5.0508
_ON_CAP_COMPUTED_POWER = 0.9500


def _scenario_count(api: ApiClient, market_id: str) -> int:
    """How many budget scenarios the market holds, per the list endpoint."""
    _, meta = validate_paginated(
        api.list_budget_scenarios(users.BRAND_PLANNER, {"market_id": market_id})
    )
    return meta["total_count"]


def _geo_design(api: ApiClient, ctx: dict, arm_population: int, mde_pct: float) -> dict:
    """A drafted geographic-holdout design on the market's A_SEARCH channel."""
    return fx.create_experiment(
        api,
        ctx,
        geo=True,
        planned_population=arm_population,
        minimum_detectable_effect_pct=mde_pct,
    )


def test_unpublished_run_outranks_budget_ceiling_on_scenario_create(api: ApiClient):
    """PRD 2.12: "Opening a budget scenario against a run that is not published
    *and* with a budget above the market's ceiling returns
    `ERR_MODEL_RUN_NOT_PUBLISHED`, not `ERR_BUDGET_CEILING_EXCEEDED` — the
    run-state check outranks the fiscal ceiling."
    PRD 3.8: "Separately, `total_budget_cents` may not exceed the market's
    `annual_budget_ceiling_cents`, or `ERR_BUDGET_CEILING_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_budget_scenario_create
    """
    ctx = fx.fitted_run(api)
    run = ctx["run"]
    assert run["publication_status"] == "UNPUBLISHED"
    assert run["fit_status"] == "FITTED"

    response = api.create_budget_scenario(
        f.budget_scenario_payload(
            ctx["market"]["id"],
            run["id"],
            total_budget_cents=_OVER_CEILING_BUDGET_CENTS,
        ),
        users.BRAND_PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_MODEL_RUN_NOT_PUBLISHED.value, 409)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_BUDGET_CEILING_EXCEEDED.value
    ), "the fiscal ceiling must not pre-empt the run-state refusal"

    market = validate_success(
        api.get_market(ctx["market"]["id"], users.BRAND_PLANNER)
    )
    assert _OVER_CEILING_BUDGET_CENTS > market["annual_budget_ceiling_cents"], (
        "the payload must genuinely break the fiscal ceiling as well"
    )
    assert _scenario_count(api, ctx["market"]["id"]) == 0, (
        "a refused create must leave no budget scenario behind"
    )


def test_budget_ceiling_is_reached_once_the_run_publishes(api: ApiClient):
    """PRD 3.8: "Those two checks collide on a single request often enough to be
    worth restating: the run-state check outranks the fiscal ceiling, so a
    request that breaks both is answered with `ERR_MODEL_RUN_NOT_PUBLISHED`."
    PRD 3.8: "Separately, `total_budget_cents` may not exceed the market's
    `annual_budget_ceiling_cents`, or `ERR_BUDGET_CEILING_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_budget_scenario_create
    """
    ctx = fx.fitted_run(api)
    payload = f.budget_scenario_payload(
        ctx["market"]["id"],
        ctx["run"]["id"],
        total_budget_cents=_OVER_CEILING_BUDGET_CENTS,
    )

    while_unpublished = api.create_budget_scenario(payload, users.BRAND_PLANNER)
    validate_error(
        while_unpublished, ApiErrorId.ERR_MODEL_RUN_NOT_PUBLISHED.value, 409
    )

    fx.validated_run(api, ctx)
    fx.published_run(api, ctx)
    assert ctx["run"]["publication_status"] == "PUBLISHED"
    assert ctx["run"]["fit_status"] == "FITTED"

    once_published = api.create_budget_scenario(payload, users.BRAND_PLANNER)
    validate_error(once_published, ApiErrorId.ERR_BUDGET_CEILING_EXCEEDED.value, 422)
    assert _scenario_count(api, ctx["market"]["id"]) == 0, (
        "neither refusal may leave a budget scenario behind"
    )


def test_unpublished_run_alone_refuses_a_scenario_within_the_ceiling(api: ApiClient):
    """PRD 3.8: "The referenced run must already be the market's published,
    fitted model: a run that is not both `PUBLISHED` and `FITTED` is refused with
    `ERR_MODEL_RUN_NOT_PUBLISHED`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_budget_scenario_create
    """
    ctx = fx.fitted_run(api)
    market = validate_success(api.get_market(ctx["market"]["id"], users.BRAND_PLANNER))
    assert (
        f.SCENARIO_TOTAL_BUDGET_CENTS <= market["annual_budget_ceiling_cents"]
    ), "this payload must break the run-state rule and nothing else"

    response = api.create_budget_scenario(
        f.budget_scenario_payload(ctx["market"]["id"], ctx["run"]["id"]),
        users.BRAND_PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_MODEL_RUN_NOT_PUBLISHED.value, 409)
    assert _scenario_count(api, ctx["market"]["id"]) == 0


def test_underpowered_outranks_holdout_share_on_lock_design(api: ApiClient):
    """PRD 2.12: "Locking an experiment design that is both underpowered *and*
    over the holdout-share ceiling returns `ERR_EXPERIMENT_UNDERPOWERED`, not
    `ERR_HOLDOUT_SHARE_EXCEEDED`."
    PRD 3.6: "Then the **power gate** runs, and it runs before the holdout-share
    ceiling — an experiment that is simultaneously underpowered and over the
    share ceiling answers `ERR_EXPERIMENT_UNDERPOWERED`, never
    `ERR_HOLDOUT_SHARE_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_experiment_lock_design
    """
    ctx = fx.market_with_channels(api)
    experiment = _geo_design(
        api, ctx, _OVER_SHARE_ARM_POPULATION, _UNDERPOWERED_MDE_PCT
    )
    market = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert market["held_out_population"] == 0
    planned = (
        experiment["planned_treatment_population"]
        + experiment["planned_control_population"]
    )
    assert planned * 100 > 20 * market["total_population"], (
        "the design must genuinely break the twenty-percent ceiling as well"
    )

    response = api.lock_design(experiment["id"], users.EXPERIMENT_DESIGNER)
    validate_error(response, ApiErrorId.ERR_EXPERIMENT_UNDERPOWERED.value, 422)
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_HOLDOUT_SHARE_EXCEEDED.value
    ), "the share ceiling must not pre-empt the power gate"

    after = validate_success(
        api.get_experiment(experiment["id"], users.EXPERIMENT_DESIGNER)
    )
    assert after["status"] == "DRAFT", "a refused lock leaves the design in DRAFT"


def test_holdout_share_alone_refuses_an_adequately_powered_lock(api: ApiClient):
    """PRD 3.6: "For a `GEO_HOLDOUT` design, the sum of the market's current
    `held_out_population`, the `planned_treatment_population` and the
    `planned_control_population`, multiplied by one hundred, must be at most
    twenty multiplied by the market's `total_population` — in other words the
    market may never plan to hold out more than twenty percent of its
    addressable people."
    PRD 3.6: "A breach is `ERR_HOLDOUT_SHARE_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_experiment_lock_design
    """
    ctx = fx.market_with_channels(api)
    experiment = _geo_design(api, ctx, _OVER_SHARE_ARM_POPULATION, _POWERED_MDE_PCT)

    response = api.lock_design(experiment["id"], users.EXPERIMENT_DESIGNER)
    validate_error(response, ApiErrorId.ERR_HOLDOUT_SHARE_EXCEEDED.value, 422)

    after = validate_success(
        api.get_experiment(experiment["id"], users.EXPERIMENT_DESIGNER)
    )
    assert after["status"] == "DRAFT"


def test_powered_design_on_the_share_cap_locks(api: ApiClient):
    """PRD 3.6: "A successful lock freezes `power_index` and `computed_power` onto
    the row, sets `status` to `DESIGN_LOCKED` and increments `version`."
    PRD 3.6: "A `GEO_HOLDOUT` design leaves both realised populations at 0 until
    it consumes actual cells."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_experiment_lock_design
    """
    ctx = fx.market_with_channels(api)
    experiment = _geo_design(api, ctx, _ON_CAP_ARM_POPULATION, _POWERED_MDE_PCT)

    locked = validate_success(
        api.lock_design(experiment["id"], users.EXPERIMENT_DESIGNER)
    )
    assert locked["status"] == "DESIGN_LOCKED"
    assert Decimal(str(locked["power_index"])) == Decimal(str(_ON_CAP_POWER_INDEX))
    assert Decimal(str(locked["computed_power"])) == Decimal(
        str(_ON_CAP_COMPUTED_POWER)
    )
    expect.assert_power_step(locked)
    assert locked["treatment_population"] == 0
    assert locked["control_population"] == 0

    market = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert market["held_out_population"] == 0, (
        "locking a design reserves no population; only cell assignment does"
    )
