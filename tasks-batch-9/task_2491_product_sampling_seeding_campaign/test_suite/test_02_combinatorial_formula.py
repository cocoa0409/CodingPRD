"""Multi-input formulas whose operation order changes the answer."""

import pytest

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers import campaign_manager_headers
from test_helpers.fixtures import KitSpec


class TestKitAssemblyRoundingOrder:
    """Rounding each line before summing, not summing before rounding."""

    @staticmethod
    def _draft_campaign_with_fractional_lines(api):
        """Three lines whose raw extended costs are 283.4, 116.40 and 55.4.

        Rounding each line first gives 283 + 116 + 55 = 454; summing the raw
        products to 455.20 and rounding once gives 455.
        """
        campaign = fx.create_campaign(api, name="Rounding Lab")
        kit_lines = fx.build_kit(api, campaign["id"])
        return campaign, kit_lines

    def test_each_line_extended_cost_is_rounded_to_a_whole_cent_first(self, api):
        """PRD §2.6: "Kit assembly rounds **per line and then sums**: each
        line's extended cost is rounded to a whole cent first, and the
        campaign's per-kit assembly cost is the sum of those already-rounded
        line values."

        Design: Difficulty/combinatorial_formula/kit_assembly_rounding_order_round_per_line_then_sum
        """
        campaign, kit_lines = self._draft_campaign_with_fractional_lines(api)
        manager = campaign_manager_headers()

        opened = validate_success(api.open_screening(manager, campaign["id"]))

        hero = validate_success(api.get_kit_line(manager, kit_lines[0]["id"]))
        accessory = validate_success(api.get_kit_line(manager, kit_lines[1]["id"]))
        insert = validate_success(api.get_kit_line(manager, kit_lines[2]["id"]))

        assert hero["extended_cost_cents"] == 283
        assert accessory["extended_cost_cents"] == 116
        assert insert["extended_cost_cents"] == 55
        assert opened["kit_assembly_unit_cost_cents"] == 454
        assert opened["status"] == "SCREENING_OPEN"

    def test_the_sum_raw_then_round_reading_is_rejected(self, api):
        """PRD §2.6: "Summing the unrounded line values and rounding once at the
        end is explicitly not the rule, and produces a different figure whenever
        the discarded per-line fractions accumulate past half a cent."

        Design: Difficulty/combinatorial_formula/kit_assembly_rounding_order_round_per_line_then_sum
        """
        campaign, _ = self._draft_campaign_with_fractional_lines(api)
        manager = campaign_manager_headers()

        opened = validate_success(api.open_screening(manager, campaign["id"]))

        assert opened["kit_assembly_unit_cost_cents"] != 455
        assert opened["kit_assembly_unit_cost_cents"] == 454

    def test_opening_screening_leaves_the_provisional_cost_at_zero(self, api):
        """PRD §3.6: "When the population is empty the value is zero rather than
        undefined."

        Design: Difficulty/combinatorial_formula/kit_assembly_rounding_order_round_per_line_then_sum
        """
        campaign, _ = self._draft_campaign_with_fractional_lines(api)
        manager = campaign_manager_headers()

        opened = validate_success(api.open_screening(manager, campaign["id"]))

        assert opened["cost_per_sample_provisional_cents"] == 0
        assert opened["status"] == "SCREENING_OPEN"


class TestDiversionPenaltyEvaluationOrder:
    """The penalty tier comes from the pre-penalty base and nothing else."""

    @staticmethod
    def _campaign_ready_for_lift(api):
        """Three delivered samples at 420 cents each, two of them substantiated.

        A single 360-cent line and 60 cents of freight commit 420 per shipment,
        so three deliveries commit 1260 in total; substantiating two of the
        three leaves one effective sample.
        """
        world = fx.delivered_sample_world(
            api,
            panelist_count=3,
            kit_specs=(KitSpec("HERO-L", "HERO_PRODUCT", 360, 1, 0.0, 10),),
            center_overrides={"freight_cents_per_kit": 60},
            wave_overrides={"planned_capacity_units": 20},
            objective_type="REVIEW_ACQUISITION",
            name="Lift Lab",
        )
        fx.open_review_window(api, world.campaign_id)

        fx.create_purchase_match(
            api,
            world.enrollment_id(2),
            retailer_channel_code="BIGBOX-WEB",
            purchase_amount_cents=4999,
            purchased_at="2026-08-05T00:00:00Z",
            match_confidence=0.9,
        )

        for index in (0, 1):
            case = fx.open_diversion_case(
                api,
                world.panelist_id(index),
                world.shipment_id(index),
                evidence_note="kit listed on a resale marketplace",
            )
            fx.investigate_case(api, case["id"])
            fx.substantiate_case(api, case["id"])

        world.campaign = fx.get_campaign(api, world.campaign_id)
        return world

    def test_penalty_rate_comes_from_the_step_one_base_cost(self, api):
        """PRD §3.9: "Step two selects `penalty_rate_pct` **from that step-one
        figure and from nothing else**: 10 percent when the base cost per sample
        is below 500 cents, 20 percent when it is below 1500 cents, and 35
        percent at 1500 cents or above."

        Design: Difficulty/combinatorial_formula/lift_diversion_penalty_tier_from_pre_penalty_base
        """
        world = self._campaign_ready_for_lift(api)
        manager = campaign_manager_headers()

        assert world.campaign["budget_committed_cents"] == 1260
        assert world.campaign["delivered_sample_count"] == 3
        assert world.campaign["substantiated_diversion_count"] == 2

        analysis = validate_success(
            api.create_lift_analysis(
                manager, world.campaign_id, "ITT", world.campaign["version"]
            ),
            201,
        )

        assert analysis["diverted_unit_count"] == 2
        assert analysis["effective_sample_count"] == 1
        assert analysis["base_cost_per_sample_cents"] == 1260
        assert analysis["penalty_rate_pct"] == 20
        assert analysis["diversion_penalty_cents"] == 504
        assert analysis["adjusted_cost_per_sample_cents"] == 1764

    def test_the_tier_is_not_re_derived_from_the_adjusted_figure(self, api):
        """PRD §3.9: "**Re-deriving the tier from the step-four figure is
        forbidden**: a campaign whose base cost sits just below a tier boundary
        and whose adjusted cost lands above it keeps the lower rate, because the
        tier was fixed at step two and the penalty is charged once."

        Design: Difficulty/combinatorial_formula/lift_diversion_penalty_tier_from_pre_penalty_base
        """
        world = self._campaign_ready_for_lift(api)
        manager = campaign_manager_headers()

        analysis = validate_success(
            api.create_lift_analysis(
                manager, world.campaign_id, "ITT", world.campaign["version"]
            ),
            201,
        )

        assert analysis["adjusted_cost_per_sample_cents"] != 2142
        assert analysis["adjusted_cost_per_sample_cents"] == 1764
        assert analysis["penalty_rate_pct"] == 20

    def test_intent_to_treat_counts_only_enrollments_still_screen_passed(self, api):
        """PRD §3.9: "Under `ITT` — intent-to-treat — the treated group is every
        enrollment of the campaign whose `holdout_flag` is false and whose
        `screening_status` is `SCREEN_PASSED`, whether or not a sample ever
        reached them."

        Design: Difficulty/combinatorial_formula/lift_diversion_penalty_tier_from_pre_penalty_base
        """
        world = self._campaign_ready_for_lift(api)
        manager = campaign_manager_headers()

        analysis = validate_success(
            api.create_lift_analysis(
                manager, world.campaign_id, "ITT", world.campaign["version"]
            ),
            201,
        )

        assert analysis["treated_count"] == 1
        assert analysis["holdout_count"] == 0
        assert analysis["treated_converted_count"] == 1
        assert analysis["treated_conversion_rate"] == pytest.approx(1.0, abs=0.01)
        assert analysis["holdout_conversion_rate"] == pytest.approx(0.0, abs=0.01)
        assert analysis["lift_pct"] == pytest.approx(100.00, abs=0.01)
        assert analysis["power_status"] == "INSUFFICIENT_POWER"
        assert analysis["superseded"] is False
