"""Lifecycle edges: entry states, self-loops, terminal lockdowns and cascades."""

from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    api_client,
    assert_all_null,
    assert_fields,
    cast_endorsement,
    create_asset,
    create_assessed_assessment,
    create_assessment,
    create_completed_session,
    create_harbor,
    create_hazard_profile,
    create_plan_cycle,
    create_published_profile,
    create_ridge,
    create_screened_project,
    create_session,
    make_jurisdiction_delegate_headers,
    open_endorsement_round,
    open_engagement,
    read_asset,
    read_assessment,
    read_hazard_profile,
    read_plan_cycle,
    read_project,
    read_session,
    revise_hazard_profile,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPlanCycleEntryStates:
    """The cycle is created in DRAFT and only open-engagement may move it first."""

    def test_a_new_cycle_reads_draft_and_open_engagement_leaves_the_round_at_zero(self):
        """Opening engagement advances the state but not the round counter.

        PRD 3.8: "A new cycle reads `status` `DRAFT`, `round_number` 0,
        `revision_count` 0, `achieved_weight_bps` null and `adopted_at` null."  The
        move itself is described as "Opening engagement is a single administrative step
        that moves the cycle `DRAFT → ENGAGEMENT`; a cycle in any other state yields
        `ERR_PLAN_CYCLE_STATE_INVALID`. The cycle's `updated_at` is refreshed and its
        `version` increments by 1."  Only the endorsement round touches the counter,
        since PRD 3.8 says of opening one that "On success `round_number` increments by
        1 and the cycle's `version` increments by 1."

        Design: Corner/state_machines/plan_cycle_starts_in_draft_and_opens_engagement
        """
        created = create_plan_cycle(required_session_count=1)

        assert_fields(
            created,
            {"status": "DRAFT", "round_number": 0, "revision_count": 0, "version": 1},
            "the freshly opened planning cycle",
        )
        assert_all_null(created, ["achieved_weight_bps", "adopted_at"], "the freshly opened cycle")

        moved = validate_success(api_client.open_engagement(created["id"], ADMIN()), 200)

        assert_fields(
            moved,
            {
                "status": "ENGAGEMENT",
                "round_number": 0,
                "revision_count": 0,
                "version": 2,
            },
            "the cycle now gathering community input",
        )

    def test_neither_endorsement_round_verb_may_act_on_a_draft_cycle(self):
        """The state gate answers before the engagement-completeness gate.

        PRD 3.8 orders the checks on opening a round: "Three checks apply, in this
        order: the cycle must be in `ENGAGEMENT` or `REVISION`, or
        `ERR_PLAN_CYCLE_STATE_INVALID`; the cycle must have at least
        `required_session_count` engagement sessions in `COMPLETED` status, or
        `ERR_ENGAGEMENT_INCOMPLETE` — sessions still `SCHEDULED` and sessions
        `CANCELLED` never count; and the cycle must own at least one adaptation project
        whose `screening_status` is `SCREENED_IN`, or `ERR_NO_SCREENED_PROJECTS`."
        Closing is gated the same way, since PRD 3.8 says "The cycle must be in
        `ENDORSEMENT_ROUND`, or `ERR_PLAN_CYCLE_STATE_INVALID`."

        Design: Corner/state_machines/open_endorsement_round_from_draft_rejected
        """
        cycle = create_plan_cycle(required_session_count=1)

        opening = api_client.open_endorsement_round(cycle["id"], ADMIN())
        closing = api_client.close_endorsement_round(cycle["id"], ADMIN())

        validate_error(opening, ApiErrorId.ERR_PLAN_CYCLE_STATE_INVALID.value, 409)
        validate_error(closing, ApiErrorId.ERR_PLAN_CYCLE_STATE_INVALID.value, 409)
        assert_fields(
            read_plan_cycle(cycle["id"]),
            {"status": "DRAFT", "round_number": 0, "version": 1},
            "the cycle neither refused verb may touch",
        )


class TestHazardProfilePublication:
    """Publication supersedes on the full four-part key and never runs twice."""

    def test_only_the_profile_sharing_all_four_key_parts_is_superseded(self):
        """A sibling profile at a different horizon year stays PUBLISHED.

        PRD 3.2: "Publication also supersedes: if another profile already sits in
        `PUBLISHED` for the very same combination of `jurisdiction_id`, `hazard_type`,
        `scenario` and `horizon_year`, that older profile's `status` moves to
        `SUPERSEDED`. Both rows have their `version` incremented."  The same paragraph
        fixes the counters: "On success the server sets `published_version` to 1 and
        stamps `published_at` with the logical clock instant."

        Design: Corner/state_machines/hazard_profile_publish_supersedes_the_prior_published_profile
        """
        harbor = create_harbor()
        first_2060 = create_published_profile(harbor["id"], horizon_year=2060)
        other_horizon = create_published_profile(
            harbor["id"],
            horizon_year=2080,
            exposure_index=0.90,
            annual_event_probability=0.03,
            projected_annual_loss_cents=400000000,
        )
        second_2060 = create_hazard_profile(
            harbor["id"],
            horizon_year=2060,
            exposure_index=0.85,
            projected_annual_loss_cents=300000000,
        )

        published = validate_success(
            api_client.publish_hazard_profile(second_2060["id"], ANALYST()), 200
        )

        assert_fields(
            published,
            {"status": "PUBLISHED", "published_version": 1},
            "the newest projection for the 2060 horizon",
        )
        assert published["published_at"] is not None, (
            "publication stamps published_at from the logical clock, but it read null"
        )
        assert_fields(
            read_hazard_profile(first_2060["id"]),
            {"status": "SUPERSEDED"},
            "the older projection for the same four-part key",
        )
        assert_fields(
            read_hazard_profile(other_horizon["id"]),
            {"status": "PUBLISHED"},
            "the projection whose horizon year differs",
        )
        _rows, meta = validate_paginated(
            api_client.list_hazard_profiles(ANALYST(), params={"status": "SUPERSEDED"})
        )
        assert meta["total_count"] == 1, (
            f"exactly one projection should have been superseded, found {meta['total_count']}"
        )

    def test_publishing_the_same_row_again_is_refused_and_does_not_advance_the_counter(self):
        """Only a revision may lift `published_version` past 1.

        PRD 3.2: "Publication is a separate, deliberate act by a `HazardAnalyst`, and
        it moves the profile `DRAFT → PUBLISHED`. Publishing a profile that is not in
        `DRAFT` is rejected with `ERR_HAZARD_PROFILE_ALREADY_PUBLISHED`."  Advancing
        the counter is reserved to republication, which PRD 3.2 describes as: "The
        three projection fields are overwritten from the request, `published_version`
        increments by 1, and `published_at` is refreshed to the current logical clock
        instant."

        Design: Corner/state_machines/hazard_profile_publish_twice_rejected
        """
        harbor = create_harbor()
        profile = create_published_profile(harbor["id"])

        response = api_client.publish_hazard_profile(profile["id"], ANALYST())

        validate_error(response, ApiErrorId.ERR_HAZARD_PROFILE_ALREADY_PUBLISHED.value, 409)
        assert_fields(
            read_hazard_profile(profile["id"]),
            {"status": "PUBLISHED", "published_version": 1, "version": 2},
            "the projection the second publish could not touch",
        )


class TestAssessmentPreconditionsAndRefresh:
    """The publication gate reads the parent, and a refresh replaces the reading."""

    def test_assessing_against_an_unpublished_projection_is_refused(self):
        """A DRAFT assessment against a DRAFT projection fails on the projection.

        PRD 3.3: "Two conditions guard it, and they are evaluated in this order:
        **first** the referenced hazard profile must currently be in `PUBLISHED` status,
        and a profile still in `DRAFT` or already `SUPERSEDED` yields
        `ERR_HAZARD_PROFILE_NOT_PUBLISHED`; **then** the assessment itself must be in
        either `DRAFT` or `STALE`, and an assessment already sitting in `ASSESSED`
        yields `ERR_ASSESSMENT_NOT_PENDING`."  PRD 3.3 also fixes what an unassessed row
        looks like: "A newly opened assessment sits in `status` `DRAFT` with
        `vulnerability_score`, `vulnerability_band`, `assessed_at` and
        `assessed_profile_version` all null."

        Design: Corner/state_machines/assessment_assess_against_a_draft_profile_rejected
        """
        harbor = create_harbor()
        profile = create_hazard_profile(harbor["id"])
        asset = create_asset(harbor["id"])
        assessment = create_assessment(profile["id"], asset["id"])

        response = api_client.assess(assessment["id"], ANALYST())

        validate_error(response, ApiErrorId.ERR_HAZARD_PROFILE_NOT_PUBLISHED.value, 409)
        stored = read_assessment(assessment["id"])
        assert_fields(stored, {"status": "DRAFT"}, "the assessment left unassessed")
        assert_all_null(
            stored,
            ["vulnerability_score", "assessed_profile_version"],
            "the assessment left unassessed",
        )

    def test_reassessing_a_stale_row_rewrites_the_score_against_the_new_projection(self):
        """Exposure 0.80 gives 0.82 EXTREME; after a revision to 0.50 it reads 0.67 HIGH.

        PRD 3.3: "Under `ADDITIVE_WEIGHTED`, the raw figure is the exposure term
        weighted at 0.40, plus the sensitivity term weighted at 0.35, plus the adaptive
        gap weighted at 0.25."  The overlay multiplier for the owning member's `HIGH`
        tier is 1.25, per PRD 3.3: "The **social vulnerability multiplier** is looked up
        from the `svi_tier` of the jurisdiction that owns the linked lifeline asset, and
        takes the value 1.00 for `LOW`, 1.10 for `MODERATE`, 1.25 for `HIGH` and 1.40
        for `SEVERE`".  So 0.40*0.80 + 0.35*0.60 + 0.25*0.50 = 0.655, times 1.25 is
        0.81875, rounding to 0.82; at exposure 0.50 the raw figure is 0.535, times 1.25
        is 0.66875, rounding to 0.67.  The stale reading is retained until the refresh,
        because PRD 3.2 says of hop 2 that "Its `vulnerability_score` and
        `vulnerability_band` are **retained** as the stale reading, so a reader can
        still see what the old number was", and PRD 3.3 fixes the refreshed counter:
        "`assessed_profile_version` is set to the profile's current `published_version`".

        Design: Corner/state_machines/assessment_reassess_from_stale_recomputes_against_the_new_projection
        """
        harbor = create_harbor()
        profile = create_published_profile(harbor["id"])
        asset = create_asset(harbor["id"])
        assessment = create_assessed_assessment(profile["id"], asset["id"])
        assert_fields(
            assessment,
            {
                "status": "ASSESSED",
                "vulnerability_score": 0.82,
                "vulnerability_band": "EXTREME",
                "assessed_profile_version": 1,
            },
            "the first reading taken against exposure 0.80",
        )
        revise_hazard_profile(
            profile["id"],
            exposure_index=0.50,
            annual_event_probability=0.02,
            projected_annual_loss_cents=180000000,
        )
        assert_fields(
            read_assessment(assessment["id"]),
            {
                "status": "STALE",
                "vulnerability_score": 0.82,
                "vulnerability_band": "EXTREME",
            },
            "the stale reading held over from the earlier model run",
        )

        refreshed = validate_success(api_client.assess(assessment["id"], ANALYST()), 200)

        assert_fields(
            refreshed,
            {
                "status": "ASSESSED",
                "vulnerability_score": 0.67,
                "vulnerability_band": "HIGH",
                "assessed_profile_version": 2,
            },
            "the reading recomputed against the re-run projection",
        )
        assert_fields(
            read_hazard_profile(profile["id"]),
            {"published_version": 2},
            "the republished projection",
        )


class TestAssetRankingGates:
    """Ranking needs an assessed reading, runs once, and freezes the dependency edge."""

    def test_ranking_ignores_an_assessment_that_was_never_assessed(self):
        """A DRAFT reading is not in the input set at all.

        PRD 3.4: "**then** the asset must have at least one vulnerability assessment in
        `ASSESSED` status, yielding `ERR_NO_ASSESSED_VULNERABILITY` if it does not. That
        last check is stricter than it looks: rows sitting in `DRAFT` or `STALE` are
        excluded from the input set entirely".  PRD 3.4 also fixes what an unranked asset
        reads: "A new asset always begins in `criticality_status` `UNRANKED` with
        `consequence_score`, `criticality_tier` and `dependency_depth` all null."

        Design: Corner/state_machines/asset_ranking_without_an_assessed_vulnerability_rejected
        """
        harbor = create_harbor()
        profile = create_published_profile(harbor["id"])
        asset = create_asset(harbor["id"])
        create_assessment(profile["id"], asset["id"])

        response = api_client.rank_asset(asset["id"], ANALYST())

        validate_error(response, ApiErrorId.ERR_NO_ASSESSED_VULNERABILITY.value, 409)
        stored = read_asset(asset["id"])
        assert_fields(
            stored,
            {"criticality_status": "UNRANKED", "version": 1},
            "the asset whose only reading is still a draft",
        )
        assert_all_null(
            stored,
            ["consequence_score", "criticality_tier", "dependency_depth"],
            "the asset whose only reading is still a draft",
        )

    def test_a_second_ranking_is_refused_and_the_consequence_score_stands(self):
        """Only a RECOMPUTE_REQUIRED asset may be ranked again.

        PRD 3.4: "Three conditions guard it, evaluated in this order: **first** the
        asset must be in `UNRANKED` or `RECOMPUTE_REQUIRED`, and an asset already
        `RANKED` yields `ERR_ASSET_ALREADY_RANKED`".  The figure the refusal protects
        follows from PRD 3.4: "`consequence_score` is then the value term multiplied by
        the peak vulnerability term, multiplied by the cascade factor, multiplied by the
        sharing factor, multiplied by one plus the population weight — rounded half up,
        once, at the very end, to 2 fractional digits."  Nine million-dollar units times
        0.82, times 1.00 at depth 0, times 1.20 for a shared asset, times 1.6 for a
        population weight of 0.6, is 14.1696 and rounds to 14.17, which PRD 3.4 bands as
        "`TIER_2` when it is at least 8.00".

        Design: Corner/state_machines/asset_ranking_twice_rejected
        """
        harbor = create_harbor()
        profile = create_published_profile(harbor["id"])
        asset = create_asset(harbor["id"])
        create_assessed_assessment(profile["id"], asset["id"])
        ranked = validate_success(api_client.rank_asset(asset["id"], ANALYST()), 200)
        assert_fields(
            ranked,
            {
                "criticality_status": "RANKED",
                "consequence_score": 14.17,
                "criticality_tier": "TIER_2",
                "dependency_depth": 0,
            },
            "the asset on its first ranking",
        )

        response = api_client.rank_asset(asset["id"], ANALYST())

        validate_error(response, ApiErrorId.ERR_ASSET_ALREADY_RANKED.value, 409)
        assert_fields(
            read_asset(asset["id"]),
            {"consequence_score": 14.17, "version": ranked["version"]},
            "the asset the second ranking could not touch",
        )

    def test_the_dependency_edge_freezes_on_ranking_but_not_on_a_sibling(self):
        """The refused PATCH is the ranked asset's; the unranked sibling still amends.

        PRD 3.4: "A `RegionalAdministrator` may amend an existing asset's `is_shared`
        flag and its `upstream_asset_id`, but only while the asset sits in `UNRANKED` or
        `RECOMPUTE_REQUIRED` — amending an asset that is currently `RANKED` is rejected
        with `ERR_ASSET_ALREADY_RANKED`, because rewriting a dependency edge under a live
        ranking would invalidate it. A successful amendment increments the asset's
        `version` by 1."

        Design: Corner/state_machines/asset_dependency_edge_cannot_be_patched_once_ranked
        """
        harbor = create_harbor()
        profile = create_published_profile(harbor["id"])
        ranked_asset = create_asset(harbor["id"])
        sibling = create_asset(
            harbor["id"],
            name="Harbor Substation",
            asset_class="POWER",
            replacement_value_cents=400000000,
            service_population=40000,
            redundancy_factor=0.10,
            is_shared=None,
        )
        create_assessed_assessment(profile["id"], ranked_asset["id"])
        validate_success(api_client.rank_asset(ranked_asset["id"], ANALYST()), 200)

        refused = api_client.patch_asset(
            ranked_asset["id"], {"upstream_asset_id": sibling["id"]}, ADMIN()
        )
        accepted = api_client.patch_asset(sibling["id"], {"is_shared": True}, ADMIN())

        validate_error(refused, ApiErrorId.ERR_ASSET_ALREADY_RANKED.value, 409)
        assert_fields(
            read_asset(ranked_asset["id"]),
            {"upstream_asset_id": None, "dependency_depth": 0},
            "the ranked asset whose edge is frozen",
        )
        amended = validate_success(accepted, 200)
        assert_fields(
            amended,
            {"is_shared": True, "version": 2},
            "the unranked sibling that may still be amended",
        )


class TestScreeningRunsExactlyOnce:
    """The cost stack is pinned by the first screen and never recomputed."""

    def test_a_second_screen_is_refused_and_the_priced_figures_stand(self):
        """The refusal leaves `screen_score` and the cost stack exactly as pinned.

        PRD 3.5: "Screening a project whose `screening_status` is anything other than
        `PROPOSED` is rejected with `ERR_PROJECT_ALREADY_SCREENED`."  The figures the
        refusal protects come from PRD 3.5's pinned stack: "A `PROTECT` project escalates
        by 1200 basis points", so 42000000 becomes 47040000; "An escalated cost from zero
        up to but not including five hundred thousand dollars attracts 900 basis points",
        giving an administration fee of 4233600 and a total of 51273600; "A total from
        zero up to but not including one million dollars requires a 2500 basis-point
        local match".  The score follows from "`screen_score` is then the cost component
        weighted at 0.40, plus the co-benefit component weighted at 0.25, plus the
        feasibility component weighted at 0.35", which is 0.2974528 + 0.15 + 0.245 =
        0.6924528, rounding to 0.6925, and PRD 3.5 rules that "A score of at least 0.4500
        moves the project `PROPOSED → SCREENED_IN`".

        Design: Corner/state_machines/project_screen_twice_rejected
        """
        harbor = create_harbor()
        cycle = create_plan_cycle(required_session_count=1)
        project = create_screened_project(cycle["id"], harbor["id"])
        assert_fields(
            project,
            {
                "screening_status": "SCREENED_IN",
                "screen_score": 0.6925,
                "escalated_cost_cents": 47040000,
                "admin_rate_bps": 900,
                "admin_fee_cents": 4233600,
                "total_program_cost_cents": 51273600,
                "grant_match_share_bps": 2500,
            },
            "the project as the first screen priced it",
        )

        response = api_client.screen_project(project["id"], ADMIN())

        validate_error(response, ApiErrorId.ERR_PROJECT_ALREADY_SCREENED.value, 409)
        assert_fields(
            read_project(project["id"]),
            {"screen_score": 0.6925, "total_program_cost_cents": 51273600},
            "the project the second screen could not reprice",
        )


class TestCycleTerminalOutcomes:
    """ADOPTED locks every verb out, and FAILED fans out to two child entities."""

    def test_an_adopted_cycle_refuses_all_three_lifecycle_verbs(self):
        """After adoption the cycle answers ERR_PLAN_CYCLE_STATE_INVALID to everything.

        PRD 3.8: "An adopted outcome moves the cycle `ENDORSEMENT_ROUND → ADOPTED`,
        writes `achieved_weight_bps`, stamps `adopted_at` with the logical clock instant,
        and increments `version` by 1. `ADOPTED` is terminal."  Both endorsement verbs
        and the engagement verb are state-gated, since PRD 3.8 says of opening a round
        "the cycle must be in `ENGAGEMENT` or `REVISION`, or
        `ERR_PLAN_CYCLE_STATE_INVALID`", of closing one "The cycle must be in
        `ENDORSEMENT_ROUND`, or `ERR_PLAN_CYCLE_STATE_INVALID`", and of opening
        engagement that it "moves the cycle `DRAFT → ENGAGEMENT`; a cycle in any other
        state yields `ERR_PLAN_CYCLE_STATE_INVALID`".  Two full weights out of a
        seven-weight active denominator is 10000 basis points, and PRD 3.8 adopts because
        "if `achieved_weight_bps` is at least the cycle's `quorum_weight_bps`, the
        outcome is **adopted**".

        Design: Corner/state_machines/plan_cycle_adopted_is_a_terminal_state_lockdown
        """
        harbor = create_harbor()
        ridge = create_ridge()
        cycle = create_plan_cycle(
            quorum_weight_bps=6600, max_revision_rounds=1, required_session_count=1
        )
        create_screened_project(cycle["id"], harbor["id"])
        create_completed_session(
            cycle["id"], harbor["id"], window_end="2026-09-10T19:00:00Z"
        )
        open_engagement(cycle["id"])
        open_endorsement_round(cycle["id"])
        cast_endorsement(cycle["id"], harbor["id"])
        cast_endorsement(cycle["id"], ridge["id"])

        adopted = validate_success(api_client.close_endorsement_round(cycle["id"], ADMIN()), 200)
        assert_fields(
            adopted,
            {"status": "ADOPTED", "achieved_weight_bps": 10000},
            "the adopted regional plan cycle",
        )
        assert adopted["adopted_at"] is not None, (
            "adoption stamps adopted_at from the logical clock, but it read null"
        )

        reopen = api_client.open_endorsement_round(cycle["id"], ADMIN())
        reclose = api_client.close_endorsement_round(cycle["id"], ADMIN())
        reengage = api_client.open_engagement(cycle["id"], ADMIN())

        for response, verb in (
            (reopen, "opening another endorsement round"),
            (reclose, "closing the round again"),
            (reengage, "reopening engagement"),
        ):
            validate_error(response, ApiErrorId.ERR_PLAN_CYCLE_STATE_INVALID.value, 409)
            assert response.status_code == 409, f"{verb} on an adopted cycle must be a 409"
        assert_fields(
            read_plan_cycle(cycle["id"]),
            {"status": "ADOPTED", "revision_count": 0, "round_number": 1},
            "the adopted cycle after three refused verbs",
        )

    def test_a_failed_round_cancels_scheduled_sessions_and_screens_projects_out(self):
        """With no revision budget left the failure reaches sessions and projects at once.

        PRD 3.8: "If instead `revision_count` plus one would exceed
        `max_revision_rounds`, the cycle moves `ENDORSEMENT_ROUND → FAILED` —
        `revision_count` is **not** incremented on this edge — with the same supersession
        of every live current-round endorsement, plus two cascades: every engagement
        session of the cycle still in `SCHEDULED` moves `SCHEDULED → CANCELLED`, leaving
        its attendance fields null and permanently excluding it from both the
        completed-session count and the host occupancy set; and every adaptation project
        of the cycle whose `screening_status` is `SCREENED_IN` **and** whose
        `program_status` is `UNPROGRAMMED` moves `SCREENED_IN → SCREENED_OUT`."  With no
        endorsements cast the tally is empty, and PRD 3.8 computes
        "`achieved_weight_bps` is 0 when the denominator is 0, and otherwise ten thousand
        multiplied by the supporting weight divided by the denominator, floored to whole
        basis points."

        Design: Corner/state_machines/plan_cycle_failed_round_cascades_to_sessions_and_screening
        """
        harbor = create_harbor()
        ridge = create_ridge()
        cycle = create_plan_cycle(
            cycle_label="One Shot Cycle",
            quorum_weight_bps=6600,
            max_revision_rounds=0,
            required_session_count=1,
        )
        project = create_screened_project(cycle["id"], harbor["id"])
        completed = create_completed_session(
            cycle["id"], harbor["id"], window_end="2026-09-10T19:00:00Z"
        )
        still_scheduled = create_session(
            cycle["id"],
            ridge["id"],
            modality="VIRTUAL",
            window_start="2026-09-20T17:00:00Z",
            window_end="2026-09-20T19:00:00Z",
        )
        open_engagement(cycle["id"])
        open_endorsement_round(cycle["id"])

        failed = validate_success(api_client.close_endorsement_round(cycle["id"], ADMIN()), 200)

        assert_fields(
            failed,
            {"status": "FAILED", "achieved_weight_bps": 0, "revision_count": 0},
            "the cycle that ran out of revision budget",
        )
        assert failed["adopted_at"] is None, (
            f"a failed cycle is never adopted, but adopted_at read {failed['adopted_at']!r}"
        )
        cancelled = read_session(still_scheduled["id"])
        assert_fields(cancelled, {"status": "CANCELLED"}, "the session the failure cancelled")
        assert_all_null(
            cancelled,
            ["attendee_count", "disadvantaged_attendee_count", "equity_reach_bps"],
            "the cancelled session",
        )
        assert_fields(
            read_session(completed["id"]),
            {"status": "COMPLETED"},
            "the session already completed before the failure",
        )
        assert_fields(
            read_project(project["id"]),
            {"screening_status": "SCREENED_OUT", "program_status": "UNPROGRAMMED"},
            "the unfunded project the failure screened out",
        )


class TestSessionCompletion:
    """Completion writes the floored equity reach, and it happens exactly once."""

    def test_completion_floors_the_equity_reach_to_whole_basis_points(self):
        """70 of 120 attendees is 5833 basis points, never 5834.

        PRD 3.8: "On success the session moves `SCHEDULED → COMPLETED` and
        `equity_reach_bps` is written as ten thousand multiplied by
        `disadvantaged_attendee_count` divided by `attendee_count`, **floored** to whole
        basis points — and defined as 0 when `attendee_count` is 0, so there is never a
        division by zero. The session's `version` increments by 1."  PRD 2.6 confirms the
        direction: "A share that works out to 61.53 percent is 6153 basis points and
        never 6154."

        Design: Corner/state_machines/engagement_session_complete_writes_equity_reach_side_effect
        """
        harbor = create_harbor()
        cycle = create_plan_cycle(required_session_count=1)
        session = create_session(
            cycle["id"], harbor["id"], modality="HYBRID", window_end="2026-09-10T19:00:00Z"
        )

        completed = validate_success(
            api_client.complete_engagement_session(
                session["id"],
                {
                    "attendee_count": 120,
                    "disadvantaged_attendee_count": 70,
                    "preferred_strategy_type": "PROTECT",
                },
                make_jurisdiction_delegate_headers(harbor["id"]),
            ),
            200,
        )

        assert_fields(
            completed,
            {
                "status": "COMPLETED",
                "attendee_count": 120,
                "disadvantaged_attendee_count": 70,
                "equity_reach_bps": 5833,
                "preferred_strategy_type": "PROTECT",
                "version": 2,
            },
            "the completed engagement session",
        )

    def test_attendance_cannot_be_restated_after_completion(self):
        """A second completion is refused and the recorded reach stands.

        PRD 3.8: "Two checks apply, in this order: the session must be in `SCHEDULED`,
        and one already `COMPLETED` or `CANCELLED` yields `ERR_SESSION_NOT_SCHEDULED`;
        then `disadvantaged_attendee_count` may not exceed `attendee_count`, or the
        request is rejected with `ERR_ATTENDANCE_MISMATCH` (HTTP 422)."

        Design: Corner/state_machines/session_complete_twice_rejected
        """
        harbor = create_harbor()
        cycle = create_plan_cycle(required_session_count=1)
        session = create_completed_session(
            cycle["id"], harbor["id"], window_end="2026-09-10T19:00:00Z"
        )

        response = api_client.complete_engagement_session(
            session["id"],
            {
                "attendee_count": 200,
                "disadvantaged_attendee_count": 150,
                "preferred_strategy_type": "RETREAT",
            },
            make_jurisdiction_delegate_headers(harbor["id"]),
        )

        validate_error(response, ApiErrorId.ERR_SESSION_NOT_SCHEDULED.value, 409)
        assert_fields(
            read_session(session["id"]),
            {
                "attendee_count": 120,
                "equity_reach_bps": 5833,
                "preferred_strategy_type": "PROTECT",
            },
            "the session whose attendance may not be restated",
        )
