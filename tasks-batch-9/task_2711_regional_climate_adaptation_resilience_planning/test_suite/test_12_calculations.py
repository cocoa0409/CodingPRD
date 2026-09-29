"""Derived magnitudes: banding floors, capped factors, filtered input sets, tallies."""

from test_helpers import (
    ADMIN,
    ANALYST,
    add_certified_retrofit_project,
    allocate,
    api_client,
    assert_fields,
    assert_program_conservation,
    award_grant,
    cast_endorsement,
    certified_levee_context,
    certified_retrofit_context,
    certify_analysis,
    create_analysis,
    create_asset_link,
    close_endorsement_round,
    complete_session,
    create_asset,
    create_assessed_assessment,
    create_assessment,
    create_capital_program,
    create_harbor,
    create_jurisdiction,
    create_plan_cycle,
    create_project,
    create_published_profile,
    create_ridge,
    create_screened_project,
    create_session,
    open_endorsement_round,
    open_engagement,
    patch_jurisdiction,
    read_assessment,
    read_capital_program,
    read_endorsement,
    read_jurisdiction,
    read_project,
    read_tally,
    report_indicator,
    screen_project,
    submit_grant,
    validate_paginated,
    validate_success,
)


class TestSocialVulnerabilityBanding:
    """Each tier floor is inclusive below and exclusive above."""

    def test_six_scores_straddling_every_floor_land_in_the_expected_tiers(self):
        """0.24/0.25/0.49/0.50/0.74/0.75 give LOW/MODERATE/MODERATE/HIGH/HIGH/SEVERE.

        PRD 3.1: "The banding is: `SEVERE` when the score is at least 0.75; `HIGH` when
        the score is at least 0.50 but below 0.75; `MODERATE` when the score is at least
        0.25 but below 0.50; and `LOW` otherwise. Each floor is inclusive, so a score of
        exactly 0.50 lands in `HIGH` and a score of exactly 0.25 lands in `MODERATE`,
        while 0.24 falls to `LOW` and 0.75 rises to `SEVERE`."  The derived boolean
        follows from the same paragraph: "`disadvantaged_flag` is true exactly when
        `svi_tier` is `HIGH` or `SEVERE`, and false for `MODERATE` and `LOW`".

        Design: Corner/calculations/svi_tier_floors_are_inclusive_at_every_boundary
        """
        expectations = (
            (0.24, "LOW", False),
            (0.25, "MODERATE", False),
            (0.49, "MODERATE", False),
            (0.50, "HIGH", True),
            (0.74, "HIGH", True),
            (0.75, "SEVERE", True),
        )
        for index, (score, tier, flag) in enumerate(expectations):
            member = create_jurisdiction(
                name=f"Boundary {index}",
                jurisdiction_code=f"B-{index:03d}",
                population=1000,
                svi_score=score,
                endorsement_weight=1,
            )
            assert_fields(
                read_jurisdiction(member["id"]),
                {"svi_tier": tier, "disadvantaged_flag": flag},
                f"the member government scored {score}",
            )

        _rows, meta = validate_paginated(
            api_client.list_jurisdictions(ADMIN(), params={"disadvantaged_flag": True})
        )
        assert meta["total_count"] == 3, (
            "three of the six scores sit at or above the HIGH floor, but the filtered "
            f"collection reported {meta['total_count']}"
        )


class TestConsequenceScoreInputs:
    """The cascade factor stops counting hops at three, and drafts never contribute."""

    def test_the_cascade_factor_stops_at_three_hops_while_the_depth_keeps_counting(self):
        """A depth-4 asset scores exactly what the depth-3 asset scores.

        PRD 3.4: "The **cascade factor** is 1.00 plus 0.15 for each hop of dependency
        depth, counting at most three hops, so a depth of 0 gives 1.00, a depth of 1
        gives 1.15, a depth of 2 gives 1.30, and a depth of 3 or anything deeper gives
        1.45 and no more."  The depth itself keeps counting, because PRD 3.4 defines
        "**`dependency_depth`** is the number of hops from this asset up its chain of
        `upstream_asset_id` pointers to the root; a root asset has a depth of 0, an asset
        one hop below a root has a depth of 1, and so on."  Nine million-dollar units
        times a peak vulnerability of 0.82, times 1.20 for sharing, times 1.6 for the
        population weight is 14.1696 at cascade 1.00 and 20.54592 at cascade 1.45.

        Design: Corner/calculations/asset_cascade_factor_caps_at_three_counted_hops
        """
        harbor = create_harbor()
        profile = create_published_profile(harbor["id"])
        chain = []
        upstream = None
        for depth in range(5):
            asset = create_asset(
                harbor["id"],
                name=f"Chain Depth {depth}",
                upstream_asset_id=upstream,
            )
            chain.append(asset)
            upstream = asset["id"]

        ranked = {}
        for depth in (0, 3, 4):
            create_assessed_assessment(profile["id"], chain[depth]["id"])
            ranked[depth] = validate_success(
                api_client.rank_asset(chain[depth]["id"], ANALYST()), 200
            )

        assert_fields(
            ranked[0],
            {
                "criticality_status": "RANKED",
                "dependency_depth": 0,
                "consequence_score": 14.17,
                "criticality_tier": "TIER_2",
            },
            "the root of the lifeline chain",
        )
        assert_fields(
            ranked[3],
            {
                "criticality_status": "RANKED",
                "dependency_depth": 3,
                "consequence_score": 20.55,
                "criticality_tier": "TIER_2",
            },
            "the asset three hops below the root",
        )
        assert_fields(
            ranked[4],
            {
                "criticality_status": "RANKED",
                "dependency_depth": 4,
                "consequence_score": 20.55,
                "criticality_tier": "TIER_2",
            },
            "the asset four hops below the root",
        )

    def test_the_peak_vulnerability_reads_only_assessed_rows(self):
        """A draft reading that would dominate the peak is excluded from the input set.

        PRD 3.4: "The **peak vulnerability** term is the largest `vulnerability_score`
        found across the asset's `ASSESSED` assessments."  The draft row here would
        compute the clamped maximum, because PRD 3.3 says "The result is clamped to lie
        between a floor of 0.00 and a ceiling of 1.00 — **the clamp is applied to the
        unrounded value**", which would drive the consequence score to 17.28 instead of
        the 14.17 the 0.82 peak produces; the 0.67 heat reading would give 11.58.

        Design: Corner/calculations/asset_consequence_peak_ignores_unassessed_vulnerabilities
        """
        harbor = create_harbor()
        asset = create_asset(harbor["id"])
        flood = create_published_profile(harbor["id"])
        heat = create_published_profile(
            harbor["id"],
            hazard_type="HEAT",
            exposure_index=0.50,
            annual_event_probability=0.05,
            projected_annual_loss_cents=90000000,
        )
        storm = create_published_profile(
            harbor["id"],
            hazard_type="STORM",
            exposure_index=1.00,
            annual_event_probability=0.01,
            projected_annual_loss_cents=500000000,
        )
        flood_reading = create_assessed_assessment(flood["id"], asset["id"])
        heat_reading = create_assessed_assessment(heat["id"], asset["id"])
        draft_reading = create_assessment(
            storm["id"],
            asset["id"],
            subject_type="POPULATION",
            sensitivity_score=1.00,
            adaptive_capacity_score=0.00,
        )

        ranked = validate_success(api_client.rank_asset(asset["id"], ANALYST()), 200)

        assert_fields(
            flood_reading,
            {"vulnerability_score": 0.82, "vulnerability_band": "EXTREME"},
            "the flood reading",
        )
        assert_fields(
            heat_reading,
            {"vulnerability_score": 0.67, "vulnerability_band": "HIGH"},
            "the heat reading",
        )
        stored_draft = read_assessment(draft_reading["id"])
        assert_fields(stored_draft, {"status": "DRAFT"}, "the storm reading left unassessed")
        assert stored_draft["vulnerability_score"] is None, (
            "an unassessed reading carries no score, but it read "
            f"{stored_draft['vulnerability_score']!r}"
        )
        assert_fields(
            ranked,
            {
                "consequence_score": 14.17,
                "criticality_tier": "TIER_2",
                "dependency_depth": 0,
            },
            "the asset ranked from its assessed readings only",
        )


class TestCostStackBoundaries:
    """The screen-in floor and the local-match tier are both decided on exact figures."""

    def test_a_score_landing_exactly_on_the_floor_is_screened_in(self):
        """0.4500 is screened in; 0.4465 is screened out, and both are priced.

        PRD 3.5: "The screening outcome is decided on the **rounded** `screen_score`
        against a floor of 0.4500. A score of at least 0.4500 moves the project
        `PROPOSED → SCREENED_IN`; a score below 0.4500 moves it `PROPOSED →
        SCREENED_OUT`, which is terminal for the screening dimension. Both outcomes write
        exactly the same fields: `escalated_cost_cents`, `admin_rate_bps`,
        `admin_fee_cents`, `total_program_cost_cents`, `grant_match_share_bps` and
        `screen_score` are all persisted on either branch".  With a total program cost of
        62500000 the cost component is 0.6875, so the weighted sum is 0.275 + 0 + 0.175 =
        0.4500 at feasibility 0.50 and 0.275 + 0 + 0.1715 = 0.4465 at feasibility 0.49.

        Design: Corner/calculations/screen_score_at_the_exact_screen_in_floor
        """
        harbor = create_harbor()
        cycle = create_plan_cycle(required_session_count=0)
        at_floor = create_project(
            cycle["id"],
            harbor["id"],
            name="Exactly At The Floor",
            base_cost_cents=52644879,
            cobenefit_points=0,
            feasibility_score=0.50,
        )
        below_floor = create_project(
            cycle["id"],
            harbor["id"],
            name="One Notch Below",
            base_cost_cents=52644879,
            cobenefit_points=0,
            feasibility_score=0.49,
        )

        screened_in = screen_project(at_floor["id"])
        screened_out = screen_project(below_floor["id"])

        assert_fields(
            screened_in,
            {"screen_score": 0.4500, "screening_status": "SCREENED_IN"},
            "the project sitting exactly on the screening floor",
        )
        assert_fields(
            screened_out,
            {"screen_score": 0.4465, "screening_status": "SCREENED_OUT"},
            "the project one notch of feasibility below the floor",
        )
        priced = {
            "escalated_cost_cents": 58962264,
            "admin_rate_bps": 600,
            "admin_fee_cents": 3537736,
            "total_program_cost_cents": 62500000,
            "grant_match_share_bps": 2500,
        }
        assert_fields(screened_in, priced, "the cost stack of the screened-in project")
        assert_fields(screened_out, priced, "the cost stack of the screened-out project")

    def test_one_cent_of_total_program_cost_flips_the_local_match_tier(self):
        """A total of exactly 100000000 needs 3000 basis points; 99999999 needs 2500.

        PRD 3.5: "`grant_match_share_bps` is selected from a second three-band schedule
        keyed on `total_program_cost_cents`. A total from zero up to but not including one
        million dollars requires a 2500 basis-point local match; from one million dollars
        up to but not including ten million dollars requires 3000; and ten million dollars
        or more requires 3500. Again lower bounds are inclusive and upper bounds
        exclusive."  Both projects sit in the same administration band, since PRD 3.5 says
        "from five hundred thousand dollars up to but not including five million dollars
        attracts 600 basis points", which is why only the post-fee total can explain the
        difference.

        Design: Corner/calculations/program_cost_stack_match_share_tier_boundary_reads_total_not_escalated
        """
        harbor = create_harbor()
        cycle = create_plan_cycle(required_session_count=0)
        at_tier = create_project(
            cycle["id"],
            harbor["id"],
            name="Tier Boundary At",
            hazard_type="STORM",
            base_cost_cents=84231806,
        )
        below_tier = create_project(
            cycle["id"],
            harbor["id"],
            name="Tier Boundary Below",
            hazard_type="STORM",
            base_cost_cents=84231805,
        )

        priced_at = screen_project(at_tier["id"])
        priced_below = screen_project(below_tier["id"])

        assert_fields(
            priced_at,
            {
                "escalated_cost_cents": 94339623,
                "admin_rate_bps": 600,
                "admin_fee_cents": 5660377,
                "total_program_cost_cents": 100000000,
                "grant_match_share_bps": 3000,
                "screen_score": 0.5950,
                "screening_status": "SCREENED_IN",
            },
            "the project whose total lands exactly on the tier boundary",
        )
        assert_fields(
            priced_below,
            {
                "escalated_cost_cents": 94339622,
                "admin_rate_bps": 600,
                "admin_fee_cents": 5660377,
                "total_program_cost_cents": 99999999,
                "grant_match_share_bps": 2500,
                "screen_score": 0.5950,
                "screening_status": "SCREENED_IN",
            },
            "the project one cent of total below the tier boundary",
        )


class TestEndorsementTally:
    """The veto gate, the conditioned halving, the frozen weight and the denominator."""

    @staticmethod
    def _cycle_at_endorsement_round(sponsor_id, **cycle_overrides):
        cycle = create_plan_cycle(required_session_count=0, **cycle_overrides)
        create_screened_project(cycle["id"], sponsor_id)
        open_engagement(cycle["id"])
        open_endorsement_round(cycle["id"])
        return cycle

    def test_a_veto_coalition_of_weight_three_blocks_a_cleared_quorum(self):
        """5714 basis points beats the 4000 quorum, and the plan is still not adopted.

        PRD 3.8: "If the veto weight is at least 3, the outcome is **blocked** — a veto
        coalition carrying a combined frozen weight of three or more defeats the plan
        *even when the supporting weight clears the quorum*."  A blocked outcome loops the
        cycle, because PRD 3.8 says "If `revision_count` plus one is still within
        `max_revision_rounds`, the cycle moves `ENDORSEMENT_ROUND → REVISION`,
        `revision_count` increments by 1, every endorsement of the just-closed round
        carrying `ENDORSED`, `CONDITIONED` or `VETOED` has its `decision` rewritten to
        `SUPERSEDED`".  Four supporting weight over a seven-weight active pool floors to
        5714 basis points.

        Design: Corner/calculations/endorsement_veto_blocks_even_when_the_quorum_is_cleared
        """
        harbor = create_harbor()
        ridge = create_ridge()
        cycle = self._cycle_at_endorsement_round(
            harbor["id"],
            cycle_label="Veto Cycle",
            quorum_weight_bps=4000,
            max_revision_rounds=1,
        )
        harbor_vote = cast_endorsement(cycle["id"], harbor["id"], decision="ENDORSED")
        ridge_vote = cast_endorsement(cycle["id"], ridge["id"], decision="VETOED")

        tally = read_tally(cycle["id"])
        closed = close_endorsement_round(cycle["id"])

        assert_fields(
            tally,
            {
                "round_number": 1,
                "total_active_weight": 7,
                "supporting_weight": 4,
                "veto_weight": 3,
                "achieved_weight_bps": 5714,
                "quorum_weight_bps": 4000,
            },
            "the read-only projection of the open round",
        )
        assert isinstance(tally.get("projected_outcome"), str) and tally["projected_outcome"], (
            "the projection reports a projected_outcome string, but it read "
            f"{tally.get('projected_outcome')!r}"
        )
        assert_fields(
            closed,
            {"status": "REVISION", "achieved_weight_bps": 5714, "revision_count": 1},
            "the cycle the veto coalition sent back for revision",
        )
        assert closed["adopted_at"] is None, (
            f"a blocked cycle is never adopted, but adopted_at read {closed['adopted_at']!r}"
        )
        assert_fields(
            read_endorsement(harbor_vote["id"]),
            {"decision": "SUPERSEDED", "round_number": 1, "weight_at_cast": 4},
            "the supporting vote of the closed round",
        )
        assert_fields(
            read_endorsement(ridge_vote["id"]),
            {"decision": "SUPERSEDED", "round_number": 1, "weight_at_cast": 3},
            "the blocking vote of the closed round",
        )

    def test_conditioned_weight_is_halved_once_over_the_summed_total(self):
        """Two conditioned weight-3 votes contribute 3, not 2, and the plan adopts.

        PRD 3.8: "From that set, the **supporting weight** is the sum of `weight_at_cast`
        over the `ENDORSED` rows, plus half of the sum of `weight_at_cast` over the
        `CONDITIONED` rows — where the halving is **floored and applied once to the sum of
        conditioned weights, never per endorsement**."  Three of ten active weight is
        exactly 3000 basis points, and PRD 3.8 adopts on the inclusive comparison: "if
        `achieved_weight_bps` is at least the cycle's `quorum_weight_bps`, the outcome is
        **adopted**. The comparison is inclusive, so landing exactly on the quorum
        adopts."

        Design: Corner/calculations/endorsement_conditioned_credit_halves_the_sum_exactly_once
        """
        first = create_jurisdiction(
            name="Cond One",
            jurisdiction_code="C-ONE",
            population=30000,
            svi_score=0.55,
            endorsement_weight=3,
        )
        second = create_jurisdiction(
            name="Cond Two",
            jurisdiction_code="C-TWO",
            population=32000,
            svi_score=0.40,
            endorsement_weight=3,
        )
        create_jurisdiction(
            name="Silent Four",
            jurisdiction_code="S-FOUR",
            population=90000,
            svi_score=0.20,
            endorsement_weight=4,
        )
        cycle = create_plan_cycle(
            cycle_label="Conditioned Cycle",
            quorum_weight_bps=3000,
            max_revision_rounds=1,
            required_session_count=0,
        )
        create_screened_project(
            cycle["id"],
            first["id"],
            name="Cond Project",
            hazard_type="HEAT",
            strategy_type="ACCOMMODATE",
            base_cost_cents=30000000,
            service_life_years=25,
            cobenefit_points=10,
            feasibility_score=0.65,
        )
        open_engagement(cycle["id"])
        open_endorsement_round(cycle["id"])
        first_vote = cast_endorsement(
            cycle["id"],
            first["id"],
            decision="CONDITIONED",
            condition_note="Fund the cooling centres first.",
        )
        second_vote = cast_endorsement(
            cycle["id"],
            second["id"],
            decision="CONDITIONED",
            condition_note="Add a drought annex before adoption.",
        )

        tally = read_tally(cycle["id"])
        closed = close_endorsement_round(cycle["id"])

        assert_fields(
            tally,
            {
                "total_active_weight": 10,
                "supporting_weight": 3,
                "veto_weight": 0,
                "achieved_weight_bps": 3000,
            },
            "the projection over two conditioned votes",
        )
        assert_fields(
            closed,
            {"status": "ADOPTED", "achieved_weight_bps": 3000, "revision_count": 0},
            "the cycle adopted on conditioned support alone",
        )
        assert closed["adopted_at"] is not None, (
            "adoption stamps adopted_at from the logical clock, but it read null"
        )
        for vote, label in ((first_vote, "the first"), (second_vote, "the second")):
            assert_fields(
                read_endorsement(vote["id"]),
                {"decision": "CONDITIONED", "weight_at_cast": 3},
                f"{label} conditioned vote, which an adopted round supersedes not at all",
            )

    def test_reweighting_a_member_after_it_voted_moves_only_the_denominator(self):
        """Harbor's vote still counts 4 while the pool it is divided by grows to 9.

        PRD 3.1: "Supplying a new `endorsement_weight` changes the denominator of every
        *future* endorsement tally but never retroactively changes the weight frozen on an
        endorsement that has already been cast".  PRD 3.8 says the same from the tally
        side: "Freezing the weight is what makes the tally auditable: re-weighting a member
        after it has voted does not change what that vote already contributes, although it
        does change the denominator described next."  Four over the new nine-weight pool
        floors to 4444 basis points, short of the 6600 quorum.

        Design: Corner/calculations/endorsement_weight_at_cast_is_frozen_while_the_denominator_moves
        """
        harbor = create_harbor()
        create_ridge()
        cycle = self._cycle_at_endorsement_round(harbor["id"], cycle_label="Reweighted Cycle")
        vote = cast_endorsement(cycle["id"], harbor["id"], decision="ENDORSED")

        reweighted = patch_jurisdiction(harbor["id"], endorsement_weight=6)
        tally = read_tally(cycle["id"])
        closed = close_endorsement_round(cycle["id"])

        assert_fields(
            reweighted,
            {"endorsement_weight": 6, "version": 2},
            "the member reweighted after voting",
        )
        assert_fields(
            tally,
            {
                "total_active_weight": 9,
                "supporting_weight": 4,
                "veto_weight": 0,
                "achieved_weight_bps": 4444,
                "quorum_weight_bps": 6600,
            },
            "the tally taken after the reweighting",
        )
        assert_fields(
            closed,
            {"status": "REVISION", "achieved_weight_bps": 4444, "revision_count": 1},
            "the cycle that fell short of its quorum",
        )
        assert_fields(
            read_endorsement(vote["id"]),
            {"weight_at_cast": 4, "decision": "SUPERSEDED"},
            "the vote whose frozen weight the reweighting could not touch",
        )

    def test_suspending_a_member_lifts_everyone_elses_share(self):
        """Removing Ridge's three from the pool turns 5714 basis points into 10000.

        PRD 3.8: "The **denominator** is the sum of `endorsement_weight` over every
        jurisdiction whose `status` is `ACTIVE`; members in `PROBATION` or `SUSPENDED`
        leave the denominator entirely, which means suspending a member mechanically raises
        everyone else's share."  With Harbor's four as the whole active pool the share is
        the full ten thousand basis points, and PRD 3.8 then adopts: "An adopted outcome
        moves the cycle `ENDORSEMENT_ROUND → ADOPTED`, writes `achieved_weight_bps`, stamps
        `adopted_at` with the logical clock instant, and increments `version` by 1."

        Design: Corner/calculations/endorsement_tally_denominator_excludes_suspended_jurisdictions
        """
        harbor = create_harbor()
        ridge = create_ridge()
        cycle = self._cycle_at_endorsement_round(harbor["id"], cycle_label="Suspension Cycle")
        vote = cast_endorsement(cycle["id"], harbor["id"], decision="ENDORSED")

        before = read_tally(cycle["id"])
        patch_jurisdiction(ridge["id"], status="SUSPENDED")
        after = read_tally(cycle["id"])
        closed = close_endorsement_round(cycle["id"])

        assert_fields(
            before,
            {"total_active_weight": 7, "supporting_weight": 4, "achieved_weight_bps": 5714},
            "the tally while both members were active",
        )
        assert_fields(
            after,
            {"total_active_weight": 4, "supporting_weight": 4, "achieved_weight_bps": 10000},
            "the tally after the silent member was suspended",
        )
        assert_fields(
            closed,
            {"status": "ADOPTED", "achieved_weight_bps": 10000, "revision_count": 0},
            "the cycle the suspension carried over the quorum",
        )
        assert_fields(
            read_endorsement(vote["id"]),
            {"decision": "ENDORSED", "weight_at_cast": 4},
            "the single surviving vote",
        )


class TestEngagementEquityReach:
    """The reach ratio is defined at zero attendance rather than dividing by zero."""

    def test_a_session_nobody_attended_reads_a_reach_of_zero(self):
        """An attendance of 0 out of 0 completes the session with equity_reach_bps 0.

        PRD 3.8: "On success the session moves `SCHEDULED → COMPLETED` and
        `equity_reach_bps` is written as ten thousand multiplied by
        `disadvantaged_attendee_count` divided by `attendee_count`, **floored** to whole
        basis points — and defined as 0 when `attendee_count` is 0, so there is never a
        division by zero."  The comparison guard cannot fire either, because PRD 3.8 says
        "`disadvantaged_attendee_count` may not exceed `attendee_count`, or the request is
        rejected with `ERR_ATTENDANCE_MISMATCH` (HTTP 422)", and zero does not exceed zero.

        Design: Corner/calculations/engagement_equity_reach_is_zero_when_nobody_attends
        """
        harbor = create_harbor()
        cycle = create_plan_cycle(cycle_label="Empty Room Cycle", required_session_count=1)
        session = create_session(cycle["id"], harbor["id"])

        completed = complete_session(
            session["id"],
            harbor["id"],
            attendee_count=0,
            disadvantaged_attendee_count=0,
            preferred_strategy_type="AVOID",
        )

        assert_fields(
            completed,
            {
                "status": "COMPLETED",
                "attendee_count": 0,
                "disadvantaged_attendee_count": 0,
                "equity_reach_bps": 0,
                "preferred_strategy_type": "AVOID",
                "version": 2,
            },
            "the session nobody attended",
        )
        rows, meta = validate_paginated(
            api_client.list_engagement_sessions(
                ADMIN(), params={"plan_cycle_id": cycle["id"], "status": "COMPLETED"}
            )
        )
        assert meta["total_count"] == 1, (
            "an unattended session still counts as completed for the engagement "
            f"threshold, but the completed listing reported {meta['total_count']}"
        )
        assert rows[0]["equity_reach_bps"] == 0, (
            f"the listed row must agree with the write, but it read {rows[0]['equity_reach_bps']!r}"
        )


class TestIndicatorAttainmentBands:
    """Delivery status is re-derived from the newest rounded percentage each period."""

    def test_four_periods_walk_both_band_floors_in_both_directions(self):
        """90.00 / 89.99 / 70.00 / 69.99 read ON_TRACK / AT_RISK / AT_RISK / OFF_TRACK.

        PRD 3.7: "`implementation_status` is then re-derived from the **rounded** attainment
        percentage: `ON_TRACK` when it is at least 90.00, `AT_RISK` when it is at least
        70.00, and `OFF_TRACK` otherwise. Both floors are inclusive, so an attainment of
        exactly 90.00 reads `ON_TRACK` and exactly 70.00 reads `AT_RISK`, while 89.99 reads
        `AT_RISK` and 69.90 reads `OFF_TRACK`."  PRD 3.7 also forbids averaging: "Each
        report **overwrites** `indicator_attainment_pct` with the newest period's figure
        rather than averaging", and "`reported_period_count` increments by 1 with every
        report".

        Design: Corner/calculations/indicator_attainment_bands_read_off_the_rounded_percentage
        """
        context = certified_levee_context(
            project_overrides={
                "name": "Harbor Levee Raise",
                "indicator_code": "FLOOD-DEPTH",
                "indicator_target_value": 100.00,
            }
        )
        harbor_id = context["harbor"]["id"]
        project_id = context["project"]["id"]
        program = create_capital_program(authorized_cents=100000000)
        allocate(program["id"], project_id, 51273600)
        submit_grant(project_id, harbor_id)
        award_grant(project_id)

        periods = (
            (90.00, "2027-Q1", "ON_TRACK"),
            (89.99, "2027-Q2", "AT_RISK"),
            (70.00, "2027-Q3", "AT_RISK"),
            (69.99, "2027-Q4", "OFF_TRACK"),
        )
        for index, (reported_value, period_label, expected_status) in enumerate(periods, start=1):
            reported = report_indicator(
                project_id, harbor_id, reported_value, period_label=period_label
            )
            assert_fields(
                reported,
                {
                    "indicator_latest_value": reported_value,
                    "indicator_attainment_pct": reported_value,
                    "latest_period_label": period_label,
                    "reported_period_count": index,
                    "implementation_status": expected_status,
                    "program_status": "AWARDED",
                },
                f"the project after the {period_label} report",
            )

        assert_fields(
            read_project(project_id),
            {
                "indicator_attainment_pct": 69.99,
                "latest_period_label": "2027-Q4",
                "reported_period_count": 4,
                "implementation_status": "OFF_TRACK",
            },
            "the project after the whole reporting year",
        )


class TestFundingPostureBoundary:
    """Ten percent of headroom is healthy; one cent less is oversubscribed."""

    def test_one_cent_of_headroom_flips_the_posture_without_closing_the_program(self):
        """1000 basis points of headroom reads OPEN and 999 reads OVERSUBSCRIBED.

        PRD 3.7: "The boundary is exact and inclusive on the healthy side: a program with
        headroom of exactly 1000 basis points is **not** oversubscribed and reads `OPEN`,
        while one cent less of headroom drops it to 999 basis points and reads
        `OVERSUBSCRIBED`."  No hold is raised on either observation, because PRD 3.7 raises
        it only at the closed posture: "Whenever the recomputed posture is `CLOSED`, the
        system sets `grant_hold_flag` to true on **every** project of that program whose
        `program_status` is `PROGRAMMED`".  The two priority scores follow PRD 3.7's
        weighting of a 1.1250 and a 1.2190 ratio against the same TIER_2 asset and a full
        equity share.

        Design: Corner/calculations/program_funding_posture_flips_oversubscribed_one_cent_past_the_boundary
        """
        context = certified_levee_context(
            avoided_loss_annual_cents=6000000,
            project_overrides={
                "name": "Boundary Project A",
                "hazard_type": "STORM",
                "base_cost_cents": 84231806,
            },
        )
        harbor_id = context["harbor"]["id"]
        project_a = context["project"]
        project_b = create_screened_project(
            context["cycle"]["id"], harbor_id, name="Boundary Project B"
        )
        create_asset_link(
            project_b["id"], harbor_id, context["asset"]["id"], 3333333,
            benefit_reaches_disadvantaged=True,
        )
        certify_analysis(
            create_analysis(project_b["id"], harbor_id, method="ANNUALIZED_EQUIVALENT")["id"]
        )
        program = create_capital_program(authorized_cents=100000000)

        funded_a = allocate(program["id"], project_a["id"], 90000000)
        at_the_boundary = read_capital_program(program["id"])
        funded_b = allocate(program["id"], project_b["id"], 1)
        past_the_boundary = read_capital_program(program["id"])

        assert_fields(
            funded_a,
            {"priority_score": 0.5988, "equity_benefit_share_bps": 10000, "program_status": "PROGRAMMED"},
            "the project holding 90 percent of the authorization",
        )
        assert_fields(
            at_the_boundary,
            {
                "committed_cents": 90000000,
                "available_cents": 10000000,
                "equity_achieved_bps": 10000,
                "funding_posture": "OPEN",
            },
            "the program with exactly ten percent of headroom left",
        )
        assert_fields(
            funded_b,
            {"priority_score": 0.6129, "allocated_cents": 1},
            "the project that took the last cent over the boundary",
        )
        assert_fields(
            past_the_boundary,
            {
                "committed_cents": 90000001,
                "available_cents": 9999999,
                "equity_achieved_bps": 10000,
                "funding_posture": "OVERSUBSCRIBED",
            },
            "the program one cent past the boundary",
        )
        assert_program_conservation(at_the_boundary)
        assert_program_conservation(past_the_boundary)
        assert read_project(project_a["id"])["grant_hold_flag"] is False, (
            "an oversubscribed program raises no grant hold, but project A's "
            "grant_hold_flag was set"
        )


class TestPriorityScoreRatioCap:
    """Any certified ratio at or above 3.0000 contributes the same full component."""

    def test_a_ratio_of_three_point_three_scores_exactly_like_a_ratio_of_three(self):
        """Both allocations write priority_score 0.8800 from the same asset and share.

        PRD 3.7: "The **ratio component** is the certified analysis's `bcr` capped at
        3.0000 and then divided by 3.0000, so any ratio at or above 3.0000 contributes the
        full amount."  The remaining terms are fixed by the same sentence-set — "the
        largest tier value among the assets the project links to, where `TIER_1` is worth
        1.00, `TIER_2` is worth 0.60 and `TIER_3` is worth 0.30" and "The **equity
        component** is `equity_benefit_share_bps` divided by ten thousand, capped at
        1.0000" — so 0.45 plus 0.30 times 0.60 plus 0.25 is 0.8800 on both rows.

        Design: Corner/calculations/priority_score_caps_the_benefit_cost_ratio_at_three
        """
        context = certified_retrofit_context(
            avoided_loss_annual_cents=7000000,
            project_overrides={"name": "Above The Cap", "hazard_type": "HEAT"},
        )
        at_the_cap = add_certified_retrofit_project(
            context,
            name="Exactly At The Cap",
            avoided_loss_annual_cents=6356880,
            hazard_type="HEAT",
        )
        program = create_capital_program(authorized_cents=100000000)

        funded_high = allocate(program["id"], context["project"]["id"], 30000000)
        funded_cap = allocate(program["id"], at_the_cap["id"], 30000000)

        assert_fields(
            context["analysis"],
            {"bcr": 3.3035, "cost_measure_cents": 2118960, "grant_eligible": True},
            "the case whose ratio sits above the cap",
        )
        cap_cases, _meta = validate_paginated(
            api_client.list_analyses(
                ADMIN(), params={"project_id": at_the_cap["id"], "status": "CERTIFIED"}
            )
        )
        assert len(cap_cases) == 1, (
            f"the second project must hold exactly one certified case, found {len(cap_cases)}"
        )
        assert_fields(
            cap_cases[0],
            {"bcr": 3.0000, "cost_measure_cents": 2118960, "grant_eligible": True},
            "the case whose ratio sits exactly on the cap",
        )
        assert_fields(
            funded_high,
            {"priority_score": 0.8800, "equity_benefit_share_bps": 10000},
            "the project whose 3.3035 ratio was clamped",
        )
        assert_fields(
            funded_cap,
            {"priority_score": 0.8800, "equity_benefit_share_bps": 10000},
            "the project sitting exactly on the cap",
        )
        assert_fields(
            read_capital_program(program["id"]),
            {"committed_cents": 60000000, "available_cents": 40000000, "funding_posture": "OPEN"},
            "the program after funding both projects",
        )
