"""
Stress overlays and the two leverage paths every scenario is run through.

The projections under test are the canonical Cascade Charter Bank plan: opening
tier 1 capital of 4,000,000,000 cents, assets of 25, 34 and 43 billion cents,
loans of 15, 21 and 28 billion cents, and net income of -250,000,000,
+120,000,000 and +460,000,000 cents across the three stress years.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import COUNSEL_HEADERS, fixtures as fx
from test_helpers.assertions import (
    assert_fields_equal,
    assert_integer_bps,
    assert_system_fields,
)
from test_helpers.factories import stress_scenario_payload
from test_helpers.types import (
    PLAN_DRAFT,
    PLAN_SUBMITTED,
    SCENARIO_ADVERSE,
    SCENARIO_SEVERELY_ADVERSE,
    VARIANT_DYNAMIC,
    VERDICT_ADEQUATE,
)


# ---------------------------------------------------------------------------
# Difficulty / dual_variant_calc
# ---------------------------------------------------------------------------
def test_severely_adverse_scenario_stores_both_variant_paths(api, composition_met_group):
    """
    A severely adverse overlay is walked down both balance-sheet variants and both
    outcomes are persisted side by side. The static run freezes assets and loans at
    the year-one projection so its denominator never grows and its minimum lands at
    1246 basis points with no breach year, while the dynamic run follows the plan's
    own growth and sinks to 636 basis points, breaching in year three.

    PRD: "Every scenario is run through the leverage path **twice**, and both results are stored."
    PRD: "Both pairs remain visible on the scenario, so the non-governing path is auditable even though it does not decide anything."

    Design: Difficulty/dual_variant_calc/stress_path_static_vs_dynamic_divergence_on_severely_adverse
    """
    world = composition_met_group
    plan_id = fx.add_business_plan(api, world)
    response = api.create_stress_scenario(
        plan_id,
        stress_scenario_payload(
            SCENARIO_SEVERELY_ADVERSE,
            credit_loss_rate_bps=185,
            nim_compression_bps=40,
            expense_overrun_cents=0,
        ),
        COUNSEL_HEADERS,
    )
    scenario = get_success_data(response, expected_status=201)

    assert_system_fields(scenario, expected_version=1)
    assert_integer_bps(
        scenario, "static_min_leverage_ratio_bps", "dynamic_min_leverage_ratio_bps"
    )
    assert_fields_equal(
        scenario,
        static_min_leverage_ratio_bps=1246,
        static_breach_year_index=0,
        dynamic_min_leverage_ratio_bps=636,
        dynamic_breach_year_index=3,
    )
    assert (
        scenario["static_min_leverage_ratio_bps"]
        - scenario["dynamic_min_leverage_ratio_bps"]
        == 610
    ), "the two variant minima must diverge by exactly 610 basis points"


def test_severely_adverse_scenario_is_governed_by_the_dynamic_variant(
    api, composition_met_group
):
    """
    The scenario code alone picks the governing run, so a severely adverse overlay is
    judged on its dynamic path — 636 basis points breaching in year three — and never
    on the far more flattering 1246 the frozen balance sheet produced. The parent plan
    rolls that governing figure up as its worst governing minimum and counts the
    overlay as one breaching scenario.

    PRD: "Which run **governs** is decided purely by the scenario code: `governing_variant` is `STATIC_BALANCE_SHEET` when `scenario_code` is `BASELINE`, and `DYNAMIC_GROWTH` when `scenario_code` is `ADVERSE` or `SEVERELY_ADVERSE`."
    PRD: "The breach year index is the smallest year among one, two and three whose ratio is below 800 basis points, and is 0 when no year breaches."

    Design: Difficulty/dual_variant_calc/stress_path_static_vs_dynamic_divergence_on_severely_adverse
    """
    world = composition_met_group
    plan_id = fx.add_business_plan(api, world)
    scenario = get_success_data(
        api.create_stress_scenario(
            plan_id,
            stress_scenario_payload(
                SCENARIO_SEVERELY_ADVERSE,
                credit_loss_rate_bps=185,
                nim_compression_bps=40,
                expense_overrun_cents=0,
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )

    assert_fields_equal(
        scenario,
        governing_variant=VARIANT_DYNAMIC,
        governing_min_leverage_ratio_bps=636,
        governing_breach_year_index=3,
    )
    assert scenario["governing_min_leverage_ratio_bps"] != 1246, (
        "the static path must not decide a severely adverse scenario"
    )

    plan = fx.read_plan(api, plan_id)
    assert_fields_equal(
        plan,
        stress_scenario_count=1,
        breach_scenario_count=1,
        worst_governing_min_leverage_ratio_bps=636,
    )


# ---------------------------------------------------------------------------
# Difficulty / boundary_precision_check
# ---------------------------------------------------------------------------
def test_governing_minimum_of_exactly_800_bps_passes_plan_submission(
    api, boundary_plan_group
):
    """
    An overlay whose governing dynamic minimum lands on exactly 800 basis points sits
    on the stress floor rather than under it, so submission is allowed through. The
    year-three ratio computes to 800.55 and floors to 800, the frozen path is a far
    healthier 1378, and no year is recorded as breaching.

    PRD: "Every stress scenario of the plan must have a `governing_min_leverage_ratio_bps` of at least 800 basis points — exactly 800 passes and 799 fails (`ERR_STRESS_CAPITAL_SHORTFALL`)."

    Design: Difficulty/boundary_precision_check/stress_floor_exactly_800_bps_passes_submit_and_799_fails
    """
    world = boundary_plan_group
    scenario = get_success_data(
        api.create_stress_scenario(
            world["b1"],
            stress_scenario_payload(
                SCENARIO_ADVERSE,
                credit_loss_rate_bps=75,
                nim_compression_bps=40,
                expense_overrun_cents=0,
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        scenario,
        dynamic_min_leverage_ratio_bps=800,
        dynamic_breach_year_index=0,
        static_min_leverage_ratio_bps=1378,
        governing_variant=VARIANT_DYNAMIC,
        governing_min_leverage_ratio_bps=800,
        governing_breach_year_index=0,
    )

    plan = get_success_data(api.submit_business_plan(world["b1"], world["lead_headers"]))
    assert_fields_equal(
        plan,
        status=PLAN_SUBMITTED,
        worst_governing_min_leverage_ratio_bps=800,
        breach_scenario_count=0,
    )


def test_capital_adequacy_on_the_floor_plan_passes_on_equality(api, boundary_plan_group):
    """
    With year-three loans of 27,950,000,000 cents against year-three assets of
    43,000,000,000, the loan concentration lands on exactly the 6500 basis point trip
    point, so no add-on is charged, the required leverage stays at the bare national
    tier of 800, and the plan's worst governing minimum of 800 clears it on equality.

    PRD: "Equality passes."

    Design: Difficulty/boundary_precision_check/stress_floor_exactly_800_bps_passes_submit_and_799_fails
    """
    world = boundary_plan_group
    fx.add_stress_scenario(
        api,
        world["b1"],
        SCENARIO_ADVERSE,
        credit_loss_rate_bps=75,
        nim_compression_bps=40,
        expense_overrun_cents=0,
    )
    get_success_data(api.submit_business_plan(world["b1"], world["lead_headers"]))

    derivation = get_success_data(
        api.get_capital_adequacy(
            world["group_id"], COUNSEL_HEADERS, params={"business_plan_id": world["b1"]}
        )
    )
    assert_fields_equal(
        derivation,
        concentration_bps=6500,
        concentration_add_on_bps=0,
        base_required_bps=800,
        risk_add_on_bps=0,
        required_leverage_bps=800,
        worst_governing_min_leverage_ratio_bps=800,
        verdict=VERDICT_ADEQUATE,
    )


def test_governing_minimum_of_799_bps_fails_plan_submission(api, boundary_plan_group):
    """
    The very same projections carrying a 4,300,000 cent first-year expense overrun sink
    the year-three ratio to 799.55, which floors to 799 and lands a single basis point
    under the stress floor. Submission is refused and the plan is left in draft with
    nothing written.

    PRD: "Flooring, not rounding, means a ratio of 799.9 basis points is 799 and fails a floor test set at 800."
    PRD: "A `DEFICIENT` verdict rejects the request and changes nothing — no status moves, no version increments."

    Design: Difficulty/boundary_precision_check/stress_floor_exactly_800_bps_passes_submit_and_799_fails
    """
    world = boundary_plan_group
    scenario = get_success_data(
        api.create_stress_scenario(
            world["b2"],
            stress_scenario_payload(
                SCENARIO_ADVERSE,
                credit_loss_rate_bps=75,
                nim_compression_bps=40,
                expense_overrun_cents=4_300_000,
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        scenario,
        dynamic_min_leverage_ratio_bps=799,
        dynamic_breach_year_index=3,
        static_min_leverage_ratio_bps=1376,
        governing_min_leverage_ratio_bps=799,
    )

    before = fx.read_plan(api, world["b2"])
    validate_error(
        api.submit_business_plan(world["b2"], world["lead_headers"]),
        "ERR_STRESS_CAPITAL_SHORTFALL",
    )
    after = fx.read_plan(api, world["b2"])
    assert_fields_equal(after, status=PLAN_DRAFT, version=before["version"])
