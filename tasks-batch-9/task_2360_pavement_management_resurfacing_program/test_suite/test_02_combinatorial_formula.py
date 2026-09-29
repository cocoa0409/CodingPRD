"""One money figure assembled from several independently-derived factors."""

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_area,
    assert_four_decimals,
    assert_index,
    assert_money,
    assert_project_estimate,
    assert_project_scope,
)
from test_helpers.constants import (
    AREA_GRAND,
    AREA_PINE,
    CRACK_SEAL,
    ELM_CANDIDATE_COST,
    ELM_LINE_COST,
    ELM_PINE_AREA,
    ELM_PINE_BASE,
    ELM_PINE_CONTINGENCY,
    ELM_PINE_TOTAL,
    GRAND_CANDIDATE_COST,
    MOBILIZATION_CRACK_SEAL_CENTS,
    OAK_BUNDLE_BASE,
    OAK_CONTINGENCY,
    OAK_LINE_COST,
    OAK_TOTAL,
    OBS_CS75,
    OBS_RECON,
    OBS_RECON_DEDUCT,
    OBS_RECON_INDEX,
    PINE_CANDIDATE_COST,
    PINE_LINE_COST,
    RECONSTRUCTION,
    SEG_GRAND,
    SEG_OAK,
)

GRAND_ONLY = [(SEG_GRAND, OBS_RECON)]
OAK_ONLY = [(SEG_OAK, OBS_CS75)]

ELM_PINE_LINES = [
    ("Elm St", "2026-09-01T00:00:00Z", "2026-09-15T00:00:00Z"),
    ("Pine St", "2026-09-15T00:00:00Z", "2026-09-30T00:00:00Z"),
]
OAK_LINE = [("Oak St", "2026-09-01T00:00:00Z", "2026-09-30T00:00:00Z")]


def test_candidate_cost_multiplies_the_matrix_rate_by_the_clamped_width_factor(api):
    """Four independent factors and an addend outside the product land on one cent.

    PRD: "The candidate's `estimated_cost_cents` is then the segment's `area_sy`
    multiplied by the base rate, then by the width factor, then by the condition
    penalty, all at full precision, with that single product rounded once to whole
    cents — and only *after* that rounding is a mobilisation charge added: 250,000
    cents ($2,500) for crack seal, and 850,000 cents ($8,500) for either
    mill-and-overlay or reconstruction."

    PRD: "The width factor recognises that wide streets cost more per yard to
    stage: it is one plus one hundredth of the amount by which `width_ft` exceeds
    the 24 feet treated as free, clamped to no less than 1.00 and no more than
    1.25, and rounded to four decimal places — so a 24-foot street and any
    narrower street both take 1.0000, a 40-foot street takes 1.1600, and anything
    at or beyond 49 feet is capped at 1.2500."

    Grand Blvd is 60.00 ft wide, whose raw width factor 1.36 is above the clamp,
    and its POOR snapshot adds the 1.05 penalty: 13333.33 * 13500 * 1.25 * 1.05
    rounds to 236249941, plus the 850000 reconstruction mobilisation.

    Design: Difficulty/combinatorial_formula/candidate_cost_tiered_rate_times_clamped_width_factor_times_condition_penalty
    """
    ctx = fixtures.sealed_survey(api, GRAND_ONLY)
    observation = ctx["observations"]["Grand Blvd"]
    assert observation["deduct_total"] == OBS_RECON_DEDUCT
    assert_index(observation["measured_condition_index"], OBS_RECON_INDEX)
    assert_area(ctx["segments"]["Grand Blvd"]["area_sy"], AREA_GRAND)

    candidate = fixtures.generate_candidates(api, ctx["survey"]["id"])[0]

    assert candidate["treatment_type"] == RECONSTRUCTION
    assert_index(candidate["selection_condition_index"], OBS_RECON_INDEX)
    assert_money(candidate["estimated_cost_cents"], GRAND_CANDIDATE_COST)
    assert candidate["estimated_cost_cents"] != 257039936, (
        "the width factor is clamped at 1.25, not the raw 1.36"
    )
    assert candidate["estimated_cost_cents"] != 224999944, (
        "the POOR condition penalty 1.05 belongs in the product"
    )


def test_candidate_benefit_cost_ratio_divides_by_the_mobilised_cost(api):
    """The ratio consumes the same assembled cost, mobilisation included.

    PRD: "The cost is restated in thousands of dollars by dividing
    `estimated_cost_cents` by 100,000, with mobilisation included."

    PRD: "The stored `benefit_cost_ratio` is the benefit quantity divided by that
    cost in thousands, rounded to four decimal places."

    Reconstruction caps the gain at 100.0 but the headroom from 30.0 is only
    70.0, so the benefit is 70.0 * 30 * 13333.33 = 27999993.00 against
    2370.99941 thousand dollars of cost.

    Design: Difficulty/combinatorial_formula/candidate_cost_tiered_rate_times_clamped_width_factor_times_condition_penalty
    """
    ctx = fixtures.sealed_survey(api, GRAND_ONLY)

    candidate = fixtures.generate_candidates(api, ctx["survey"]["id"])[0]

    assert_index(candidate["treatment_pci_gain"], 70.0)
    assert candidate["expected_service_life_years"] == 30
    assert_money(candidate["estimated_cost_cents"], GRAND_CANDIDATE_COST)
    assert_four_decimals(candidate["benefit_cost_ratio"], 11809.3631, "benefit_cost_ratio")


def _elm_pine_bundle(api):
    """A two-line all-crack-seal Z3 bundle whose areas both carry a .67 tail."""
    ctx = fixtures.adopted_program(api, fixtures.ELM_AND_PINE)
    return fixtures.draft_project(
        api,
        ctx,
        ELM_PINE_LINES,
        geo_zone="Z3",
        project_name="Z3 crack seal package",
    )


def test_bundle_base_rounds_each_line_before_summing_them(api):
    """Round-then-sum and sum-then-round differ by one cent, and the PRD picks one.

    PRD: "Second, the already-rounded line costs are summed. Rounding per line and
    then summing is the specification; summing the raw products and rounding once
    at the end differs by cents and is wrong."

    Elm St at 3336.67 SY and Pine St at 3346.67 SY price to 1237905 and 1241615,
    which sum to 2479520; summing the raw products and rounding once gives
    2479519 instead.

    Design: Difficulty/combinatorial_formula/bundle_base_rounds_each_line_before_summation
    """
    ctx = _elm_pine_bundle(api)

    assert_money(ctx["lines"]["Elm St"]["line_cost_cents"], ELM_LINE_COST)
    assert_money(ctx["lines"]["Pine St"]["line_cost_cents"], PINE_LINE_COST)
    assert_area(ctx["lines"]["Pine St"]["line_area_sy"], AREA_PINE)
    assert_project_scope(ctx["project"], 2, ELM_PINE_AREA)
    assert_money(ctx["project"]["bundle_base_cents"], ELM_PINE_BASE)
    assert ctx["project"]["bundle_base_cents"] != 2729519, (
        "summing the raw products and rounding once at the end is one cent low"
    )


def test_all_crack_seal_bundle_carries_one_smaller_mobilisation(api):
    """Two lines, each priced with its own mobilisation, share a single bundle charge.

    PRD: "One mobilisation charge is then added for the whole bundle: 250,000
    cents when *every* non-removed line is a `CRACK_SEAL` line, and 850,000 cents
    otherwise."

    Both candidates were priced at 1487905 and 1491615 with a mobilisation each,
    yet the bundle base 2729520 exceeds the line sum by exactly one 250000 charge.

    Design: Difficulty/combinatorial_formula/bundle_base_rounds_each_line_before_summation
    """
    ctx = _elm_pine_bundle(api)
    assert_money(fixtures.candidate_for(ctx, "Elm St")["estimated_cost_cents"], ELM_CANDIDATE_COST)
    assert_money(fixtures.candidate_for(ctx, "Pine St")["estimated_cost_cents"], PINE_CANDIDATE_COST)
    assert ctx["lines"]["Elm St"]["treatment_type"] == CRACK_SEAL
    assert ctx["lines"]["Pine St"]["treatment_type"] == CRACK_SEAL

    line_sum = ELM_LINE_COST + PINE_LINE_COST
    assert ctx["project"]["bundle_base_cents"] - line_sum == MOBILIZATION_CRACK_SEAL_CENTS
    assert_project_estimate(
        ctx["project"], ELM_PINE_BASE, ELM_PINE_CONTINGENCY, 0, ELM_PINE_TOTAL
    )


def test_contingency_tier_reads_the_pre_contingency_base(api):
    """The tier lookup consumes the base, so a sub-boundary base keeps 15 percent.

    PRD: "The contingency percentage is 15 percent when `bundle_base_cents` is
    below 5,000,000 cents ($50,000), 10 percent when it is below 50,000,000 cents
    ($500,000), and 7 percent at or above that; the comparisons are strict, so a
    base of exactly 5,000,000 cents takes 10 percent."

    Oak St prices to a base of 4599975, some 400025 cents below the boundary, so
    the 15 percent tier applies and yields 689996 rather than a 10 percent 459998.

    Design: Difficulty/combinatorial_formula/project_total_contingency_tier_keyed_on_base_not_total
    """
    ctx = fixtures.adopted_program(api, OAK_ONLY)
    ctx = fixtures.draft_project(
        api, ctx, OAK_LINE, project_name="Oak St crack seal"
    )

    assert_money(ctx["lines"]["Oak St"]["line_cost_cents"], OAK_LINE_COST)
    assert ctx["project"]["bundle_base_cents"] == OAK_BUNDLE_BASE
    assert ctx["project"]["bundle_base_cents"] < 5000000
    assert_money(ctx["project"]["contingency_cents"], OAK_CONTINGENCY)
    assert ctx["project"]["contingency_cents"] != 459998, (
        "a 10 percent tier keyed on the total would produce this instead"
    )


def test_total_crossing_the_tier_boundary_does_not_rekey_the_tier(api):
    """Adding the contingency pushes the total past the boundary with no feedback.

    PRD: "Two further amounts ride on that base, and both are keyed on the base
    rather than on the total — keying them on the total would be circular, since
    the total contains them."

    The Oak St total lands at 5289971, some 289971 cents above the same boundary
    its base sat below, and the stored contingency is unchanged.

    Design: Difficulty/combinatorial_formula/project_total_contingency_tier_keyed_on_base_not_total
    """
    ctx = fixtures.adopted_program(api, OAK_ONLY)
    ctx = fixtures.draft_project(
        api, ctx, OAK_LINE, project_name="Oak St crack seal"
    )

    assert_project_estimate(ctx["project"], OAK_BUNDLE_BASE, OAK_CONTINGENCY, 0, OAK_TOTAL)
    assert ctx["project"]["project_total_estimate_cents"] > 5000000
    assert ctx["project"]["bundle_base_cents"] < 5000000
