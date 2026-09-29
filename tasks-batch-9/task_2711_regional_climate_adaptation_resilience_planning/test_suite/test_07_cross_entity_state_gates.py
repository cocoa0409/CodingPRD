"""Gates whose blocking state lives on an entity the request never names."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    analysis_payload,
    api_client,
    assert_fields,
    complete_session,
    create_asset,
    create_asset_link,
    create_assessed_assessment,
    create_screened_project,
    create_session,
    create_completed_session,
    create_harbor,
    create_plan_cycle,
    make_project_sponsor_headers,
    open_engagement,
    rank_asset,
    read_asset,
    read_plan_cycle,
    read_project,
    read_session,
    screened_retrofit_context,
    validate_error,
    validate_success,
)


class TestAnalysisWaitsForEveryLinkedAsset:
    """One unranked asset two hops away blocks a case the project itself is ready for."""

    @staticmethod
    def _project_linked_to_a_ranked_and_an_unranked_asset():
        context = screened_retrofit_context(project_overrides={"name": "Harbor Pump Retrofit"})
        harbor_id = context["harbor"]["id"]
        second_asset = create_asset(
            harbor_id,
            name="Harbor Depot Backup Feeder",
            asset_class="POWER",
            replacement_value_cents=400000000,
            service_population=40000,
            redundancy_factor=0.10,
            is_shared=False,
        )
        create_assessed_assessment(
            context["profile"]["id"], second_asset["id"], method="COMPOSITE_MULTIPLICATIVE"
        )
        create_asset_link(
            context["project"]["id"], harbor_id, context["asset"]["id"], 2118960,
            benefit_reaches_disadvantaged=True,
        )
        create_asset_link(
            context["project"]["id"], harbor_id, second_asset["id"], 100000,
            benefit_reaches_disadvantaged=True,
        )
        context["second_asset"] = second_asset
        return context

    def test_the_unranked_second_asset_blocks_preparation(self):
        """Two links exist, so the refusal is about ranking rather than link count.

        PRD 3.6: "the project must have at least one linked asset, or
        `ERR_NO_LINKED_ASSETS`; and every lifeline asset reachable through the
        project's links must sit in `criticality_status` `RANKED`, or
        `ERR_ASSET_RANKING_REQUIRED`. That last rule is what forces a sponsor to wait
        for the science team to re-rank an asset after a republication before a new
        case can be built on it."  A newly added asset is not yet ranked, since PRD
        3.4 states that "A new asset always begins in `criticality_status` `UNRANKED`
        with `consequence_score`, `criticality_tier` and `dependency_depth` all null."

        Design: Difficulty/cross_entity_state_dependency/analysis_blocked_until_every_linked_asset_is_ranked
        """
        context = self._project_linked_to_a_ranked_and_an_unranked_asset()

        response = api_client.create_analysis(
            context["project"]["id"],
            analysis_payload(method="ANNUALIZED_EQUIVALENT", discount_rate_bps=700),
            make_project_sponsor_headers(context["harbor"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_ASSET_RANKING_REQUIRED.value, 409)
        assert_fields(
            read_project(context["project"]["id"]),
            {"screening_status": "SCREENED_IN", "analysis_status": "NOT_ANALYZED"},
            "the ready project held up by a third entity",
        )

    def test_ranking_the_third_entity_unblocks_the_identical_request(self):
        """Ranking the second asset alone lets the rejected payload through.

        PRD 3.4: "`consequence_score` is then the value term multiplied by the peak
        vulnerability term, multiplied by the cascade factor, multiplied by the
        sharing factor, multiplied by one plus the population weight — rounded half
        up, once, at the very end, to 2 fractional digits."  For the private feeder
        that is 3.6 times 0.30 times 1.16, which is 1.25, and PRD 3.4 reads the tier
        off it: "`TIER_1` when it is at least 25.00, `TIER_2` when it is at least
        8.00, and `TIER_3` otherwise."  The benefit then sums both links, so the
        ratio is 2218960 over 2118960.

        Design: Difficulty/cross_entity_state_dependency/analysis_blocked_until_every_linked_asset_is_ranked
        """
        context = self._project_linked_to_a_ranked_and_an_unranked_asset()

        rank_asset(context["second_asset"]["id"])

        assert_fields(
            read_asset(context["second_asset"]["id"]),
            {
                "criticality_status": "RANKED",
                "consequence_score": 1.25,
                "criticality_tier": "TIER_3",
                "dependency_depth": 0,
            },
            "the newly ranked feeder",
        )
        assert_fields(
            read_asset(context["asset"]["id"]),
            {"consequence_score": 14.17, "criticality_tier": "TIER_2"},
            "the treatment plant the second ranking must not touch",
        )

        response = api_client.create_analysis(
            context["project"]["id"],
            analysis_payload(method="ANNUALIZED_EQUIVALENT", discount_rate_bps=700),
            make_project_sponsor_headers(context["harbor"]["id"]),
        )

        analysis = validate_success(response, 201)
        assert_fields(
            analysis,
            {
                "benefit_measure_cents": 2218960,
                "cost_measure_cents": 2118960,
                "bcr": 1.0472,
                "grant_eligible": True,
            },
            "the case that both links now support",
        )
        assert_fields(
            read_project(context["project"]["id"]),
            {"analysis_status": "BCA_PENDING"},
            "the project once the case exists",
        )


class TestEndorsementRoundWaitsForTheSessionCount:
    """A count over sibling sessions, not one row's state, gates the transition."""

    @staticmethod
    def _cycle_in_engagement_with_one_of_two_sessions_completed():
        harbor = create_harbor()
        cycle = create_plan_cycle(quorum_weight_bps=6600, max_revision_rounds=1, required_session_count=2)
        create_screened_project(cycle["id"], harbor["id"], name="Harbor Levee Raise")
        first = create_completed_session(
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
        second = create_session(
            cycle["id"],
            harbor["id"],
            modality="VIRTUAL",
            window_start="2026-09-12T00:00:00Z",
            window_end="2026-09-12T02:00:00Z",
        )
        open_engagement(cycle["id"])
        return {"harbor": harbor, "cycle": cycle, "first": first, "second": second}

    def test_one_completed_session_against_a_requirement_of_two_blocks_the_round(self):
        """The scheduled sibling does not count toward `required_session_count`.

        PRD 3.8: "the cycle must have at least `required_session_count` engagement
        sessions in `COMPLETED` status, or `ERR_ENGAGEMENT_INCOMPLETE` — sessions
        still `SCHEDULED` and sessions `CANCELLED` never count".  Because the cycle
        already owns a screened project, PRD 3.8's third check — "the cycle must own
        at least one adaptation project whose `screening_status` is `SCREENED_IN`, or
        `ERR_NO_SCREENED_PROJECTS`" — cannot be the reason for the refusal.

        Design: Difficulty/cross_entity_state_dependency/endorsement_round_blocked_until_required_sessions_complete
        """
        context = self._cycle_in_engagement_with_one_of_two_sessions_completed()

        response = api_client.open_endorsement_round(context["cycle"]["id"], ADMIN())

        validate_error(response, ApiErrorId.ERR_ENGAGEMENT_INCOMPLETE.value, 409)
        assert_fields(
            read_plan_cycle(context["cycle"]["id"]),
            {"status": "ENGAGEMENT", "round_number": 0},
            "the cycle still short of its engagement quota",
        )
        assert_fields(
            read_session(context["second"]["id"]),
            {"status": "SCHEDULED"},
            "the session that has not yet been held",
        )

    def test_completing_the_second_session_unblocks_the_round(self):
        """A delegate act on another entity is what admits the administrative one.

        PRD 3.8: "On success the session moves `SCHEDULED → COMPLETED` and
        `equity_reach_bps` is written as ten thousand multiplied by
        `disadvantaged_attendee_count` divided by `attendee_count`, **floored** to
        whole basis points".  Ten of eighty attendees is 1250 basis points, and PRD
        3.8 then admits the transition: "On success `round_number` increments by 1 and
        the cycle's `version` increments by 1."

        Design: Difficulty/cross_entity_state_dependency/endorsement_round_blocked_until_required_sessions_complete
        """
        context = self._cycle_in_engagement_with_one_of_two_sessions_completed()

        complete_session(
            context["second"]["id"],
            context["harbor"]["id"],
            attendee_count=80,
            disadvantaged_attendee_count=10,
            preferred_strategy_type="PROTECT",
        )

        assert_fields(
            read_session(context["second"]["id"]),
            {"status": "COMPLETED", "equity_reach_bps": 1250},
            "the freshly completed session",
        )
        assert_fields(
            read_session(context["first"]["id"]),
            {"equity_reach_bps": 5833},
            "the earlier session, whose reach must not move",
        )

        response = api_client.open_endorsement_round(context["cycle"]["id"], ADMIN())

        validate_success(response, 200)
        assert_fields(
            read_plan_cycle(context["cycle"]["id"]),
            {"status": "ENDORSEMENT_ROUND", "round_number": 1, "revision_count": 0},
            "the cycle the second completion unblocked",
        )
