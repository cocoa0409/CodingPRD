"""Formulas whose several inputs interact rather than simply add.

Each scenario drives one formula from more than one direction so that the
saturation points, the pinned evaluation order and the pinned rounding order
are all observable from the outside.
"""

from test_helpers import (
    LineSpec,
    LotSpec,
    RecipeSpec,
    StepSpec,
    USER_PROCESS_ENGINEER,
    advance_to_at_sort,
    build_line,
    two_recipe_line_spec,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_fields,
    assert_hours,
    assert_lot_state,
    assert_ratio,
)
from test_helpers.factories import wafer_result


# --------------------------------------------------------------------------
# Engineering change risk score
# --------------------------------------------------------------------------


class TestRecipeChangeRiskScore:
    def test_the_relative_move_term_saturates_at_a_ten_percent_shift(self, fab):
        """A forty-percent and an eighty-percent move score identically.

        PRD: "The second is a normalised, saturating relative move: take the
        absolute difference between `proposed_target` and the recipe's current
        `target_value`, divide it by that current `target_value`, divide the
        result by a normalising move of 0.10 — that is, a ten-percent shift
        saturates the term — take the smaller of that quotient and 1.0, and
        multiply by 25.0."

        Design: Difficulty/combinatorial_formula/recipe_change_risk_saturates_on_both_continuous_terms
        """
        recipe = fab.recipe("ETCH-100", "ETCH", 100.0, 100)

        forty_percent = fab.change_request(
            recipe["id"], "MINOR", 140.0, "Delta term at four times the normalising move"
        )
        eighty_percent = fab.change_request(
            recipe["id"], "MINOR", 180.0, "Delta term at eight times the normalising move"
        )

        # 10.0 class weight + a saturated 25.0 delta term + a 0-lot blast radius.
        assert_hours(forty_percent["risk_score"], 35.00, "risk_score")
        assert_hours(eighty_percent["risk_score"], 35.00, "risk_score")
        assert forty_percent["risk_score"] == eighty_percent["risk_score"]
        assert forty_percent["impact_lot_count"] == 0
        assert forty_percent["requires_full_requal"] is False
        assert eighty_percent["requires_full_requal"] is False

    def test_the_requal_threshold_is_inclusive_at_seventy(self, fab):
        """The class weight dominates, so a tiny critical move outranks a huge minor one.

        PRD: "A notice whose `risk_score` is 70.0 or higher has
        `requires_full_requal` set true, which is what drives the
        chamber-requalification cascade at implementation time; below 70.0 it is
        false."

        Design: Difficulty/combinatorial_formula/recipe_change_risk_saturates_on_both_continuous_terms
        """
        recipe = fab.recipe("ETCH-100", "ETCH", 100.0, 100)
        huge_minor = fab.change_request(
            recipe["id"], "MINOR", 180.0, "Delta term at eight times the normalising move"
        )

        # 60.0 + 25.0 * (0.005 / 0.10) = 61.25, still below the threshold.
        tiny_critical = fab.change_request(
            recipe["id"], "CRITICAL", 100.5, "Half-percent move on a critical parameter"
        )
        # 60.0 + 25.0 * (0.04 / 0.10) = 70.00, exactly on the threshold.
        four_percent_critical = fab.change_request(
            recipe["id"], "CRITICAL", 104.0, "Four-percent move on a critical parameter"
        )

        assert_hours(tiny_critical["risk_score"], 61.25, "risk_score")
        assert tiny_critical["requires_full_requal"] is False
        assert_hours(four_percent_critical["risk_score"], 70.00, "risk_score")
        assert four_percent_critical["requires_full_requal"] is True
        assert tiny_critical["risk_score"] > huge_minor["risk_score"]

        assert_fields(
            four_percent_critical,
            status="SUBMITTED",
            revision_round=0,
            author_user_id=USER_PROCESS_ENGINEER,
        )
        assert fab.read_recipe(recipe["id"])["status"] == "QUALIFIED"


# --------------------------------------------------------------------------
# Wafer start plan commitment pricing
# --------------------------------------------------------------------------


def _draft_plan_at_point_eight_six_eight(fab):
    """A LOGIC_N7 line whose plan prices out at a pre-surcharge 0.8680."""
    spec = LineSpec(
        recipes=[
            RecipeSpec("LITHO-100", "LITHO", 50.0, 100),
            RecipeSpec("ETCH-100", "ETCH", 100.0, 100),
        ],
        flow_code="FLOW-B",
        product_family="LOGIC_N7",
        steps=[
            StepSpec(10, "LITHO-1", 2.0, recipe_ix=0),
            StepSpec(20, "ETCH-1", 3.0, recipe_ix=1),
            StepSpec(30, "LITHO-2", 2.0, recipe_ix=0),
        ],
        planned_wafer_starts=62,
        capacity_budget_hours=500.0,
        cycle_time_target_days=4.0,
        commit_plan=False,
        lots=[],
    )
    return build_line(fab, spec)


class TestCapacityCommitmentTier:
    def test_tier_is_read_from_the_pre_surcharge_utilisation(self, fab):
        """62 starts against a 7.0 h flow tier at 0.8680, not at the post-surcharge ratio.

        PRD: "Third, `commitment_tier` is selected from that utilisation against
        inclusive lower bounds: `TIER_3` when the utilisation is 0.90 or more,
        otherwise `TIER_2` when it is 0.70 or more, otherwise `TIER_1` when it
        is 0.50 or more, otherwise `TIER_0`."

        Design: Difficulty/combinatorial_formula/capacity_commitment_tier_pinned_to_pre_surcharge_utilisation
        """
        env = _draft_plan_at_point_eight_six_eight(fab)
        assert_hours(env.flow["total_standard_hours"], 7.0, "total_standard_hours")

        committed = fab.commit_plan(env.plan["id"])

        # base 434.00, utilisation 0.8680 -> TIER_2 -> 12% -> 52.08.
        assert_fields(committed, commitment_tier="TIER_2", status="COMMITTED")
        assert_hours(committed["surcharge_hours"], 52.08, "surcharge_hours")
        assert_hours(committed["committed_hours"], 486.08, "committed_hours")
        assert committed["released_wafer_starts"] == 0

    def test_the_surcharge_never_re_tiers_the_plan(self, fab):
        """Re-tiering off 0.9722 would have priced the plan out of its own budget.

        PRD: "The pricing sequence is fixed and must be evaluated in exactly
        this order, because the tier looks circular and is resolved by reading
        the tier from the *pre-surcharge* utilisation only; the surcharge never
        re-tiers the plan."

        Design: Difficulty/combinatorial_formula/capacity_commitment_tier_pinned_to_pre_surcharge_utilisation
        """
        env = _draft_plan_at_point_eight_six_eight(fab)
        fab.commit_plan(env.plan["id"])

        stored = fab.read_plan(env.plan["id"])
        assert stored["commitment_tier"] != "TIER_3"
        assert float(stored["surcharge_hours"]) != 108.50
        assert float(stored["committed_hours"]) <= float(stored["capacity_budget_hours"])
        assert_common_fields(stored, expected_version=2)


# --------------------------------------------------------------------------
# Die sort yield and the speed-grade waterfall
# --------------------------------------------------------------------------


UNEQUAL_WAFERS = [
    wafer_result(1, 100, 90, edge_ring_fails=7, center_cluster_fails=1,
                 parametric_shift_fails=2),
    wafer_result(2, 10, 8, edge_ring_fails=2),
    wafer_result(3, 50, 47, edge_ring_fails=2, center_cluster_fails=1),
]


def _lot_at_sort(fab):
    env = build_line(
        fab, two_recipe_line_spec(lots=[LotSpec("LOT-001", 3, "STANDARD")])
    )
    advance_to_at_sort(fab, env, lot_ix=0)
    return env


class TestDieYieldRoundingOrder:
    def test_each_wafer_is_rounded_before_the_average_is_taken(self, fab):
        """Three very unequal wafers average unweighted, not pooled.

        PRD: "Working through the elements in ascending `wafer_slot`, each
        wafer's yield is its `good_die` divided by its `tested_die`, rounded to
        4 decimal places."

        Design: Difficulty/combinatorial_formula/die_yield_rounds_each_wafer_before_averaging
        """
        env = _lot_at_sort(fab)

        sort_run = fab.die_sort(env.lots[0]["id"], UNEQUAL_WAFERS)

        # (0.9000 + 0.8000 + 0.9400) / 3; pooling 145/160 would give 0.9063.
        assert_ratio(sort_run["sort_yield"], 0.8800, "sort_yield")
        assert float(sort_run["sort_yield"]) != 0.9063
        assert sort_run["good_die_total"] == 145
        assert_ratio(sort_run["yield_loss_ratio"], 0.0435, "yield_loss_ratio")
        assert_fields(sort_run, dominant_signature="EDGE_RING", status="SORTED")

    def test_the_waterfall_distributes_the_whole_good_die_pool(self, fab):
        """Premium takes its target, standard the remainder cap, value the rest.

        PRD: "The three buckets therefore always sum to exactly
        `good_die_total`, and all three are integers with no rounding."

        Design: Difficulty/combinatorial_formula/die_yield_rounds_each_wafer_before_averaging
        """
        env = _lot_at_sort(fab)
        sort_run = fab.die_sort(env.lots[0]["id"], UNEQUAL_WAFERS)

        binned = fab.bin_sort_run(sort_run["id"], 50, 60)

        assert_fields(
            binned,
            premium_die=50,
            standard_die=60,
            value_die=35,
            status="BINNED",
            premium_target_die=50,
            standard_target_die=60,
        )
        assert (
            binned["premium_die"] + binned["standard_die"] + binned["value_die"]
            == sort_run["good_die_total"]
        )
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), flow_state="COMPLETED")
