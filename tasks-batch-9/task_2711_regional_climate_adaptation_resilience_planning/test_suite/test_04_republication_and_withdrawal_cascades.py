"""The five-hop republication cascade and the four-hop withdrawal cascade."""

from test_helpers import (
    allocate,
    assert_all_null,
    assert_fields,
    assert_program_conservation,
    assert_project_dimensions,
    cast_endorsement,
    certify_analysis,
    create_analysis,
    create_asset,
    create_asset_link,
    create_assessed_assessment,
    create_completed_session,
    create_harbor,
    create_plan_cycle,
    create_published_profile,
    create_retrofit_project,
    create_ridge,
    open_endorsement_round,
    open_engagement,
    rank_asset,
    read_analysis,
    read_asset,
    read_assessment,
    read_capital_program,
    read_endorsement,
    read_hazard_profile,
    read_plan_cycle,
    read_project,
    revise_hazard_profile,
    screen_project,
    two_certified_retrofit_projects,
    withdraw_project,
)


class TestHazardRevisionCascade:
    """One republication invalidates an assessment, a ranking, a case and a round."""

    @staticmethod
    def _cycle_in_endorsement_round_over_a_certified_case():
        harbor = create_harbor()
        create_ridge()
        cycle = create_plan_cycle(
            quorum_weight_bps=6600, max_revision_rounds=1, required_session_count=1
        )
        profile = create_published_profile(harbor["id"], exposure_index=0.80)
        asset = create_asset(harbor["id"])
        assessment = create_assessed_assessment(
            profile["id"], asset["id"], method="ADDITIVE_WEIGHTED"
        )
        rank_asset(asset["id"])
        project = create_retrofit_project(cycle["id"], harbor["id"], name="Harbor Pump Retrofit")
        screen_project(project["id"])
        create_asset_link(
            project["id"], harbor["id"], asset["id"], 2118960,
            benefit_reaches_disadvantaged=True,
        )
        analysis = create_analysis(
            project["id"], harbor["id"], method="ANNUALIZED_EQUIVALENT", discount_rate_bps=700
        )
        certify_analysis(analysis["id"])
        create_completed_session(
            cycle["id"],
            harbor["id"],
            completion={
                "attendee_count": 120,
                "disadvantaged_attendee_count": 70,
                "preferred_strategy_type": "ACCOMMODATE",
            },
            modality="HYBRID",
            window_start="2026-09-10T17:00:00Z",
            window_end="2026-09-10T20:00:00Z",
        )
        open_engagement(cycle["id"])
        open_endorsement_round(cycle["id"])
        endorsement = cast_endorsement(cycle["id"], harbor["id"], decision="ENDORSED")
        return {
            "harbor": harbor,
            "cycle": cycle,
            "profile": profile,
            "asset": asset,
            "assessment": assessment,
            "project": project,
            "analysis": analysis,
            "endorsement": endorsement,
        }

    def test_republication_stales_the_assessment_and_strips_the_ranking(self):
        """Hops one to three: the profile advances, the assessment stales, the ranking is nulled.

        PRD 3.2 hop 2: "every vulnerability assessment against this profile that
        sits in `ASSESSED` and whose `assessed_profile_version` is now strictly less
        than the profile's `published_version` moves `ASSESSED → STALE`."  Its score
        survives: "Its `vulnerability_score` and `vulnerability_band` are
        **retained** as the stale reading".  Hop 3 discards instead: "its
        `consequence_score`, `criticality_tier` and `dependency_depth` are all set
        to null. Unlike hop 2, the ranking outputs are discarded rather than
        retained."

        Design: Difficulty/transitive_cascade/hazard_revision_cascades_to_plan_cycle_revision
        """
        context = self._cycle_in_endorsement_round_over_a_certified_case()

        revise_hazard_profile(
            context["profile"]["id"],
            exposure_index=0.90,
            annual_event_probability=0.03,
            projected_annual_loss_cents=300000000,
        )

        assert_fields(
            read_hazard_profile(context["profile"]["id"]),
            {"published_version": 2, "exposure_index": 0.90, "status": "PUBLISHED"},
            "the republished projection",
        )
        assert_fields(
            read_assessment(context["assessment"]["id"]),
            {"status": "STALE", "vulnerability_score": 0.82},
            "the staled assessment",
        )
        asset = read_asset(context["asset"]["id"])
        assert_fields(asset, {"criticality_status": "RECOMPUTE_REQUIRED"}, "the unranked asset")
        assert_all_null(
            asset,
            ["consequence_score", "criticality_tier", "dependency_depth"],
            "the asset whose ranking was discarded",
        )

    def test_republication_stales_the_certified_case_and_reverses_the_round(self):
        """Hops four and five: the case goes stale and the cycle drops back to REVISION.

        PRD 3.2 hop 4: "every benefit-cost analysis in `CERTIFIED` status whose
        project is linked to one of those assets moves `CERTIFIED → STALE` with
        `stale_reason` set to `ASSET_RECOMPUTE`, and the owning adaptation project's
        `analysis_status` moves `BCA_CERTIFIED → BCA_STALE`."  Hop 5: "every plan
        cycle that owns one of them and currently sits in `ENDORSEMENT_ROUND` is
        pushed back: it moves `ENDORSEMENT_ROUND → REVISION` with `revision_count`
        incremented by 1 and every live current-round endorsement marked
        `SUPERSEDED`".

        Design: Difficulty/transitive_cascade/hazard_revision_cascades_to_plan_cycle_revision
        """
        context = self._cycle_in_endorsement_round_over_a_certified_case()

        revise_hazard_profile(
            context["profile"]["id"],
            exposure_index=0.90,
            annual_event_probability=0.03,
            projected_annual_loss_cents=300000000,
        )

        assert_fields(
            read_analysis(context["analysis"]["id"]),
            {"status": "STALE", "stale_reason": "ASSET_RECOMPUTE"},
            "the staled benefit-cost case",
        )
        assert_project_dimensions(
            read_project(context["project"]["id"]),
            screening="SCREENED_IN",
            analysis="BCA_STALE",
            program="UNPROGRAMMED",
        )
        assert_fields(
            read_plan_cycle(context["cycle"]["id"]),
            {"status": "REVISION", "revision_count": 1, "round_number": 1},
            "the cycle pushed back by the cascade",
        )
        assert_fields(
            read_endorsement(context["endorsement"]["id"]),
            {"decision": "SUPERSEDED"},
            "the endorsement the cascade invalidated",
        )


class TestWithdrawalReleasesTheGrantHold:
    """Releasing one allocation reopens the posture and unblocks the sibling."""

    @staticmethod
    def _closed_program_holding_two_allocations():
        context = two_certified_retrofit_projects(
            authorized_cents=60000000, equity_target_bps=4000
        )
        program_id = context["program"]["id"]
        allocate(program_id, context["project_a"]["id"], 30000000)
        allocate(program_id, context["project_b"]["id"], 30000000)
        return context

    def test_withdrawal_releases_the_allocation_back_into_the_ledger(self):
        """Hops one and two: the project drops out and the money returns.

        PRD 3.7 hop 1: "The project's `program_status` moves to `WITHDRAWN` and its
        `allocated_cents` is reset to 0. `capital_program_id` is deliberately
        **retained** for audit."  Hop 2 then restores the ledger: "*Because* the project
        has left the committed set, the program's `committed_cents` decreases by exactly
        the released amount and `available_cents` increases by exactly the same amount, so
        `committed_cents` plus `available_cents` still equals `authorized_cents`."

        Design: Difficulty/transitive_cascade/project_withdraw_cascades_to_grant_hold_release
        """
        context = self._closed_program_holding_two_allocations()

        withdraw_project(context["project_a"]["id"], context["harbor"]["id"])

        assert_fields(
            read_project(context["project_a"]["id"]),
            {"program_status": "WITHDRAWN", "allocated_cents": 0},
            "the withdrawn project",
        )
        program = read_capital_program(context["program"]["id"])
        assert_fields(
            program,
            {
                "authorized_cents": 60000000,
                "committed_cents": 30000000,
                "available_cents": 30000000,
            },
            "the recomputed capital program ledger",
        )
        assert_program_conservation(program)

    def test_reopened_posture_clears_the_hold_on_the_sibling_only(self):
        """Hops three and four: the posture reopens and only siblings are released.

        PRD 3.7 hop 3: "*Because* `available_cents` has risen above zero,
        `funding_posture` is re-derived by the same ordered rule as above and therefore
        leaves `CLOSED`."  Hop 4 then names the released set exactly: "*Because* the
        posture has left `CLOSED`, `grant_hold_flag` is cleared to false on **every
        sibling project** of that program whose `program_status` is `PROGRAMMED`."  The
        withdrawn project is not in that set — its own `program_status` now reads
        `WITHDRAWN` — so nothing clears the flag it was already carrying.

        Design: Difficulty/transitive_cascade/project_withdraw_cascades_to_grant_hold_release
        """
        context = self._closed_program_holding_two_allocations()

        withdraw_project(context["project_a"]["id"], context["harbor"]["id"])

        assert_fields(
            read_capital_program(context["program"]["id"]),
            {"funding_posture": "OPEN", "equity_achieved_bps": 10000, "version": 4},
            "the reopened capital program",
        )
        assert_fields(
            read_project(context["project_b"]["id"]),
            {
                "program_status": "PROGRAMMED",
                "allocated_cents": 30000000,
                "grant_hold_flag": False,
            },
            "the released sibling project",
        )
        assert_fields(
            read_project(context["project_a"]["id"]),
            {"grant_hold_flag": True},
            "the withdrawn project, which keeps its own flag",
        )
