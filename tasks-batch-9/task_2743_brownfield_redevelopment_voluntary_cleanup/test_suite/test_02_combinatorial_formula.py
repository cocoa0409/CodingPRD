"""
Multi-input formulas whose result depends on the order the steps are taken in.

Three of them live here: the per-line rounding that pins ``direct_cost_cents``, the
placement ladder that must price against the pre-premium estimate before the funding
need is rewritten, and the three-rung rate tier the limit-to-estimate ratio selects.
"""

from test_helpers import (
    add_plan,
    add_policy,
    assert_fields,
    assert_number,
    assert_placement_figures,
    canonical_cost_lines,
    expected_direct_cost_cents,
    expected_line_cents,
    expected_placement,
    single_excavation_line,
    single_monitoring_line,
    stage_bind,
    stage_enrolled,
    stage_plan,
    stage_plan_approved,
    stage_quote,
)

DESIGN_TOTAL_CENTS = 115210677
UNDERWRITING_TOTAL_CENTS = 139803445


def _add_second_plan(world, cost_lines, years_to_construction_start=3):
    """File another plan on the same enrollment, echoing its current version back."""
    enrollment = world.read_enrollment()
    return add_plan(
        world,
        cost_lines=cost_lines,
        years_to_construction_start=years_to_construction_start,
        expected_vcp_enrollment_version=enrollment["version"],
    )


def _quote_against(world, plan, policy_reference, term_years=5):
    """Price a cap over one specific plan at that plan's current version."""
    return add_policy(
        world,
        remedial_action_plan_id=plan["id"],
        expected_remedial_action_plan_version=plan["version"],
        policy_reference=policy_reference,
        term_years=term_years,
    )


# ─── per_line_rounding_before_sum_pins_direct_cost_cents ───────────────────────


def test_direct_cost_sums_the_individually_rounded_lines(api):
    """
    Each line is rounded before the sum, which lands a whole cent below the naive total.

    "Summing the raw products and rounding the total once at the end yields a different
    figure by whole cents and is not what this specification requires."

    Design: Difficulty/combinatorial_formula/per_line_rounding_before_sum_pins_direct_cost_cents
    """
    world = stage_enrolled(api)
    stage_plan(world)

    plan = world.read_plan()
    assert_fields(plan, direct_cost_cents=89787402)
    assert plan["direct_cost_cents"] != 89787403, (
        "rounding the summed raw products would produce 89787403, which is wrong"
    )
    assert plan["direct_cost_cents"] == expected_direct_cost_cents(
        canonical_cost_lines()
    ), "direct_cost_cents must equal the sum of the already-rounded line values"


def test_cost_lines_come_back_in_the_submitted_array_order(api):
    """
    The stored array preserves the order the lines were filed in.

    "The lines of `cost_lines` are evaluated **in array order**, and each is rounded to
    whole cents individually before any summing happens."

    Design: Difficulty/combinatorial_formula/per_line_rounding_before_sum_pins_direct_cost_cents
    """
    world = stage_enrolled(api)
    stage_plan(world)

    submitted = canonical_cost_lines()
    stored = world.read_plan()["cost_lines"]
    assert len(stored) == 6, f"the plan must carry six cost lines, got {len(stored)}"
    for index, (want, got) in enumerate(zip(submitted, stored)):
        assert got["cost_category"] == want["cost_category"], f"line {index} category"
        assert got["media"] == want["media"], f"line {index} media"
        assert_number(got["quantity"], want["quantity"], f"line {index} quantity")
        assert_number(
            got["unit_cost_cents"], want["unit_cost_cents"], f"line {index} unit cost"
        )


def test_escalation_and_total_build_on_the_pinned_direct_cost(api):
    """
    Every later step reads the per-line-rounded direct cost, not a re-multiplication.

    "`escalation_cents` is the direct cost multiplied by 0.042 multiplied by the
    applicable number of years, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/per_line_rounding_before_sum_pins_direct_cost_cents
    """
    world = stage_enrolled(api)
    stage_plan(world)

    plan = world.read_plan()
    assert_fields(
        plan,
        direct_cost_cents=89787402,
        escalation_cents=11313213,
        contingency_cents=10110062,
        oversight_cents=4000000,
        total_estimate_cents=DESIGN_TOTAL_CENTS,
    )
    lines = canonical_cost_lines()
    assert expected_line_cents(lines[0]["quantity"], lines[0]["unit_cost_cents"], "SOIL") == 433062
    assert expected_line_cents(lines[1]["quantity"], lines[1]["unit_cost_cents"], "SOIL") == 865562


# ─── premium_derived_before_funding_need_is_written ────────────────────────────


def test_quote_prices_the_cap_from_the_pre_premium_estimate(api):
    """
    Attachment, buffer, limit, rate and premium all descend from one figure.

    "the limit and the premium are derived from the **pre-premium**
    `underwriting_estimate_cents` alone, and `total_funding_need_cents` is written
    afterwards, at bind, and never re-enters the pricing"

    Design: Difficulty/combinatorial_formula/premium_derived_before_funding_need_is_written
    """
    world = stage_enrolled(api)
    stage_plan(world)
    stage_plan_approved(world)
    stage_quote(world)

    policy = world.read_policy()
    assert_fields(
        policy,
        status="QUOTED",
        bound_at=None,
        underwriting_estimate_cents=UNDERWRITING_TOTAL_CENTS,
        attachment_point_cents=153783790,
        buffer_layer_cents=13980345,
        limit_cents=50000000,
        premium_cents=2832500,
    )
    assert_number(policy["rate_applied"], "0.055", "rate_applied")
    assert_placement_figures(policy, expected_placement(UNDERWRITING_TOTAL_CENTS))


def test_bind_folds_the_premium_into_the_funding_need_afterwards(api):
    """
    The need is rewritten at bind; the placement figures do not move with it.

    "A plan's `total_funding_need_cents` is its `total_estimate_cents` plus the
    `premium_cents` of every cost-cap policy on that plan whose `status` is `BOUND` —
    quoted, superseded and cancelled policies contribute nothing."

    Design: Difficulty/combinatorial_formula/premium_derived_before_funding_need_is_written
    """
    world = stage_enrolled(api)
    stage_plan(world)
    stage_plan_approved(world)
    stage_quote(world)
    stage_bind(world)

    policy = world.read_policy()
    assert_fields(
        policy,
        status="BOUND",
        limit_cents=50000000,
        premium_cents=2832500,
        underwriting_estimate_cents=UNDERWRITING_TOTAL_CENTS,
    )
    plan = world.read_plan()
    assert_fields(
        plan,
        total_estimate_cents=DESIGN_TOTAL_CENTS,
        total_funding_need_cents=118043177,
    )


# ─── premium_rate_tier_ladder_selects_three_distinct_rates ─────────────────────


def test_a_low_limit_ratio_selects_the_seven_percent_rate(api):
    """
    A large remedy takes a limit worth under 35 percent of the estimate.

    "The rate ladder is then selected from the ratio of `limit_cents` to
    `underwriting_estimate_cents`, and that ratio is compared **unrounded**: a ratio of
    0.35 or less selects a rate of 0.070, a ratio above 0.35 but no greater than 0.60
    selects 0.055, and any larger ratio selects 0.045."

    Design: Difficulty/combinatorial_formula/premium_rate_tier_ladder_selects_three_distinct_rates
    """
    world = stage_enrolled(api)
    stage_plan(world)
    stage_plan_approved(world)

    plan_b = _add_second_plan(world, single_excavation_line())
    policy = _quote_against(world, plan_b, "CCP-2743-B")

    assert_fields(
        policy,
        underwriting_estimate_cents=94750000,
        limit_cents=30000000,
        premium_cents=2500000,
    )
    assert_number(policy["rate_applied"], "0.070", "rate_applied")
    assert_placement_figures(policy, expected_placement(94750000))


def test_a_mid_limit_ratio_selects_the_five_and_a_half_percent_rate(api):
    """
    The canonical remedy's ratio falls just above the low rung.

    "a ratio above 0.35 but no greater than 0.60 selects 0.055"

    Design: Difficulty/combinatorial_formula/premium_rate_tier_ladder_selects_three_distinct_rates
    """
    world = stage_enrolled(api)
    stage_plan(world)
    stage_plan_approved(world)
    stage_quote(world)

    policy = world.read_policy()
    assert_fields(
        policy,
        underwriting_estimate_cents=UNDERWRITING_TOTAL_CENTS,
        limit_cents=50000000,
        premium_cents=2832500,
    )
    assert_number(policy["rate_applied"], "0.055", "rate_applied")


def test_a_high_limit_ratio_selects_the_four_and_a_half_percent_rate(api):
    """
    A tiny remedy is dominated by the limit granularity and pays the floor premium.

    "`premium_cents` is the larger of that broker-loaded figure and a minimum premium of
    2,500,000 cents (25,000.00), so a small remedy still pays the carrier's floor."

    Design: Difficulty/combinatorial_formula/premium_rate_tier_ladder_selects_three_distinct_rates
    """
    world = stage_enrolled(api)
    stage_plan(world)
    stage_plan_approved(world)

    plan_c = _add_second_plan(world, single_monitoring_line(), years_to_construction_start=2)
    policy = _quote_against(world, plan_c, "CCP-2743-C", term_years=3)

    assert_fields(
        policy,
        underwriting_estimate_cents=2174597,
        limit_cents=10000000,
        premium_cents=2500000,
    )
    assert_number(policy["rate_applied"], "0.045", "rate_applied")
    assert_placement_figures(policy, expected_placement(2174597))
