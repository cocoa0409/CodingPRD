"""The cycle that re-enters a state it has left, and the project with four dimensions."""

from test_helpers import (
    allocate,
    assert_fields,
    assert_project_dimensions,
    award_grant,
    cast_endorsement,
    certify_analysis,
    close_endorsement_round,
    create_analysis,
    create_asset,
    create_asset_link,
    create_assessed_assessment,
    create_capital_program,
    create_completed_session,
    create_harbor,
    create_plan_cycle,
    create_published_profile,
    create_retrofit_project,
    create_ridge,
    create_screened_project,
    open_endorsement_round,
    open_engagement,
    rank_asset,
    read_endorsement,
    read_plan_cycle,
    read_project,
    read_session,
    report_indicator,
    screen_project,
    submit_grant,
)


class TestEndorsementRevisionLoop:
    """ENDORSEMENT_ROUND to REVISION and back again, resolving differently each visit."""

    @staticmethod
    def _cycle_in_first_round():
        harbor = create_harbor()
        ridge = create_ridge()
        cycle = create_plan_cycle(
            quorum_weight_bps=6600, max_revision_rounds=1, required_session_count=1
        )
        create_screened_project(
            cycle["id"],
            harbor["id"],
            name="Harbor Levee Raise",
            strategy_type="PROTECT",
            base_cost_cents=42000000,
            service_life_years=30,
            cobenefit_points=12,
            feasibility_score=0.70,
        )
        session = create_completed_session(
            cycle["id"],
            harbor["id"],
            completion={
                "attendee_count": 120,
                "disadvantaged_attendee_count": 70,
                "preferred_strategy_type": "PROTECT",
            },
            modality="IN_PERSON",
            window_start="2026-09-10T17:00:00Z",
            window_end="2026-09-10T20:00:00Z",
        )
        open_engagement(cycle["id"])
        open_endorsement_round(cycle["id"])
        return harbor, ridge, cycle, session

    def test_short_round_returns_the_cycle_to_revision_and_supersedes_its_votes(self):
        """Four of seven weight is 5714 bps, short of 6600, so the cycle goes back to REVISION.

        PRD 3.8: "If `revision_count` plus one is still within
        `max_revision_rounds`, the cycle moves `ENDORSEMENT_ROUND → REVISION`,
        `revision_count` increments by 1, every endorsement of the just-closed round
        carrying `ENDORSED`, `CONDITIONED` or `VETOED` has its `decision` rewritten
        to `SUPERSEDED`, and the cycle's `version` increments by 1."

        Design: Difficulty/non_linear_state_machine/plan_cycle_endorsement_revision_cycle_returns_to_endorsement_round
        """
        harbor, _, cycle, _ = self._cycle_in_first_round()

        first_vote = cast_endorsement(cycle["id"], harbor["id"], decision="ENDORSED")
        assert_fields(
            first_vote,
            {"round_number": 1, "weight_at_cast": 4},
            "the weight-4 member's first-round endorsement",
        )

        closed = close_endorsement_round(cycle["id"])

        assert_fields(
            closed,
            {"status": "REVISION", "achieved_weight_bps": 5714, "revision_count": 1},
            "the cycle after a short round",
        )
        assert_fields(
            read_endorsement(first_vote["id"]),
            {"decision": "SUPERSEDED"},
            "the just-closed round's endorsement",
        )

    def test_the_second_visit_to_the_endorsement_round_adopts(self):
        """Re-opening the round lifts round_number to 2 and the full weight adopts the plan.

        PRD 3.8: "**Opening an endorsement round** is an administrative act, and it is
        entered from two different states: `ENGAGEMENT → ENDORSEMENT_ROUND` the
        first time, and `REVISION → ENDORSEMENT_ROUND` on every subsequent lap of
        the loop."  Adoption is inclusive on the quorum: "Otherwise, if
        `achieved_weight_bps` is at least the cycle's `quorum_weight_bps`, the
        outcome is **adopted**."

        Design: Difficulty/non_linear_state_machine/plan_cycle_endorsement_revision_cycle_returns_to_endorsement_round
        """
        harbor, ridge, cycle, session = self._cycle_in_first_round()

        cast_endorsement(cycle["id"], harbor["id"], decision="ENDORSED")
        close_endorsement_round(cycle["id"])
        reopened = open_endorsement_round(cycle["id"])
        assert_fields(reopened, {"status": "ENDORSEMENT_ROUND", "round_number": 2}, "the reopened cycle")

        second_harbor_vote = cast_endorsement(cycle["id"], harbor["id"], decision="ENDORSED")
        ridge_vote = cast_endorsement(cycle["id"], ridge["id"], decision="ENDORSED")
        for vote, label in (
            (second_harbor_vote, "the weight-4 member's second-round endorsement"),
            (ridge_vote, "the weight-3 member's second-round endorsement"),
        ):
            assert_fields(vote, {"round_number": 2}, label)

        adopted = close_endorsement_round(cycle["id"])

        assert_fields(
            adopted,
            {
                "status": "ADOPTED",
                "achieved_weight_bps": 10000,
                "round_number": 2,
                "revision_count": 1,
            },
            "the cycle after the second round",
        )
        assert adopted["adopted_at"] is not None, (
            "adoption must stamp adopted_at with the logical clock instant"
        )
        assert_fields(read_plan_cycle(cycle["id"]), {"status": "ADOPTED"}, "the stored cycle")
        assert_fields(
            read_session(session["id"]),
            {"status": "COMPLETED", "equity_reach_bps": 5833},
            "the completed engagement session",
        )


class TestProjectDimensionsAdvanceIndependently:
    """One project row carrying four different dimension values at once."""

    @staticmethod
    def _fundable_retrofit():
        harbor = create_harbor()
        cycle = create_plan_cycle(
            quorum_weight_bps=6600, max_revision_rounds=1, required_session_count=1
        )
        profile = create_published_profile(harbor["id"], exposure_index=0.80)
        asset = create_asset(harbor["id"])
        create_assessed_assessment(profile["id"], asset["id"], method="ADDITIVE_WEIGHTED")
        rank_asset(asset["id"])
        project = create_retrofit_project(
            cycle["id"],
            harbor["id"],
            name="Harbor Pump Retrofit",
            indicator_code="FLOOD_DEPTH_REDUCTION",
            indicator_target_value=40.00,
        )
        screened = screen_project(project["id"])
        create_asset_link(
            project["id"], harbor["id"], asset["id"], 2118960,
            benefit_reaches_disadvantaged=True,
        )
        analysis = create_analysis(
            project["id"], harbor["id"], method="ANNUALIZED_EQUIVALENT", discount_rate_bps=700
        )
        certified = certify_analysis(analysis["id"])
        program = create_capital_program(
            fiscal_year=2027, authorized_cents=60000000, equity_target_bps=4000
        )
        return harbor, screened, certified, program

    def test_four_dimensions_hold_four_different_values_at_once(self):
        """Screening, certification, award and reporting each move a different dimension.

        PRD 3.5: "A project is the only entity in the system that carries **four
        independent state dimensions on one row**, and they are never collapsed into
        a single status field."  The specification is explicit that they can differ:
        "a single project can legitimately read `SCREENED_IN`, `BCA_STALE`,
        `AWARDED` and `AT_RISK` all at once."

        Design: Difficulty/non_linear_state_machine/project_dimensions_advance_independently
        """
        harbor, project, _, program = self._fundable_retrofit()

        allocate(program["id"], project["id"], 30000000, expected_version=program["version"])
        submit_grant(project["id"], harbor["id"], grant_funder="BRIC")
        award_grant(project["id"])
        report_indicator(project["id"], harbor["id"], 36.00, period_label="2027-Q1")

        assert_project_dimensions(
            read_project(project["id"]),
            screening="SCREENED_IN",
            analysis="BCA_CERTIFIED",
            program="AWARDED",
            implementation="ON_TRACK",
        )

    def test_each_dimension_advance_writes_its_own_derived_fields(self):
        """The cost stack, ratio, equity share, priority and attainment all land together.

        PRD 3.7: "`priority_score` is the ratio component weighted at 0.45, plus the
        criticality component weighted at 0.30, plus the equity component weighted
        at 0.25; the ratio and equity components are carried into that sum unrounded,
        and only the final sum is rounded half up to 4 fractional digits."  And on
        reporting: "`indicator_attainment_pct` as one hundred multiplied by
        `reported_value` divided by `indicator_target_value`, rounded half up to 2
        fractional digits."

        Design: Difficulty/non_linear_state_machine/project_dimensions_advance_independently
        """
        harbor, project, analysis, program = self._fundable_retrofit()

        assert_fields(project, {"total_program_cost_cents": 35316000}, "screened project")
        assert_fields(
            analysis, {"bcr": 1.0000, "grant_eligible": True}, "certified analysis"
        )

        allocate(program["id"], project["id"], 30000000, expected_version=program["version"])
        submit_grant(project["id"], harbor["id"], grant_funder="BRIC")
        award_grant(project["id"])
        report_indicator(project["id"], harbor["id"], 36.00, period_label="2027-Q1")

        final = read_project(project["id"])
        assert_fields(
            final,
            {
                "equity_benefit_share_bps": 10000,
                "priority_score": 0.5800,
                "indicator_attainment_pct": 90.00,
                "reported_period_count": 1,
                "grant_hold_flag": False,
            },
            "the fully advanced project",
        )
