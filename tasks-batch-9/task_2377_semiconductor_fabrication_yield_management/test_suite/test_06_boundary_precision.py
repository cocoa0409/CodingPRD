"""Thresholds probed from exactly on the line and from one step off it.

Each scenario feeds two inputs that straddle a single boundary by the smallest
representable amount, so an implementation that compares with the wrong strictness
or rounds after comparing rather than before is caught by the pair.
"""

from test_helpers import (
    LotSpec,
    build_line,
    complete_step,
    open_run,
    two_recipe_line_spec,
)
from test_helpers.assertions import (
    assert_fields,
    assert_hours,
    assert_lot_state,
    assert_nulls,
    assert_ratio,
)


# --------------------------------------------------------------------------
# The upper control limit is inclusive, the upper spec limit is strict
# --------------------------------------------------------------------------


def _open_etch_run_under_a_chart(fab):
    """An open metrology run on a chart whose ucl is 106.00 and usl 110.00."""
    env = build_line(fab, two_recipe_line_spec(lots=[LotSpec("LOT-001", 3, "STANDARD")]))
    complete_step(fab, env, step_ix=0, lot_ix=0)
    env.run = open_run(fab, env, step_ix=1, lot_ix=0)
    return env


class TestControlLimitInclusiveness:
    def test_one_hundredth_below_the_control_limit_is_only_a_warning(self, fab):
        """105.99 against a 106.00 control limit stays a warning and opens nothing.

        PRD: "So the `classification` is `OUT_OF_SPEC` when the reading is
        strictly above `usl` or strictly below `lsl`; otherwise `OUT_OF_CONTROL`
        when the reading is at or above `ucl` or at or below `lcl`; otherwise
        `WARN` when the absolute deviation is at least twice `sigma`; otherwise
        `IN_CONTROL`."

        Design: Difficulty/boundary_precision_check/spc_control_limit_is_inclusive_at_exactly_ucl
        """
        env = _open_etch_run_under_a_chart(fab)
        chart_id = env.charts[0]["id"]
        assert fab.read_chart(chart_id)["status"] == "MONITORING"

        measurement = fab.measure(
            env.run["id"], chart_id, 105.99, env.operators[0]["id"]
        )

        assert measurement["classification"] == "WARN"
        assert_ratio(measurement["deviation_sigma"], 2.9950, "deviation_sigma")
        assert measurement["run_rule_triggered"] is False
        assert_nulls(measurement, "excursion_id")

        chart = fab.read_chart(chart_id)
        assert_fields(
            chart,
            status="MONITORING",
            last_side="ABOVE",
            consecutive_same_side_count=1,
            violation_count=0,
        )
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), hold_state="NONE")

    def test_exactly_on_the_control_limit_is_out_of_control(self, fab):
        """106.00 against the same 106.00 limit flips the classification and opens an excursion.

        PRD: "When the `classification` is `OUT_OF_CONTROL` or `OUT_OF_SPEC`, or
        `run_rule_triggered` is true, the chart's `violation_count` increments by
        1 and an **excursion** is opened: `source_type` `SPC`, `spc_chart_id`
        pointing at the chart, `lot_id` copied from the run's `lot_id`,
        `trigger_value` set to the reading rounded to 4 decimal places, and the
        measurement's own `excursion_id` set to the new excursion."

        Design: Difficulty/boundary_precision_check/spc_control_limit_is_inclusive_at_exactly_ucl
        """
        env = _open_etch_run_under_a_chart(fab)
        chart_id = env.charts[0]["id"]
        operator_id = env.operators[0]["id"]

        warning = fab.measure(env.run["id"], chart_id, 105.99, operator_id)
        violation = fab.measure(env.run["id"], chart_id, 106.0, operator_id)

        assert violation["classification"] == "OUT_OF_CONTROL"
        assert violation["classification"] != warning["classification"]
        assert_ratio(violation["deviation_sigma"], 3.0000, "deviation_sigma")
        # Two same-side points is short of the four the run rule needs.
        assert violation["run_rule_triggered"] is False
        assert violation["excursion_id"] is not None

        chart = fab.read_chart(chart_id)
        assert_fields(
            chart, last_side="ABOVE", consecutive_same_side_count=2, violation_count=1
        )

        excursion = fab.read_excursion(violation["excursion_id"])
        assert_fields(
            excursion,
            source_type="SPC",
            status="OPEN",
            severity_variant="PROVISIONAL",
            affected_lot_count=1,
            severity_band="LOW",
            spc_chart_id=chart_id,
            lot_id=env.lots[0]["id"],
        )
        assert_ratio(excursion["trigger_value"], 106.0000, "trigger_value")
        # 60.0 * (6/10) deviation + 3.0 for the single lot, no spec penalty.
        assert_hours(excursion["severity_score"], 39.00, "severity_score")
        assert_lot_state(fab.read_lot(env.lots[0]["id"]), hold_state="NONE")


# --------------------------------------------------------------------------
# The capacity tier lower bound is inclusive at 0.70
# --------------------------------------------------------------------------


def _two_draft_plans_over_one_flow(fab):
    """Two drafts differing only in budget: 500.0 hours and 501.0 hours."""
    env = build_line(fab, two_recipe_line_spec(commit_plan=False, lots=[]))
    env.tight_plan = env.plan
    env.loose_plan = fab.plan(
        env.flow["id"],
        env.flow["product_family"],
        50,
        501.0,
        30.0,
        "2026-08-10T00:00:00Z",
    )
    return env


class TestCapacityTierBoundary:
    def test_a_utilisation_of_exactly_seventy_percent_reaches_the_second_tier(self, fab):
        """350.00 hours against a 500.0 budget lands on the bound and is included.

        PRD: "Third, `commitment_tier` is selected from that utilisation against
        inclusive lower bounds: `TIER_3` when the utilisation is 0.90 or more,
        otherwise `TIER_2` when it is 0.70 or more, otherwise `TIER_1` when it is
        0.50 or more, otherwise `TIER_0`."

        Design: Difficulty/boundary_precision_check/capacity_tier_boundary_at_exactly_seventy_percent_utilisation
        """
        env = _two_draft_plans_over_one_flow(fab)
        assert_hours(env.flow["total_standard_hours"], 7.0, "total_standard_hours")

        committed = fab.commit_plan(env.tight_plan["id"])

        # base 350.00, utilisation exactly 0.7000, so 12 percent of 350.00.
        assert_fields(committed, commitment_tier="TIER_2", status="COMMITTED")
        assert_hours(committed["surcharge_hours"], 42.00, "surcharge_hours")
        assert_hours(committed["committed_hours"], 392.00, "committed_hours")

    def test_one_extra_budget_hour_drops_the_plan_a_whole_tier(self, fab):
        """A 0.6986 utilisation prices at five percent instead of twelve.

        PRD: "Fourth, the surcharge rate follows from the tier: zero for
        `TIER_0`, five percent for `TIER_1`, twelve percent for `TIER_2`, and
        twenty-five percent for `TIER_3`."

        Design: Difficulty/boundary_precision_check/capacity_tier_boundary_at_exactly_seventy_percent_utilisation
        """
        env = _two_draft_plans_over_one_flow(fab)

        tight = fab.commit_plan(env.tight_plan["id"])
        loose = fab.commit_plan(env.loose_plan["id"])

        # 350.00 / 501.0 rounds to 0.6986, one ten-thousandth under the bound.
        assert_fields(loose, commitment_tier="TIER_1", status="COMMITTED")
        assert_hours(loose["surcharge_hours"], 17.50, "surcharge_hours")
        assert_hours(loose["committed_hours"], 367.50, "committed_hours")
        assert loose["commitment_tier"] != tight["commitment_tier"]
        assert float(loose["surcharge_hours"]) != float(tight["surcharge_hours"])


# --------------------------------------------------------------------------
# The requalification threshold is inclusive at a rounded 70.00
# --------------------------------------------------------------------------


class TestRequalThresholdBoundary:
    def test_a_score_of_exactly_seventy_demands_full_requalification(self, fab):
        """A four-percent critical move scores on the bound and is included.

        PRD: "A notice whose `risk_score` is 70.0 or higher has
        `requires_full_requal` set true, which is what drives the
        chamber-requalification cascade at implementation time; below 70.0 it is
        false."

        Design: Difficulty/boundary_precision_check/requal_threshold_boundary_at_exactly_seventy_risk_score
        """
        recipe = fab.recipe("ETCH-100", "ETCH", 100.0, 100)

        notice = fab.change_request(
            recipe["id"], "CRITICAL", 104.0, "Four percent etch depth increase"
        )

        # 60.0 class weight + 25.0 * (0.04 / 0.10), with no lots exposed.
        assert notice["impact_lot_count"] == 0
        assert_hours(notice["risk_score"], 70.00, "risk_score")
        assert notice["requires_full_requal"] is True
        assert_fields(notice, status="SUBMITTED", revision_round=0)

    def test_the_score_is_rounded_before_it_meets_the_threshold(self, fab):
        """69.975 rounds to 69.98 and still falls short of the bound.

        PRD: "The `risk_score` is the sum of the three terms rounded to 2 decimal
        places."

        Design: Difficulty/boundary_precision_check/requal_threshold_boundary_at_exactly_seventy_risk_score
        """
        on_the_bound_recipe = fab.recipe("ETCH-100", "ETCH", 100.0, 100)
        under_the_bound_recipe = fab.recipe("ETCH-200", "ETCH", 100.0, 100)

        on_the_bound = fab.change_request(
            on_the_bound_recipe["id"], "CRITICAL", 104.0,
            "Four percent etch depth increase",
        )
        under_the_bound = fab.change_request(
            under_the_bound_recipe["id"], "CRITICAL", 103.99,
            "Three-point-nine-nine percent etch depth increase",
        )

        assert under_the_bound["impact_lot_count"] == 0
        assert_hours(under_the_bound["risk_score"], 69.98, "risk_score")
        assert under_the_bound["requires_full_requal"] is False
        assert on_the_bound["requires_full_requal"] != under_the_bound["requires_full_requal"]
        assert_fields(under_the_bound, status="SUBMITTED", revision_round=0)
