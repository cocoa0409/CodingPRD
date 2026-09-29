"""The six-step deposit-market concentration screen."""
from test_helpers.assertions import assert_competitive_analysis, assert_deposit_market
from test_helpers.fixtures import (
    kestrel_market_world,
    read_application,
    read_market,
    rosewood_market_world,
    run_competitive_analysis,
)


class TestOverlappingThreeInstitutionMarket:
    """A market where two of three participants combine."""

    def test_the_market_aggregates_from_the_includable_branch_set(self):
        """PRD §2.8: "A deposit market's `total_deposits_usd` is the sum of `deposits_usd` over its
        includable branches."
        PRD §2.8: "A market's `participant_count` is the number of distinct `institution_id` values
        among the owners of its includable branches."

        Design: Difficulty/combinatorial_formula/hhi_screen_nonlinear_combination_across_three_institutions
        """
        world = kestrel_market_world()

        market = read_market(world["market"]["id"])

        assert_deposit_market(market)
        assert market["total_deposits_usd"] == 1_000_000_000
        assert market["participant_count"] == 3
        assert market["hhi_current"] == 5400, (
            f"20/10/70 percent shares square and sum to 5400, got {market['hhi_current']}"
        )

    def test_a_delta_of_exactly_400_lands_on_mitigation_required(self):
        """PRD §3.5: "Otherwise, if `hhi_post_unmitigated` is at least 2500 **and**
        `hhi_delta_unmitigated` is strictly greater than 400, `screen_result` is
        `PRESUMPTIVE_VIOLATION`."
        PRD §3.5: "Note the two boundaries carefully: a market can pass on either the absolute-level
        branch or the delta branch, and a delta of exactly 400 at a post-merger level of 2500 or
        more is `MITIGATION_REQUIRED`, not `PRESUMPTIVE_VIOLATION`."

        Design: Difficulty/combinatorial_formula/hhi_screen_nonlinear_combination_across_three_institutions
        """
        world = kestrel_market_world()

        analysis = run_competitive_analysis(world["application"]["id"], world["market"]["id"])

        assert_competitive_analysis(analysis)
        assert analysis["combined_market_deposits_usd"] == 300_000_000
        assert analysis["hhi_pre_merger"] == 5400
        assert analysis["hhi_post_unmitigated"] == 5800
        assert analysis["hhi_delta_unmitigated"] == 400
        assert analysis["screen_result"] == "MITIGATION_REQUIRED"

    def test_the_divestiture_search_reports_the_smallest_clearing_million(self):
        """PRD §3.5: "Otherwise the service searches for the smallest whole multiple of one million
        dollars that would clear the screen, testing one million, then two million, then three
        million and so on, never exceeding `combined_market_deposits_usd`."
        PRD §3.5: "If either half fails, `mitigation_satisfied` is false, and a freshly created
        analysis with no designations carries `designated_divestiture_deposits_usd` of 0 and
        `mitigation_satisfied` false unless the screen itself passed."

        Design: Difficulty/combinatorial_formula/hhi_screen_nonlinear_combination_across_three_institutions
        """
        world = kestrel_market_world()

        analysis = run_competitive_analysis(world["application"]["id"], world["market"]["id"])

        assert analysis["required_divestiture_deposits_usd"] == 39_000_000, (
            "the search walks one million at a time until the trial delta drops to 200 or less, "
            f"got {analysis['required_divestiture_deposits_usd']}"
        )
        assert analysis["designated_divestiture_deposits_usd"] == 0
        assert analysis["hhi_post_mitigated"] == 5800, (
            "with nothing designated the mitigated index equals the unmitigated one"
        )
        assert analysis["mitigation_satisfied"] is False

    def test_an_unmitigated_market_rolls_the_application_posture_up(self):
        """PRD §3.5: "Otherwise, if any analysis has `screen_result` `MITIGATION_REQUIRED` and
        `mitigation_satisfied` false, the posture is `MITIGATION_REQUIRED`."

        Design: Difficulty/combinatorial_formula/hhi_screen_nonlinear_combination_across_three_institutions
        """
        world = kestrel_market_world()
        run_competitive_analysis(world["application"]["id"], world["market"]["id"])

        application = read_application(world["application"]["id"], world["acquirer"]["id"])

        assert application["competitive_posture"] == "MITIGATION_REQUIRED"


class TestDeltaExactlyAtTheSafeHarbour:
    """A delta of exactly 200 passes on the delta branch."""

    def test_a_delta_of_exactly_200_passes_the_screen(self):
        """PRD §3.5: "Otherwise, if `hhi_delta_unmitigated` is at most 200, `screen_result` is
        `PASS` — a delta of exactly 200 passes on this branch."

        Design: Difficulty/boundary_precision_check/hhi_delta_exactly_at_safe_harbor_passes_the_screen
        """
        world = rosewood_market_world()

        analysis = run_competitive_analysis(world["application"]["id"], world["market"]["id"])

        assert analysis["hhi_pre_merger"] == 2750
        assert analysis["hhi_post_unmitigated"] == 2950, (
            "the post-merger level of 2950 is above the 1800 MSA ceiling, so the absolute-level "
            "branch cannot be what passed the screen"
        )
        assert analysis["hhi_delta_unmitigated"] == 200
        assert analysis["screen_result"] == "PASS"

    def test_a_passing_screen_requires_no_divestiture_and_is_already_mitigated(self):
        """PRD §3.5: "When `screen_result` is `PASS`, `required_divestiture_deposits_usd` is 0."
        PRD §3.5: "`mitigation_satisfied` is true when two things both hold:
        `designated_divestiture_deposits_usd` is at least `required_divestiture_deposits_usd`,
        **and** either `hhi_post_mitigated` is strictly below the market's ceiling or
        `hhi_post_mitigated` less `hhi_pre_merger` is at most 200."

        Design: Difficulty/boundary_precision_check/hhi_delta_exactly_at_safe_harbor_passes_the_screen
        """
        world = rosewood_market_world()

        analysis = run_competitive_analysis(world["application"]["id"], world["market"]["id"])

        assert analysis["required_divestiture_deposits_usd"] == 0
        assert analysis["designated_divestiture_deposits_usd"] == 0
        assert analysis["hhi_post_mitigated"] == 2950
        assert analysis["mitigation_satisfied"] is True

    def test_every_analysis_passing_outright_clears_the_application(self):
        """PRD §3.5: "Only when every analysis passed outright is the posture `CLEARED`."

        Design: Difficulty/boundary_precision_check/hhi_delta_exactly_at_safe_harbor_passes_the_screen
        """
        world = rosewood_market_world()
        run_competitive_analysis(world["application"]["id"], world["market"]["id"])

        application = read_application(world["application"]["id"], world["acquirer"]["id"])

        assert application["competitive_posture"] == "CLEARED"

    def test_a_five_participant_market_aggregates_before_the_screen_runs(self):
        """PRD §2.8: "A market's `hhi_current` is then computed by taking, for each institution
        present in the market, that institution's in-market includable deposits divided by the
        market's `total_deposits_usd`, multiplied by 100 and rounded half-up to four decimal places;
        squaring each of those share percentages; summing the squares; and rounding the sum half-up
        to a whole integer."

        Design: Difficulty/boundary_precision_check/hhi_delta_exactly_at_safe_harbor_passes_the_screen
        """
        world = rosewood_market_world()

        market = read_market(world["market"]["id"])

        assert market["total_deposits_usd"] == 1_000_000_000
        assert market["participant_count"] == 5
        assert market["hhi_current"] == 2750
