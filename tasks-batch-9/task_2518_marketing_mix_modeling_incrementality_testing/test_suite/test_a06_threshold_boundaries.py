"""Numeric thresholds probed one unit either side of the value that decides them.

Two thresholds are exercised here, on two different metrics and two different
endpoints. The first is the step table that turns a `power_index` into a
`computed_power`, whose rungs are strictly less-than, so an index that lands
exactly on a rung takes the higher step. The second is the holdout-share ceiling
that assign-cells re-evaluates in exact integers, where a hundred surplus people
still round to the same two-decimal reporting percentage yet break the ceiling.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, List, Tuple

from test_helpers import ApiClient, validate_error, validate_success
from test_helpers import assertions as expect
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_errors import ApiErrorId

# Three relative effects over identical arms of 245000 at a baseline conversion
# rate of 0.0200. They put `power_index` exactly on the 2.5000 rung, exactly on
# the 2.0000 rung below it, and clear of both.
_MDE_ON_BOUNDARY_PCT = 5.0
_MDE_BELOW_BOUNDARY_PCT = 4.0
_MDE_ABOVE_BOUNDARY_PCT = 6.0

# The realised arms an AUDIENCE_SPLIT lock copies from the planned ones.
_AUDIENCE_ARM_POPULATION = 245_000

# The cell pool the integer ceiling is measured against: two twins of a million
# people and a third cell carrying exactly one hundred people more.
_CEILING_CELL_SPECS: List[Tuple[str, int]] = [
    ("GC01", fx.F1_CEILING_CELL_POPULATION),
    ("GC02", fx.F1_CEILING_CELL_POPULATION),
    ("GC03", fx.F1_CEILING_CELL_POPULATION_OVER),
]

# A pool whose pair falls one single person short of the ceiling.
_UNDER_CEILING_CELL_POPULATION = 999_999
_UNDER_CEILING_CELL_SPECS: List[Tuple[str, int]] = [
    ("GC01", fx.F1_CEILING_CELL_POPULATION),
    ("GC02", _UNDER_CEILING_CELL_POPULATION),
]
_UNDER_CEILING_HELD_OUT_POPULATION = 1_999_999

# Every cell of the three-cell pool counts towards `celled_population`.
_CELLED_POPULATION_OF_POOL = 3_000_100

# The planned arms of the geographic design, which sit exactly on the ceiling at
# lock time and so let the trigger reach the assign-cells re-evaluation.
_GEO_ARM_POPULATION = 1_000_000


def _audience_design(api: ApiClient, ctx: Dict[str, Any], mde_pct: float) -> Dict[str, Any]:
    """A drafted audience-split design whose only moving part is the effect size."""
    return fx.create_experiment(
        api, ctx, minimum_detectable_effect_pct=mde_pct
    )


def _locked_geo_design_with_cells(
    api: ApiClient, cell_specs: List[Tuple[str, int]]
) -> Dict[str, Any]:
    """A market with a cell pool and one geographic design already locked."""
    ctx = fx.market_with_channels(api)
    ctx["cells"] = fx.create_geo_cells(api, ctx["market"]["id"], cell_specs)
    ctx["experiment"] = fx.locked_experiment(
        api, ctx, geo=True, planned_population=_GEO_ARM_POPULATION
    )
    assert ctx["experiment"]["status"] == "DESIGN_LOCKED"
    return ctx


def test_power_index_exactly_on_the_rung_locks_the_design(api: ApiClient):
    """PRD 3.6: "The strictness of those bounds is observable at the acceptance
    threshold: a `power_index` of exactly 2.5000 lands on the 0.8000 row and
    passes, while 2.4999 lands on 0.7500 and fails."
    PRD 3.6: "For an `AUDIENCE_SPLIT` design it also copies
    `planned_treatment_population` into `treatment_population` and
    `planned_control_population` into `control_population`, because that design
    has nothing further to enlist."

    Design: Difficulty/boundary_precision_check/power_index_exact_boundary_on_lock_design
    """
    ctx = fx.market_with_channels(api)
    experiment = _audience_design(api, ctx, _MDE_ON_BOUNDARY_PCT)

    locked = validate_success(
        api.lock_design(experiment["id"], users.EXPERIMENT_DESIGNER)
    )
    assert Decimal(str(locked["power_index"])) == Decimal(
        str(fx.F1_POWER_INDEX_BOUNDARY)
    )
    assert Decimal(str(locked["computed_power"])) == Decimal(
        str(fx.F1_COMPUTED_POWER_BOUNDARY)
    )
    expect.assert_power_step(locked)
    assert locked["status"] == "DESIGN_LOCKED"
    assert locked["treatment_population"] == _AUDIENCE_ARM_POPULATION
    assert locked["control_population"] == _AUDIENCE_ARM_POPULATION


def test_power_index_on_the_rung_below_is_underpowered(api: ApiClient):
    """PRD 3.6: "`computed_power` must be at least 0.80, or the lock is refused
    with `ERR_EXPERIMENT_UNDERPOWERED` (HTTP 422)."
    PRD 3.6: "That index is then read against a step table to produce
    `computed_power`, rounded to four decimal places, where each bound is
    **strictly** less-than and the first matching row wins: a `power_index` below
    1.0000 gives power 0.2000; below 1.6000 gives 0.4500; below 2.0000 gives
    0.6500; below 2.5000 gives 0.7500; below 2.8000 gives 0.8000; below 3.2400
    gives 0.9000; and anything at or above 3.2400 gives 0.9500."

    Design: Difficulty/boundary_precision_check/power_index_exact_boundary_on_lock_design
    """
    ctx = fx.market_with_channels(api)
    experiment = _audience_design(api, ctx, _MDE_BELOW_BOUNDARY_PCT)

    response = api.lock_design(experiment["id"], users.EXPERIMENT_DESIGNER)
    validate_error(response, ApiErrorId.ERR_EXPERIMENT_UNDERPOWERED.value, 422)
    assert Decimal(
        str(expect.expected_power_for(fx.F1_POWER_INDEX_BELOW))
    ) == Decimal(str(fx.F1_COMPUTED_POWER_BELOW)), (
        "an index of 2.0000 belongs to the 0.7500 row, which is under the gate"
    )

    after = validate_success(
        api.get_experiment(experiment["id"], users.EXPERIMENT_DESIGNER)
    )
    assert after["status"] == "DRAFT", "the refused transition wrote no new state"
    assert after["treatment_population"] == 0
    assert after["control_population"] == 0


def test_power_index_above_the_rung_locks_on_the_higher_step(api: ApiClient):
    """PRD 3.6: "That index is then read against a step table to produce
    `computed_power`, rounded to four decimal places, where each bound is
    **strictly** less-than and the first matching row wins: a `power_index` below
    1.0000 gives power 0.2000; below 1.6000 gives 0.4500; below 2.0000 gives
    0.6500; below 2.5000 gives 0.7500; below 2.8000 gives 0.8000; below 3.2400
    gives 0.9000; and anything at or above 3.2400 gives 0.9500."
    PRD 3.6: "A successful lock freezes `power_index` and `computed_power` onto
    the row, sets `status` to `DESIGN_LOCKED` and increments `version`."

    Design: Difficulty/boundary_precision_check/power_index_exact_boundary_on_lock_design
    """
    ctx = fx.market_with_channels(api)
    experiment = _audience_design(api, ctx, _MDE_ABOVE_BOUNDARY_PCT)

    locked = validate_success(
        api.lock_design(experiment["id"], users.EXPERIMENT_DESIGNER)
    )
    assert Decimal(str(locked["power_index"])) == Decimal(
        str(fx.F1_POWER_INDEX_ABOVE)
    )
    assert Decimal(str(locked["computed_power"])) == Decimal(
        str(fx.F1_COMPUTED_POWER_ABOVE)
    )
    expect.assert_power_step(locked)
    assert locked["status"] == "DESIGN_LOCKED"
    assert locked["version"] == experiment["version"] + 1


def test_assign_cells_one_hundred_people_over_the_integer_ceiling_is_refused(
    api: ApiClient,
):
    """PRD 3.6: "Finally the holdout-share ceiling is re-evaluated with real
    numbers: the market's current `held_out_population` plus the summed
    `population` of the cells named in this request, multiplied by one hundred,
    must be at most twenty multiplied by `total_population`, again compared as
    exact integers, or `ERR_HOLDOUT_SHARE_EXCEEDED`."
    PRD 3.6: "The comparison is carried out in exact integers on both sides and
    never through the two-decimal `held_out_population_pct`, which exists only
    for reporting."

    Design: Difficulty/boundary_precision_check/holdout_share_exact_integer_ceiling_on_assign_cells
    """
    ctx = _locked_geo_design_with_cells(api, _CEILING_CELL_SPECS)
    twin, _, surplus = ctx["cells"]
    market = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    requested = twin["population"] + surplus["population"]
    assert requested * 100 > 20 * market["total_population"]
    # The very same pair reads as 20.00 once rounded to two decimals, which is
    # why the ceiling may not be evaluated on the reporting percentage.
    rounded_share = (
        Decimal(100 * requested) / Decimal(market["total_population"])
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert rounded_share == Decimal("20.00")

    response = api.assign_cells(
        ctx["experiment"]["id"],
        {"treatment_cell_ids": [twin["id"]], "control_cell_ids": [surplus["id"]]},
        users.EXPERIMENT_DESIGNER,
    )
    validate_error(response, ApiErrorId.ERR_HOLDOUT_SHARE_EXCEEDED.value, 422)

    for cell in (twin, surplus):
        after = validate_success(
            api.get_geo_cell(cell["id"], users.EXPERIMENT_DESIGNER)
        )
        assert after["assignment_state"] == "UNASSIGNED"
        assert after["assigned_experiment_id"] is None

    experiment = validate_success(
        api.get_experiment(ctx["experiment"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert experiment["status"] == "DESIGN_LOCKED"
    assert experiment["treatment_population"] == 0
    assert experiment["control_population"] == 0

    market = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert market["held_out_population"] == 0
    assert Decimal(str(market["held_out_population_pct"])) == Decimal("0.00")


def test_assign_cells_exactly_on_the_integer_ceiling_succeeds(api: ApiClient):
    """PRD 3.6: "Finally the holdout-share ceiling is re-evaluated with real
    numbers: the market's current `held_out_population` plus the summed
    `population` of the cells named in this request, multiplied by one hundred,
    must be at most twenty multiplied by `total_population`, again compared as
    exact integers, or `ERR_HOLDOUT_SHARE_EXCEEDED`."
    PRD 3.6: "On success, each cell named in `treatment_cell_ids` moves to
    `assignment_state` `TREATMENT` and each cell named in `control_cell_ids` moves
    to `CONTROL`, both recording the experiment in their `assigned_experiment_id`;
    each such cell adds its `population` to the market's `held_out_population`."
    PRD 3.1: "`celled_population` is the summed `population` of every geographic
    cell belonging to the market, regardless of assignment."

    Design: Difficulty/boundary_precision_check/holdout_share_exact_integer_ceiling_on_assign_cells
    """
    ctx = _locked_geo_design_with_cells(api, _CEILING_CELL_SPECS)
    treatment, control, untouched = ctx["cells"]
    market = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    requested = treatment["population"] + control["population"]
    assert requested * 100 == 20 * market["total_population"]

    assigned = validate_success(
        api.assign_cells(
            ctx["experiment"]["id"],
            {
                "treatment_cell_ids": [treatment["id"]],
                "control_cell_ids": [control["id"]],
            },
            users.EXPERIMENT_DESIGNER,
        )
    )
    assert assigned["status"] == "CELLS_ASSIGNED"
    assert assigned["treatment_population"] == fx.F1_CEILING_CELL_POPULATION
    assert assigned["control_population"] == fx.F1_CEILING_CELL_POPULATION

    treatment_after = validate_success(
        api.get_geo_cell(treatment["id"], users.EXPERIMENT_DESIGNER)
    )
    assert treatment_after["assignment_state"] == "TREATMENT"
    assert treatment_after["assigned_experiment_id"] == ctx["experiment"]["id"]
    control_after = validate_success(
        api.get_geo_cell(control["id"], users.EXPERIMENT_DESIGNER)
    )
    assert control_after["assignment_state"] == "CONTROL"
    assert control_after["assigned_experiment_id"] == ctx["experiment"]["id"]
    surplus_after = validate_success(
        api.get_geo_cell(untouched["id"], users.EXPERIMENT_DESIGNER)
    )
    assert surplus_after["assignment_state"] == "UNASSIGNED"

    market = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert market["held_out_population"] == fx.F1_HOLDOUT_CEILING_POPULATION
    assert Decimal(str(market["held_out_population_pct"])) == Decimal("20.00")
    assert market["celled_population"] == _CELLED_POPULATION_OF_POOL


def test_assign_cells_one_person_below_the_integer_ceiling_succeeds(api: ApiClient):
    """PRD 3.6: "Finally the holdout-share ceiling is re-evaluated with real
    numbers: the market's current `held_out_population` plus the summed
    `population` of the cells named in this request, multiplied by one hundred,
    must be at most twenty multiplied by `total_population`, again compared as
    exact integers, or `ERR_HOLDOUT_SHARE_EXCEEDED`."
    PRD 3.6: "The experiment's `treatment_population` becomes the summed
    population of its treatment cells and its `control_population` the summed
    population of its control cells."

    Design: Difficulty/boundary_precision_check/holdout_share_exact_integer_ceiling_on_assign_cells
    """
    ctx = _locked_geo_design_with_cells(api, _UNDER_CEILING_CELL_SPECS)
    treatment, control = ctx["cells"]
    market = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    requested = treatment["population"] + control["population"]
    assert requested * 100 < 20 * market["total_population"]

    assigned = validate_success(
        api.assign_cells(
            ctx["experiment"]["id"],
            {
                "treatment_cell_ids": [treatment["id"]],
                "control_cell_ids": [control["id"]],
            },
            users.EXPERIMENT_DESIGNER,
        )
    )
    assert assigned["status"] == "CELLS_ASSIGNED"
    assert assigned["treatment_population"] == fx.F1_CEILING_CELL_POPULATION
    assert assigned["control_population"] == _UNDER_CEILING_CELL_POPULATION

    market = validate_success(
        api.get_market(ctx["market"]["id"], users.EXPERIMENT_DESIGNER)
    )
    assert market["held_out_population"] == _UNDER_CEILING_HELD_OUT_POPULATION
