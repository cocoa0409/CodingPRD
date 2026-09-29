"""Formulas whose factors interact: nested clamps, per-line rounding, tier keys."""
import pytest

from test_helpers import fixtures as fx, parse_instant


class TestMethodScoreNestedClamps:
    #: Every factor is at or beyond its own clamp, so the raw sum overshoots the cap.
    MAXIMAL_SURVEY = {
        "survey_method": "MAGNETOMETER",
        "tanks_detected_count": 1,
        "tank_capacity_gallons": 1000,
        "tank_depth_to_top_inches": 200,
        "tank_distance_to_foundation_inches": 0,
        "tank_under_structure": True,
        "tank_material": "STEEL",
    }

    def test_each_factor_is_clamped_on_its_own_before_the_sum_is_capped(self, api):
        """PRD §3.1: "The five clamped factors are added together, that raw sum is capped at 100.0, and *only then* is the capped figure rounded half up to two decimal places to become `method_score`."
        PRD §3.1: "Take the depth of cover in inches, subtract the 24 inches of cover that are treated as free, multiply the remainder by half a point per inch, then clamp the result into the range from 0.0 to 40.0."
        PRD §3.1: "Take 60 inches — the clearance below which the foundation is considered at concern — subtract the tank's actual clearance to the foundation, multiply the remainder by three quarters of a point per inch, then clamp into the range from 0.0 to 30.0."

        Design: Difficulty/combinatorial_formula/method_score_mode_a_nested_clamps_over_five_factors
        """
        ctx = fx.project_at_intake()
        project = fx.record_sweep_survey(ctx["project"]["id"], **self.MAXIMAL_SURVEY)

        assert project["method_score"] == pytest.approx(100.00, abs=0.01), (
            "the clamped factors 40.0 + 30.0 + 35.0 + 15.0 + 10.0 sum to 130.0, which "
            f"the cap brings to 100.00, got {project['method_score']}"
        )
        assert project["method_score"] != pytest.approx(193.00, abs=0.01), (
            "leaving the depth and proximity factors unclamped would give 88.0 + 45.0 "
            "+ 35.0 + 15.0 + 10.0 = 193.0, which the per-factor clamps forbid"
        )
        assert project["method_score"] != pytest.approx(130.00, abs=0.01), (
            "clamping each factor but omitting the 100.0 cap on the sum would give "
            "130.0, which the cap forbids"
        )

    def test_capped_score_at_or_above_the_threshold_recommends_abandonment(self, api):
        """PRD §3.1: "`recommended_method` is then `ABANDONMENT_IN_PLACE` when `method_score` is at least 55.00, and `REMOVAL` otherwise."
        PRD §3.1: "The sweep survey advances the project `INTAKE → SURVEYED` and records the `survey_method` used — `GPR` for ground-penetrating radar, `MAGNETOMETER`, or `PROBE_ROD` — together with `tanks_detected_count` and, stamped from the logical clock, `survey_completed_at`."

        Design: Difficulty/combinatorial_formula/method_score_mode_a_nested_clamps_over_five_factors
        """
        ctx = fx.project_at_intake(clock="2026-08-03T08:00:00Z")
        project = fx.record_sweep_survey(ctx["project"]["id"], **self.MAXIMAL_SURVEY)

        assert project["recommended_method"] == "ABANDONMENT_IN_PLACE", (
            "a score of 100.00 is well past the 55.00 threshold, got "
            f"{project['recommended_method']}"
        )
        assert project["status"] == "SURVEYED", (
            f"the survey advances INTAKE to SURVEYED, got {project['status']}"
        )
        assert parse_instant(project["survey_completed_at"]) == parse_instant(
            "2026-08-03T08:00:00Z"
        ), (
            "the completion instant is stamped from the logical clock, got "
            f"{project['survey_completed_at']}"
        )


class TestRemediationCostPerLineRounding:
    def test_each_line_amount_is_rounded_half_up_before_any_summation(self, api):
        """PRD §2.9: "A change order's `line_amount_cents` is rounded half up to whole cents *per line, before any summation*."
        PRD §3.7: "For each such row, multiply its `additional_cubic_yards` by its `unit_rate_cents`, then by the disposal multiplier for its `disposal_class`: a factor of 1.0 for `NON_HAZARDOUS` soil, and a factor of 1.85 for `HAZARDOUS` soil, reflecting the eighty-five percent premium a licensed hazardous-waste facility charges over an ordinary landfill."

        Design: Difficulty/combinatorial_formula/remediation_cost_mode_b_round_each_line_before_summation
        """
        ctx = fx.project_remediation_active_gross()

        first = fx.approved_change_order(ctx, 3.5, 1001, "NON_HAZARDOUS")
        assert first["line_amount_cents"] == 3504, (
            "3.5 cubic yards at 1001 cents is 3503.5 cents, which rounds half up to "
            f"3504, got {first['line_amount_cents']}"
        )

        second = fx.approved_change_order(ctx, 2.5, 1001, "NON_HAZARDOUS")
        assert second["line_amount_cents"] == 2503, (
            "2.5 cubic yards at 1001 cents is 2502.5 cents, which rounds half up to "
            f"2503, got {second['line_amount_cents']}"
        )

    def test_cost_sums_already_rounded_lines_rather_than_rounding_the_sum_once(
        self, api
    ):
        """PRD §3.7: "*Step two* sums those already-rounded integer line amounts. Rounding per line before summing is required; summing the unrounded products and rounding once at the end produces a different figure whenever two or more lines carry a half-cent remainder, and is wrong."
        PRD §3.7: "Once the latch is true, `remediation_cost_cents` is the flat mobilization charge of 185,000 cents — one thousand eight hundred fifty dollars — plus the line total from step two."
        PRD §3.7: "The project's `approved_scope_cubic_yards` is always its `baseline_scope_cubic_yards` plus the sum of `additional_cubic_yards` over the project's change orders whose `status` is `APPROVED`."

        Design: Difficulty/combinatorial_formula/remediation_cost_mode_b_round_each_line_before_summation
        """
        ctx = fx.project_remediation_active_gross()
        fx.approved_change_order(ctx, 3.5, 1001, "NON_HAZARDOUS")
        fx.approved_change_order(ctx, 2.5, 1001, "NON_HAZARDOUS")

        project = fx.read_project(ctx["project"]["id"])
        assert project["remediation_cost_cents"] == 191007, (
            "185,000 mobilization plus the rounded lines 3504 and 2503 is 191,007 "
            f"cents, got {project['remediation_cost_cents']}"
        )
        assert project["remediation_cost_cents"] != 191006, (
            "summing 3503.5 and 2502.5 to 6006.0 and rounding once would give "
            "191,006 cents, which the per-line rounding rule forbids"
        )
        assert project["approved_scope_cubic_yards"] == pytest.approx(14.0, abs=0.01), (
            "the 8.0 baseline plus 3.5 plus 2.5 approved cubic yards is 14.0, got "
            f"{project['approved_scope_cubic_yards']}"
        )


class TestTrustFundCapTierKey:
    #: One cent above the first tier boundary, and above it only on the gross figure.
    CLAIMED_CENTS = 5000001

    def test_cap_tier_is_selected_by_the_gross_figure(self, api):
        """PRD §3.9: "`cap_cents` is the reimbursement ceiling selected by the gross figure across three tiers: forty thousand dollars when the gross figure is at most fifty thousand dollars; ninety thousand dollars when it is at most one hundred twenty thousand dollars; and one hundred twenty-five thousand dollars above that."
        PRD §3.9: "The gross figure is the claim's `claimed_costs_cents`."

        Design: Difficulty/combinatorial_formula/trust_fund_mode_c_cap_tier_keyed_on_gross_before_deductible
        """
        ctx = fx.project_cleared()
        claim = fx.create_claim(
            ctx["project"]["id"],
            variant="FINAL_SETTLEMENT",
            claimed_costs_cents=self.CLAIMED_CENTS,
        )

        assert claim["cap_cents"] == 9000000, (
            "5,000,001 cents gross is one cent past the 5,000,000-cent boundary, so "
            f"the 9,000,000-cent tier applies, got {claim['cap_cents']}"
        )
        assert claim["admin_fee_cents"] == 175000, (
            "3.5 percent of the 5,000,001-cent capped figure is 175,000.035, which "
            f"rounds half up to 175,000 cents, got {claim['admin_fee_cents']}"
        )

    def test_eligible_amount_follows_the_gross_keyed_tier_not_a_net_keyed_one(
        self, api
    ):
        """PRD §3.9: "Under `FINAL_SETTLEMENT`, the deductible is subtracted from the gross figure first and the cap is applied to the net: take the gross figure less `deductible_cents`, take the smaller of that difference and `cap_cents`, floor the result at zero, and subtract `admin_fee_cents`."
        PRD §3.9: "`unreimbursed_balance_cents` is `eligible_amount_cents` less `reimbursed_amount_cents`, the latter being 0 until cash is actually disbursed."

        Design: Difficulty/combinatorial_formula/trust_fund_mode_c_cap_tier_keyed_on_gross_before_deductible
        """
        ctx = fx.project_cleared()
        claim = fx.create_claim(
            ctx["project"]["id"],
            variant="FINAL_SETTLEMENT",
            claimed_costs_cents=self.CLAIMED_CENTS,
        )

        assert claim["eligible_amount_cents"] == 4775001, (
            "4,950,001 net of the deductible is below the 9,000,000-cent cap, so the "
            "eligible amount is 4,950,001 less the 175,000-cent fee, got "
            f"{claim['eligible_amount_cents']}"
        )
        assert claim["eligible_amount_cents"] != 3860000, (
            "keying the tier on the post-deductible figure would select the "
            "4,000,000-cent cap and yield 3,860,000 cents, which the gross-keyed "
            "tier rule forbids"
        )
        assert claim["unreimbursed_balance_cents"] == 4775001, (
            "with nothing disbursed the balance equals the eligible amount, got "
            f"{claim['unreimbursed_balance_cents']}"
        )
        assert claim["reimbursed_amount_cents"] == 0, (
            "a fresh claim has disbursed nothing, got "
            f"{claim['reimbursed_amount_cents']}"
        )
