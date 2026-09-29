"""
Two derivations that run the same arithmetic twice under different inputs.

A cleanup goal is derived on a restricted or an unrestricted basis, and a remediation
estimate is run on a design basis or an underwriting basis. In both pairs the two
variants must diverge in exactly the way the contract describes, and neither variant may
overwrite the other's stored figures.
"""

from decimal import Decimal

from test_helpers import (
    assert_estimate_figures,
    assert_fields,
    assert_number,
    expected_cost_estimate,
    canonical_cost_lines,
    stage_assessed,
    stage_enrolled,
    stage_goals,
    stage_plan,
    stage_plan_approved,
    stage_quote,
)

DESIGN_ESTIMATE = {
    "direct_cost_cents": 89787402,
    "escalation_cents": 11313213,
    "contingency_pct": "0.10",
    "contingency_cents": 10110062,
    "oversight_cents": 4000000,
    "total_cents": 115210677,
}
UNDERWRITING_TOTAL_CENTS = 139803445


# ─── cleanup_goal_restricted_vs_unrestricted_basis_diverge ─────────────────────


def test_restricted_goal_lands_on_the_shared_cumulative_cap(api):
    """
    The commercial multiplier and the vapour credit push the target past the cap.

    "The cumulative cap is 500.0 divided by the greater of 1 and that distinct count —
    so a media with no qualifying analytes still divides by 1 rather than by zero."

    Design: Difficulty/dual_variant_calc/cleanup_goal_restricted_vs_unrestricted_basis_diverge
    """
    world = stage_assessed(api)
    stage_goals(world)

    goal = world.read_goal(world.goal_restricted)
    assert_number(goal["goal_ugl"], "250.00", "goal_ugl")
    assert_fields(
        goal,
        basis="RESTRICTED",
        control_credit_type="VAPOR_MITIGATION",
        media="SOIL_VAPOR",
        cumulative_cap_applied=True,
        attainment_status="NOT_ATTAINED",
        compliant_streak=0,
    )


def test_unrestricted_goal_forces_the_residential_scenario(api):
    """
    The unrestricted variant ignores the parcel's reuse and takes no credit.

    "An `UNRESTRICTED` goal takes no control credit at all — the credited value equals
    the scenario goal."

    Design: Difficulty/dual_variant_calc/cleanup_goal_restricted_vs_unrestricted_basis_diverge
    """
    world = stage_assessed(api)
    stage_goals(world)

    goal = world.read_goal(world.goal_unrestricted)
    assert_number(goal["goal_ugl"], "166.67", "goal_ugl")
    assert_fields(
        goal,
        basis="UNRESTRICTED",
        control_credit_type=None,
        media="SOIL_VAPOR",
        cumulative_cap_applied=False,
        attainment_status="NOT_ATTAINED",
        compliant_streak=0,
    )


def test_the_two_bases_diverge_on_the_same_screening_level(api):
    """
    Same media, same screening level, two targets and two cap verdicts.

    "When `basis` is `UNRESTRICTED`, the scenario is forced to residential regardless of
    what the parcel's `intended_reuse` says; when `basis` is `RESTRICTED`, the scenario
    is the parcel's `intended_reuse`."

    Design: Difficulty/dual_variant_calc/cleanup_goal_restricted_vs_unrestricted_basis_diverge
    """
    world = stage_assessed(api)
    stage_goals(world)

    restricted = world.read_goal(world.goal_restricted)
    unrestricted = world.read_goal(world.goal_unrestricted)

    assert_number(restricted["screening_level_ugl"], "5.0", "restricted screening level")
    assert_number(unrestricted["screening_level_ugl"], "5.0", "unrestricted screening level")
    # Both targets are stored to two decimal places, so the divergence is taken in
    # exact decimal arithmetic; a binary float subtraction would invent digits the
    # contract's 2-dp quantum does not have.
    assert_number(
        Decimal(str(restricted["goal_ugl"])) - Decimal(str(unrestricted["goal_ugl"])),
        "83.33",
        "divergence between the two bases",
    )
    assert restricted["cumulative_cap_applied"] is True
    assert unrestricted["cumulative_cap_applied"] is False


# ─── cost_estimate_design_vs_underwriting_basis_diverge ────────────────────────


def test_plan_filing_writes_the_design_basis_estimate(api):
    """
    Filing runs the five steps on the plan's own schedule and confidence tier.

    "Under the design basis that total is stored on the plan as `total_estimate_cents`;
    under the underwriting basis it is stored on the cost-cap policy as
    `underwriting_estimate_cents`."

    Design: Difficulty/dual_variant_calc/cost_estimate_design_vs_underwriting_basis_diverge
    """
    world = stage_enrolled(api)
    stage_plan(world)

    plan = world.read_plan()
    assert_estimate_figures(plan, DESIGN_ESTIMATE)
    assert_estimate_figures(
        plan, expected_cost_estimate(canonical_cost_lines(), 3, "FULL", 4.80)
    )
    assert_fields(plan, total_funding_need_cents=DESIGN_ESTIMATE["total_cents"])


def test_quote_writes_the_underwriting_basis_alongside_the_design_basis(api):
    """
    The carrier's number is larger and it does not disturb the plan's own figures.

    "The design basis escalates over the plan's own `years_to_construction_start`; the
    underwriting basis escalates over a fixed five years regardless of what the plan
    proposes."

    Design: Difficulty/dual_variant_calc/cost_estimate_design_vs_underwriting_basis_diverge
    """
    world = stage_enrolled(api)
    stage_plan(world)
    stage_plan_approved(world)
    stage_quote(world)

    policy = world.read_policy()
    assert_fields(policy, underwriting_estimate_cents=UNDERWRITING_TOTAL_CENTS)
    assert (
        policy["underwriting_estimate_cents"] - DESIGN_ESTIMATE["total_cents"] == 24592768
    ), "the underwriting basis must exceed the design basis by the pinned delta"

    plan = world.read_plan()
    assert_fields(
        plan,
        total_estimate_cents=DESIGN_ESTIMATE["total_cents"],
        total_funding_need_cents=DESIGN_ESTIMATE["total_cents"],
    )
