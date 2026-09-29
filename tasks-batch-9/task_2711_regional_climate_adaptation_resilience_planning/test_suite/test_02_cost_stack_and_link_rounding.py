"""Pinned arithmetic: per-link rounding order and the pinned five-step cost stack."""

from test_helpers import (
    assert_fields,
    assert_project_dimensions,
    create_analysis,
    create_asset,
    create_asset_link,
    create_assessed_assessment,
    create_harbor,
    create_plan_cycle,
    create_project,
    create_published_profile,
    create_screened_project,
    rank_asset,
    read_asset_link,
    read_project,
    screen_project,
)


class TestPerLinkRoundingOrder:
    """Rounding each link before summing is normative and shifts the answer by a cent."""

    @staticmethod
    def _three_link_project():
        harbor = create_harbor()
        cycle = create_plan_cycle(
            quorum_weight_bps=6600, max_revision_rounds=1, required_session_count=1
        )
        profile = create_published_profile(harbor["id"], exposure_index=0.80)

        assets = []
        for spec in (
            dict(
                name="Harbor Water Treatment Plant",
                asset_class="WATER",
                replacement_value_cents=1200000000,
                service_population=150000,
                redundancy_factor=0.25,
                is_shared=True,
            ),
            dict(
                name="Harbor Pump Substation",
                asset_class="POWER",
                replacement_value_cents=400000000,
                service_population=40000,
                redundancy_factor=0.10,
                is_shared=False,
            ),
            dict(
                name="Harbor Causeway",
                asset_class="TRANSPORT",
                replacement_value_cents=200000000,
                service_population=20000,
                redundancy_factor=0.10,
                is_shared=False,
            ),
        ):
            asset = create_asset(harbor["id"], **spec)
            create_assessed_assessment(
                profile["id"], asset["id"], method="ADDITIVE_WEIGHTED"
            )
            assets.append(rank_asset(asset["id"]))

        project = create_screened_project(
            cycle["id"],
            harbor["id"],
            name="Harbor Levee Raise",
            strategy_type="PROTECT",
            base_cost_cents=42000000,
            service_life_years=30,
            cobenefit_points=12,
            feasibility_score=0.70,
        )
        links = [
            create_asset_link(
                project["id"], harbor["id"], assets[0]["id"], 3333333,
                benefit_reaches_disadvantaged=True,
            ),
            create_asset_link(
                project["id"], harbor["id"], assets[1]["id"], 2777777,
                benefit_reaches_disadvantaged=False,
            ),
            create_asset_link(
                project["id"], harbor["id"], assets[2]["id"], 1111111,
                benefit_reaches_disadvantaged=True,
            ),
        ]
        return harbor, project, links

    def test_link_sequence_numbers_the_links_in_creation_order(self):
        """Three links on one project are stamped 1, 2 and 3 in creation order.

        PRD 3.6: "Each accepted link is stamped with a `link_sequence` equal to one
        plus the count of links already held by that project, ordered by
        `created_at` ascending — so the first link on a project is 1, the second is
        2, and so on."  That ordering is load bearing because "it pins the per-line
        rounding order of the discounted benefit-cost calculation below".

        Design: Difficulty/combinatorial_formula/bca_per_link_rounding_then_sum_pinned
        """
        _, _, links = self._three_link_project()

        for expected, link in enumerate(links, start=1):
            assert_fields(
                read_asset_link(link["id"]),
                {"link_sequence": expected},
                f"link created in position {expected}",
            )

    def test_benefit_rounds_each_link_before_summing_them(self):
        """The discounted benefit reads 89620837, not the sum-then-round 89620838.

        PRD 3.6: "Then, **for each link in `link_sequence` ascending order**, the
        link's `avoided_loss_annual_cents` is multiplied by the annuity factor and
        that product is rounded half up to whole cents; `benefit_measure_cents` is
        the sum of those already-rounded per-link amounts."  The specification is
        explicit about the consequence: "Summing the raw products and rounding once
        at the end can differ by a cent and is wrong."

        Design: Difficulty/combinatorial_formula/bca_per_link_rounding_then_sum_pinned
        """
        harbor, project, _ = self._three_link_project()

        analysis = create_analysis(
            project["id"], harbor["id"], method="DISCOUNTED_NPV", discount_rate_bps=700
        )

        assert analysis["benefit_measure_cents"] == 89620837, (
            "benefit_measure_cents must round each link before summing, giving "
            f"89620837; got {analysis['benefit_measure_cents']}"
        )
        assert analysis["benefit_measure_cents"] != 89620838, (
            "89620838 is the sum-then-round answer the specification rules out"
        )
        assert_fields(
            analysis,
            {"cost_measure_cents": 63998724, "bcr": 1.4004, "grant_eligible": True},
            "DISCOUNTED_NPV analysis over three links",
        )


class TestPinnedCostStack:
    """The administration rate tier is keyed on the escalated cost, never the total."""

    @staticmethod
    def _proposed_levee_project():
        harbor = create_harbor()
        cycle = create_plan_cycle(
            quorum_weight_bps=6600, max_revision_rounds=1, required_session_count=1
        )
        project = create_project(
            cycle["id"],
            harbor["id"],
            name="Harbor Levee Raise",
            strategy_type="PROTECT",
            base_cost_cents=42000000,
            service_life_years=30,
            cobenefit_points=12,
            feasibility_score=0.70,
        )
        return harbor, project

    def test_admin_rate_band_reads_the_escalated_cost_not_the_total(self):
        """A 47040000-cent escalated cost stays in the 900 bps band despite a 51273600 total.

        PRD 3.5: "`admin_rate_bps` is selected from a three-band schedule keyed on
        the **Step 1 result**, not on the eventual total."  And: "**Step 2 is never
        re-evaluated after Step 4.** Adding the administration fee can push the
        running amount across the five-hundred-thousand-dollar band boundary, but
        the administration rate stays the one that Step 1's result selected."

        Design: Difficulty/combinatorial_formula/program_cost_stack_admin_tier_keyed_on_escalated_not_total
        """
        _, project = self._proposed_levee_project()

        screened = screen_project(project["id"])

        assert_fields(
            screened,
            {
                "escalated_cost_cents": 47040000,
                "admin_rate_bps": 900,
                "admin_fee_cents": 4233600,
                "total_program_cost_cents": 51273600,
            },
            "screened PROTECT project",
        )
        assert screened["admin_fee_cents"] != 2822400, (
            "2822400 is the fee produced by keying the administration rate on the "
            "total instead of on the escalated cost"
        )
        assert screened["total_program_cost_cents"] != 49862400, (
            "49862400 is the total produced by re-keying the administration rate "
            "after Step 4"
        )

    def test_match_share_and_screen_score_follow_the_pinned_stack(self):
        """The match band reads the total, and the screen score rounds once to 0.6925.

        PRD 3.5: "`grant_match_share_bps` is selected from a second three-band
        schedule keyed on `total_program_cost_cents`."  And: "`screen_score` is then
        the cost component weighted at 0.40, plus the co-benefit component weighted
        at 0.25, plus the feasibility component weighted at 0.35 — with the cost
        component carried into that weighted sum **unrounded**, and the sum rounded
        half up, once, to 4 fractional digits."

        Design: Difficulty/combinatorial_formula/program_cost_stack_admin_tier_keyed_on_escalated_not_total
        """
        _, project = self._proposed_levee_project()

        screened = screen_project(project["id"])

        assert_fields(
            screened,
            {"grant_match_share_bps": 2500, "screen_score": 0.6925},
            "screened PROTECT project",
        )
        assert_project_dimensions(
            read_project(project["id"]),
            screening="SCREENED_IN",
            analysis="NOT_ANALYZED",
            program="UNPROGRAMMED",
        )
