"""Multi-branch payout curves, the weighted vehicle factor, and target sizing.

Three formulas in the compensation calendar combine several independent inputs
into one number: the payout curve, which picks one of eight branches from a
metric's direction, interpolation and achievement band; the weighted vehicle
factor, whose per-metric rounding order is pinned to the cent; and the five-step
target computation, whose equity tier is keyed on the fixed-leg ratio alone.
"""

import pytest

from test_helpers import (
    CONSULTANT,
    api_client,
    assert_money,
    assert_ratio,
    certify_metric,
    create_pay_program_payload,
    read_award,
    read_metric,
    read_pay_program,
    setup_award,
    setup_mini_peer_group,
    setup_pay_program,
    submit_metric_result,
    validate_success,
)

# The four direction-by-interpolation combinations over one ANNUAL_INCENTIVE
# vehicle, each weighted 25.00 so the vehicle's weights total 100.00.
BRANCH_MATRIX_CURVES = (
    "ADJ_EPS_LINEAR",
    "REVENUE_GROWTH_STEP",
    "COST_RATIO_STEP",
    "ROIC_LINEAR",
)
BRANCH_MATRIX_OVERRIDES = [
    {"weight_pct": 25.00},
    {"weight_pct": 25.00},
    {"weight_pct": 25.00, "interpolation": "LINEAR"},
    {"weight_pct": 25.00, "interpolation": "STEP"},
]
BRANCH_MATRIX_ACHIEVEMENTS = (5.50, 4.50, 0.63, 0.59)

# Three equally weighted metrics whose weights are 33.33 / 33.33 / 33.34.
THIRDS_CURVES = ("ADJ_EPS_LINEAR", "ADJ_EPS_LINEAR", "ADJ_EPS_LINEAR")
THIRDS_OVERRIDES = [
    {"weight_pct": 33.33},
    {"metric_code": "REVENUE_GROWTH", "weight_pct": 33.33},
    {"metric_code": "FCF", "weight_pct": 33.34},
]


# ---------------------------------------------------------------------------
# Local composition helpers (built only from the barrel's atoms)
# ---------------------------------------------------------------------------
def _program_with_award(curves, overrides) -> dict:
    """Committee-approved program over the mini peer group with one cash award."""
    env = setup_pay_program(metric_curves=curves, metric_overrides=list(overrides))
    return setup_award(env, "annual_incentive", "ANNUAL_INCENTIVE")


def _certified_single_metric(curve: str, achieved: float, **metric_overrides) -> dict:
    """Carry one solitary metric weighted 100.00 all the way to CERTIFIED."""
    overrides = {"weight_pct": 100.00}
    overrides.update(metric_overrides)
    env = setup_pay_program(metric_curves=(curve,), metric_overrides=[overrides])
    metric = env["metrics"][0]
    submit_metric_result(metric["id"], achieved)
    certify_metric(metric["id"])
    return read_metric(env["program"]["id"], metric["id"])


# ---------------------------------------------------------------------------
# The payout curve's branch matrix
# ---------------------------------------------------------------------------
def test_four_direction_and_interpolation_branches_each_pick_their_own_factor():
    """One program's four metrics land on four different curve branches.

    ADJ_EPS interpolates above target for 150.00, REVENUE_GROWTH steps to the
    threshold for 50.00, COST_RATIO interpolates down past target for 140.00 and
    ROIC steps to the maximum for 200.00. Weighted 25.00 each those give the
    award a 135.00 factor and 2,430,000.00 of earned cash on its 1,800,000.00
    target.

    "The curve is evaluated against `achieved_value` using the metric's own three
    goal values and three payout percentages, and each of the four
    direction-by-interpolation combinations is specified separately."

    Design: Difficulty/combinatorial_formula/payout_curve_branch_matrix_across_direction_and_interpolation
    """
    env = _program_with_award(BRANCH_MATRIX_CURVES, BRANCH_MATRIX_OVERRIDES)
    for metric, achieved in zip(env["metrics"], BRANCH_MATRIX_ACHIEVEMENTS):
        submit_metric_result(metric["id"], achieved)
    for metric in env["metrics"]:
        certify_metric(metric["id"])

    factors = [read_metric(env["program"]["id"], m["id"]) for m in env["metrics"]]
    for metric in factors:
        assert metric["status"] == "CERTIFIED"
    assert_money(factors[0]["payout_factor_pct"], 150.00, "HIGHER_IS_BETTER LINEAR factor")
    assert_money(factors[1]["payout_factor_pct"], 50.00, "HIGHER_IS_BETTER STEP factor")
    assert_money(factors[2]["payout_factor_pct"], 140.00, "LOWER_IS_BETTER LINEAR factor")
    assert_money(factors[3]["payout_factor_pct"], 200.00, "LOWER_IS_BETTER STEP factor")

    award = read_award(env["awards"]["annual_incentive"]["id"])
    assert_money(award["target_amount_usd"], 1800000.00, "target_amount_usd")
    assert_money(award["certified_factor_pct"], 135.00, "certified_factor_pct")
    assert_money(award["earned_amount_usd"], 2430000.00, "earned_amount_usd")


def test_step_branch_refuses_to_interpolate_where_the_linear_branch_prorates():
    """Identical curve, identical achievement, two different payout factors.

    Both metrics run 4.00 / 5.00 / 6.00 upward and both achieve 4.50. The linear
    branch prorates half the way from the 50.00 threshold payout to the 100.00
    target payout and pays 75.00; the staircase pays the threshold payout of
    50.00 flat. Weighted 50.00 each the award factor is 62.50.

    "For a `HIGHER_IS_BETTER` metric with `STEP` interpolation the curve is a
    staircase with no proration: at or above the maximum pays
    `maximum_payout_pct`, otherwise at or above the target pays
    `target_payout_pct`, otherwise at or above the threshold pays
    `threshold_payout_pct`, otherwise 0.00."

    Design: Difficulty/combinatorial_formula/payout_curve_branch_matrix_across_direction_and_interpolation
    """
    env = _program_with_award(
        ("ADJ_EPS_LINEAR", "REVENUE_GROWTH_STEP"),
        [{"weight_pct": 50.00}, {"weight_pct": 50.00}],
    )
    for metric in env["metrics"]:
        submit_metric_result(metric["id"], 4.50)
    for metric in env["metrics"]:
        certify_metric(metric["id"])

    linear = read_metric(env["program"]["id"], env["metrics"][0]["id"])
    step = read_metric(env["program"]["id"], env["metrics"][1]["id"])
    assert_money(linear["payout_factor_pct"], 75.00, "LINEAR factor at 4.50")
    assert_money(step["payout_factor_pct"], 50.00, "STEP factor at 4.50")
    assert linear["payout_factor_pct"] != pytest.approx(step["payout_factor_pct"], abs=0.01), (
        "the staircase must not interpolate the way the linear curve does"
    )

    award = read_award(env["awards"]["annual_incentive"]["id"])
    assert_money(award["certified_factor_pct"], 62.50, "certified_factor_pct")
    assert_money(award["earned_amount_usd"], 1125000.00, "earned_amount_usd")


@pytest.mark.parametrize(
    "curve,interpolation,achieved,expected_factor",
    [
        ("ADJ_EPS_LINEAR", "LINEAR", 4.00, 50.00),
        ("ADJ_EPS_LINEAR", "LINEAR", 6.00, 200.00),
        ("ADJ_EPS_LINEAR", "LINEAR", 3.00, 0.00),
        ("COST_RATIO_STEP", "LINEAR", 0.70, 50.00),
        ("COST_RATIO_STEP", "LINEAR", 0.60, 200.00),
        ("COST_RATIO_STEP", "LINEAR", 0.80, 0.00),
    ],
)
def test_curve_boundaries_are_inclusive_in_the_earning_direction(
    curve, interpolation, achieved, expected_factor
):
    """Achieving exactly a goal value pays exactly that goal's payout percentage.

    The upward curve runs 4.00 / 5.00 / 6.00 and the downward curve runs 0.70 /
    0.65 / 0.60, both paying 50.00 / 100.00 / 200.00. Landing exactly on the
    threshold pays 50.00 and exactly on the maximum pays 200.00 in either
    direction, while an achievement past the threshold in the failing direction
    pays nothing.

    "The boundaries are inclusive in the earning direction: an achievement
    exactly equal to `threshold_value` pays exactly `threshold_payout_pct`, an
    achievement exactly equal to `maximum_value` pays exactly
    `maximum_payout_pct`, and one unit past the threshold in the failing
    direction pays 0.00."

    Design: Difficulty/combinatorial_formula/payout_curve_branch_matrix_across_direction_and_interpolation
    """
    metric = _certified_single_metric(curve, achieved, interpolation=interpolation)

    assert metric["status"] == "CERTIFIED"
    assert_money(metric["payout_factor_pct"], expected_factor, "payout_factor_pct")
    assert_money(
        metric["original_payout_factor_pct"], expected_factor, "original_payout_factor_pct"
    )


# ---------------------------------------------------------------------------
# The weighted vehicle factor's rounding order
# ---------------------------------------------------------------------------
def test_weighted_vehicle_factor_rounds_each_contribution_before_summing():
    """Three thirds of a vehicle at 150.00 each sum to 150.01, not to 150.00.

    Weights 33.33, 33.33 and 33.34 against a 150.00 factor give contributions of
    49.995, 49.995 and 50.01. Rounding each one first yields 50.00 + 50.00 +
    50.01 = 150.01, whereas summing the unrounded products would give exactly
    150.00 — and the surviving cent moves earned cash from 2,700,000.00 to
    2,700,180.00 on the 1,800,000.00 target.

    "Otherwise each metric contributes its `payout_factor_pct` multiplied by its
    `weight_pct` divided by 100, **each contribution rounded half-up to two
    decimal places individually**, and `certified_factor_pct` is the sum of those
    rounded contributions, rounded again to two decimal places."

    Design: Difficulty/combinatorial_formula/weighted_factor_rounds_per_metric_before_summing
    """
    env = _program_with_award(THIRDS_CURVES, THIRDS_OVERRIDES)
    for metric in env["metrics"]:
        submit_metric_result(metric["id"], 5.50)
    for metric in env["metrics"]:
        certify_metric(metric["id"])

    for metric in env["metrics"]:
        row = read_metric(env["program"]["id"], metric["id"])
        assert_money(row["payout_factor_pct"], 150.00, "payout_factor_pct")

    award = read_award(env["awards"]["annual_incentive"]["id"])
    assert_money(award["target_amount_usd"], 1800000.00, "target_amount_usd")
    assert_money(award["certified_factor_pct"], 150.01, "certified_factor_pct")
    assert award["certified_factor_pct"] != pytest.approx(150.00, abs=0.001), (
        "summing unrounded products and rounding the total afterwards is wrong"
    )
    assert_money(award["earned_amount_usd"], 2700180.00, "earned_amount_usd")
    assert award["earned_amount_usd"] != pytest.approx(2700000.00, abs=0.01)
    assert_money(award["realizable_value_usd"], 2700180.00, "realizable_value_usd")
    assert award["status"] == "GRANTED"


def test_vehicle_factor_stays_null_until_every_metric_of_the_vehicle_is_certified():
    """Two certifications out of three leave the award without a factor at all.

    While the third metric is still RESULT_SUBMITTED the award has no
    certified_factor_pct and no earned_amount_usd, so the forward-looking
    valuation falls back to the assumed 100.00 percent of the 1,800,000.00
    target. Certifying the last metric is what publishes the 150.01 factor.

    "If the set is non-empty but not every member of it is in `CERTIFIED` or
    `RESTATED`, the factor is likewise null and the computation stops."

    Design: Difficulty/combinatorial_formula/weighted_factor_rounds_per_metric_before_summing
    """
    env = _program_with_award(THIRDS_CURVES, THIRDS_OVERRIDES)
    for metric in env["metrics"]:
        submit_metric_result(metric["id"], 5.50)
    certify_metric(env["metrics"][0]["id"])
    certify_metric(env["metrics"][1]["id"])

    partial = read_award(env["awards"]["annual_incentive"]["id"])
    assert partial["certified_factor_pct"] is None, (
        "the factor waits for every metric of the vehicle"
    )
    assert partial["earned_amount_usd"] is None, "no factor means no earned amount"
    assert_money(partial["realizable_value_usd"], 1800000.00, "realizable at assumed target")

    certify_metric(env["metrics"][2]["id"])

    complete = read_award(env["awards"]["annual_incentive"]["id"])
    assert_money(complete["certified_factor_pct"], 150.01, "certified_factor_pct")
    assert_money(complete["earned_amount_usd"], 2700180.00, "earned_amount_usd")


# ---------------------------------------------------------------------------
# The five-step target computation
# ---------------------------------------------------------------------------
def test_equity_tier_keyed_on_the_fixed_leg_ratio_not_on_target_compensation():
    """A 0.6250 fixed-leg ratio buys the 4.0 multiple and never revisits it.

    The CEO's fixed leg is 3,000,000.00 and the benchmark's own fixed leg on a
    15.00 plus 25.00 share of a 12,000,000.00 benchmark is 4,800,000.00, so
    benchmark_ratio is 0.6250 and the multiple is 4.0. That produces
    lti_target_usd 12,000,000.00 and target_tdc_usd 15,000,000.00 — a posture
    ratio of 1.2500 and therefore ABOVE_MARKET — rather than the 9,000,000.00 a
    tier re-keyed on that posture ratio would have produced.

    "The tier is keyed on the fixed-leg ratio from step two and nothing else; it
    is never keyed on target compensation, which does not exist yet, and it is
    never re-evaluated after the later steps."

    Design: Difficulty/combinatorial_formula/tdc_tier_pinned_to_fixed_leg_ratio_not_to_total_target
    """
    env = setup_mini_peer_group(target_status="APPROVED")
    payload = create_pay_program_payload(
        env["issuer"]["id"], env["peer_group"]["id"], env["ceo"]["id"]
    )

    response = api_client.create_pay_program(payload, CONSULTANT)
    program = validate_success(response, 201)

    assert_money(program["fixed_leg_usd"], 3000000.00, "fixed_leg_usd")
    assert_ratio(program["benchmark_ratio"], 0.6250, "benchmark_ratio")
    assert program["lti_multiple"] == pytest.approx(4.0, abs=0.01)
    assert_money(program["lti_target_usd"], 12000000.00, "lti_target_usd")
    assert_money(program["target_tdc_usd"], 15000000.00, "target_tdc_usd")
    assert program["target_tdc_usd"] != pytest.approx(9000000.00, abs=0.01), (
        "the tier must not be re-derived from the posture ratio"
    )
    assert program["benchmark_posture"] == "ABOVE_MARKET"
    assert_money(program["performance_based_pct"], 61.00, "performance_based_pct")


def test_same_fixed_leg_on_a_heavier_equity_share_lands_on_the_middle_tier():
    """Shifting the mix to 20.00 / 5.00 / 75.00 changes the tier, not the fixed leg.

    The officer's fixed leg is still 3,000,000.00, but the benchmark's fixed leg
    on a 20.00 plus 5.00 share of the same 12,000,000.00 benchmark is
    3,000,000.00, so benchmark_ratio is 1.0000 and the multiple drops to 3.0.
    That gives lti_target_usd 9,000,000.00, target_tdc_usd 12,000,000.00 and a
    posture ratio of 1.0000, which bands to ALIGNED.

    "**Step three** looks up the equity tier from that ratio: `lti_multiple` is
    4.0 when `benchmark_ratio` is below 0.80, 3.0 when it is at least 0.80 but
    below 1.20, and 2.0 when it is at or above 1.20."

    Design: Difficulty/combinatorial_formula/tdc_tier_pinned_to_fixed_leg_ratio_not_to_total_target
    """
    env = setup_mini_peer_group(target_status="APPROVED")
    payload = create_pay_program_payload(
        env["issuer"]["id"],
        env["peer_group"]["id"],
        env["ceo"]["id"],
        fiscal_year=2025,
        meeting_date="2027-04-15T00:00:00Z",
        salary_pct=20.00,
        sti_pct=5.00,
        lti_pct=75.00,
    )

    response = api_client.create_pay_program(payload, CONSULTANT)
    program = validate_success(response, 201)

    assert_money(program["fixed_leg_usd"], 3000000.00, "fixed_leg_usd")
    assert_ratio(program["benchmark_ratio"], 1.0000, "benchmark_ratio")
    assert program["lti_multiple"] == pytest.approx(3.0, abs=0.01)
    assert_money(program["lti_target_usd"], 9000000.00, "lti_target_usd")
    assert_money(program["target_tdc_usd"], 12000000.00, "target_tdc_usd")
    assert program["benchmark_posture"] == "ALIGNED"
    assert_money(program["performance_based_pct"], 50.00, "performance_based_pct")

    readback = read_pay_program(program["id"])
    assert_ratio(readback["benchmark_ratio"], 1.0000, "benchmark_ratio")
    assert_money(readback["target_tdc_usd"], 12000000.00, "target_tdc_usd")


def test_target_chain_stops_at_the_fixed_leg_when_the_group_has_no_benchmark():
    """An unscreened peer group leaves everything downstream of step one null.

    The officer's fixed leg still resolves to 3,000,000.00 because it depends on
    salary and the annual-incentive target alone, but with no
    benchmark_target_tdc_usd to size against there is no ratio, no multiple, no
    equity target and no total, and the program reports UNBENCHMARKED.

    "If the peer group has no `benchmark_target_tdc_usd` yet, the chain stops
    here: `benchmark_ratio`, `lti_multiple`, `lti_target_usd` and
    `target_tdc_usd` are all null and `benchmark_posture` is `UNBENCHMARKED`."

    Design: Difficulty/combinatorial_formula/tdc_tier_pinned_to_fixed_leg_ratio_not_to_total_target
    """
    env = setup_mini_peer_group(target_status="DRAFT")
    payload = create_pay_program_payload(
        env["issuer"]["id"], env["peer_group"]["id"], env["ceo"]["id"]
    )

    response = api_client.create_pay_program(payload, CONSULTANT)
    program = validate_success(response, 201)

    assert_money(program["fixed_leg_usd"], 3000000.00, "fixed_leg_usd")
    assert program["benchmark_ratio"] is None, "benchmark_ratio must stay null"
    assert program["lti_multiple"] is None, "lti_multiple must stay null"
    assert program["lti_target_usd"] is None, "lti_target_usd must stay null"
    assert program["target_tdc_usd"] is None, "target_tdc_usd must stay null"
    assert program["benchmark_posture"] == "UNBENCHMARKED"
    assert_money(program["performance_based_pct"], 61.00, "performance_based_pct")
