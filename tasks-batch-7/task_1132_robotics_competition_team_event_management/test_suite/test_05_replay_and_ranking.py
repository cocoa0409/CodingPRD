"""Match replay cycle, ranking reversal, and the forward-looking projection
(PRD §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    complete_open_reset_log,
    create_manual_match,
    create_violation_payload,
    drive_match_to_finalized,
    drive_match_to_scored,
    finalize_match,
    make_head_referee_headers,
    setup_matches_running,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    api_client,
)

SK = TEST_USERS["scorekeeper_headers"]
HR = TEST_USERS["head_referee_headers"]


def _six(ctx):
    return [entry["team"]["id"] for entry in ctx["teams"][:6]]


def _red_wins_no_bonus():
    return (
        {"auto_points": 10, "teleop_points": 40, "endgame_points": 10,
         "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"},
        {"auto_points": 5, "teleop_points": 20, "endgame_points": 5,
         "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"},
    )


def _red_wins_auto_bonus():
    return (
        {"auto_points": 30, "teleop_points": 40, "endgame_points": 0,
         "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"},
        {"auto_points": 5, "teleop_points": 20, "endgame_points": 5,
         "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"},
    )


def _open_match_review_violation(ctx, match_id, team_id):
    """A MATCH_REVIEW violation against a team on the match (the only
    team-linked handle a violation has for referencing a match)."""
    return validate_success(
        api_client.create_violation(
            ctx["event"]["id"], team_id,
            create_violation_payload(
                source_kind="MATCH_REVIEW",
                severity="MAJOR",
                description=f"score dispute for match {match_id}",
                opened_by_person_id=ctx["inspector"]["id"],
            ),
            HR,
        ),
        expected_status=201,
    )


class TestReplayCycle:
    def test_scored_match_replayed_and_new_match_reenters_cycle(self):
        """PRD §3.5: "A `HeadReferee` may move `SCORED → REPLAYED` only when at
        least one `ComplianceViolation` with `source_kind` equal to
        `MATCH_REVIEW` references this match" and "the match remains in
        `REPLAYED`. A new `Match` row is created via the schedule-replay
        workflow to actually run the rematch."

        Design: Difficulty/non_linear_state_machine/match_cyclic_scored_to_replayed_to_new_match
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        red_bd, blue_bd = _red_wins_no_bonus()
        m1 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9201, field_index=1,
        )
        drive_match_to_scored(ctx, m1["id"], _six(ctx), red_bd, blue_bd)
        _open_match_review_violation(ctx, m1["id"], ctx["teams"][0]["team"]["id"])
        replayed = validate_success(
            api_client.replay_match(
                ctx["event"]["id"], m1["id"],
                make_head_referee_headers(ctx["referee"]["id"]),
            )
        )
        assert replayed["status"] == "REPLAYED"
        # m1's score-time FieldResetLog is still IN_PROGRESS; completing it is
        # permitted while the parent match is REPLAYED (PRD §3.5) and the next
        # match on field 1 cannot take the field until it is COMPLETE.
        complete_open_reset_log(ctx, m1["id"])
        # The rematch enters the same lifecycle from SCHEDULED.
        m2 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9202, field_index=1,
        )
        assert m2["status"] == "SCHEDULED"
        scored2, _ = drive_match_to_scored(ctx, m2["id"], _six(ctx), red_bd, blue_bd)
        assert scored2["status"] == "SCORED"

    def test_replay_without_match_review_grounds_rejected(self):
        """PRD §3.5: replay is permitted "only when at least one
        `ComplianceViolation` with `source_kind` equal to `MATCH_REVIEW`
        references this match; otherwise the call is rejected with
        `ERR_NO_REPLAY_GROUNDS`."

        Design: Difficulty/non_linear_state_machine/match_cyclic_scored_to_replayed_to_new_match
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        red_bd, blue_bd = _red_wins_no_bonus()
        m1 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9203,
        )
        drive_match_to_scored(ctx, m1["id"], _six(ctx), red_bd, blue_bd)
        resp = api_client.replay_match(
            ctx["event"]["id"], m1["id"],
            make_head_referee_headers(ctx["referee"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_REPLAY_GROUNDS)


class TestRankingReversal:
    def test_replay_excludes_match_from_team_aggregates(self):
        """PRD §3.5: "On replay, the prior ranking points are reversed from
        each team's aggregate (which is to say: each team's
        `team_ranking_score` is recomputed against the now-smaller set of
        finalized matches)" — the FINALIZED-only aggregate is unchanged when a
        never-finalized match is replayed out, and the replayed match is
        excluded from then on.

        Design: Difficulty/compensating_invariant/ranking_points_reversal_on_replay
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        red_bd, blue_bd = _red_wins_no_bonus()  # red rp=2, tie 20 per red team
        m1 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9204, field_index=1,
        )
        drive_match_to_finalized(ctx, m1["id"], _six(ctx), red_bd, blue_bd)
        t1 = ctx["teams"][0]["team"]["id"]
        before = validate_success(api_client.get_team(ctx["event"]["id"], t1, SK))
        assert before["matches_played"] == 1
        assert before["ranking_score"] == pytest.approx(2.0, abs=1e-4)
        # Second match: SCORED but never finalized, then replayed out.
        m2 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9205, field_index=2,
        )
        drive_match_to_scored(ctx, m2["id"], _six(ctx), red_bd, blue_bd)
        _open_match_review_violation(ctx, m2["id"], t1)
        validate_success(
            api_client.replay_match(
                ctx["event"]["id"], m2["id"],
                make_head_referee_headers(ctx["referee"]["id"]),
            )
        )
        after = validate_success(api_client.get_team(ctx["event"]["id"], t1, SK))
        assert after["matches_played"] == before["matches_played"]
        assert after["ranking_score"] == pytest.approx(before["ranking_score"], abs=1e-4)
        assert after["ranking_tie_break"] == pytest.approx(before["ranking_tie_break"], abs=1e-4)

    def test_double_replay_rejected(self):
        """PRD §3.5: a `HeadReferee` "may move `SCORED → REPLAYED`" only from
        SCORED, and PRD §2.7: "Entity state (`ERR_INVALID_STATE`) — the target
        entity must be in the `from` state the transition requires; if it is
        already in a terminal state, the more specific `ERR_ALREADY_TERMINAL`
        is used instead." A second replay against a match already in REPLAYED
        is rejected by that state check.

        Design: Difficulty/compensating_invariant/ranking_points_reversal_on_replay
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        red_bd, blue_bd = _red_wins_no_bonus()
        m1 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9206,
        )
        drive_match_to_scored(ctx, m1["id"], _six(ctx), red_bd, blue_bd)
        _open_match_review_violation(ctx, m1["id"], ctx["teams"][0]["team"]["id"])
        validate_success(
            api_client.replay_match(
                ctx["event"]["id"], m1["id"],
                make_head_referee_headers(ctx["referee"]["id"]),
            )
        )
        resp = api_client.replay_match(
            ctx["event"]["id"], m1["id"],
            make_head_referee_headers(ctx["referee"]["id"]),
        )
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL]
        )

    def test_ranking_score_excludes_replayed_matches(self):
        """PRD §3.5: the aggregation "collects every `QUALIFICATION` match in
        `FINALIZED` status on which the team appears (either alliance)" and
        "`matches_played` is `n`" — a REPLAYED match is not in the input set.

        Design: Corner/calculations/ranking_score_excludes_replayed_matches
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        red_bd, blue_bd = _red_wins_no_bonus()
        m1 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9207, field_index=1,
        )
        drive_match_to_finalized(ctx, m1["id"], _six(ctx), red_bd, blue_bd)
        m2 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9208, field_index=2,
        )
        drive_match_to_finalized(ctx, m2["id"], _six(ctx), red_bd, blue_bd)
        # Third match is scored then replayed before finalize.
        m3 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9209, field_index=1,
        )
        drive_match_to_scored(ctx, m3["id"], _six(ctx), red_bd, blue_bd)
        _open_match_review_violation(ctx, m3["id"], ctx["teams"][0]["team"]["id"])
        validate_success(
            api_client.replay_match(
                ctx["event"]["id"], m3["id"],
                make_head_referee_headers(ctx["referee"]["id"]),
            )
        )
        t1 = validate_success(
            api_client.get_team(ctx["event"]["id"], ctx["teams"][0]["team"]["id"], SK)
        )
        assert t1["matches_played"] == 2


class TestChronologicalVsForwardLooking:
    def _setup_one_finalized_one_scored(self):
        """t1: one FINALIZED match (win + auto bonus -> 3 RP) and one SCORED
        match (win, no bonus -> 2 RP)."""
        ctx = setup_matches_running(num_teams=6, field_count=2)
        m1 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9210, field_index=1,
        )
        red_bd, blue_bd = _red_wins_auto_bonus()
        drive_match_to_finalized(ctx, m1["id"], _six(ctx), red_bd, blue_bd)
        m2 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9211, field_index=2,
        )
        red2, blue2 = _red_wins_no_bonus()
        drive_match_to_scored(ctx, m2["id"], _six(ctx), red2, blue2)
        return ctx

    def test_chronological_variant_counts_finalized_only(self):
        """PRD §3.5: the pinned chronological aggregation uses "every
        `QUALIFICATION` match in `FINALIZED` status", so with one FINALIZED
        3-RP match and one still-SCORED match, `ranking_score` is 3.0.

        Design: Difficulty/dual_variant_calc/team_ranking_score_chronological_vs_forward_looking
        """
        ctx = self._setup_one_finalized_one_scored()
        t1 = validate_success(
            api_client.get_team(ctx["event"]["id"], ctx["teams"][0]["team"]["id"], SK)
        )
        assert t1["matches_played"] == 1
        assert t1["ranking_score"] == pytest.approx(3.0, abs=1e-4)

    def test_forward_looking_projection_includes_scored(self):
        """PRD §3.5: "the server returns `projected_ranking_score`,
        `projected_ranking_tie_break`, and `projected_matches_played` computed
        by the **forward_looking** variant of `team_ranking_score` — it
        includes `SCORED`-but-not-yet-`FINALIZED` matches in the average, so
        the projection during the score-to-finalize window differs from the
        pinned aggregate."

        Design: Difficulty/dual_variant_calc/team_ranking_score_chronological_vs_forward_looking
        """
        ctx = self._setup_one_finalized_one_scored()
        proj = validate_success(
            api_client.get_projected_ranking(
                ctx["event"]["id"], ctx["teams"][0]["team"]["id"], SK
            )
        )
        # (3 RP finalized + 2 RP scored) / 2 matches = 2.5
        assert proj["projected_matches_played"] == 2
        assert proj["projected_ranking_score"] == pytest.approx(2.5, abs=1e-4)


class TestProjectedRankingShape:
    def test_projected_ranking_returns_projection_object(self):
        """PRD §3.5: "the server returns `projected_ranking_score`,
        `projected_ranking_tie_break`, and `projected_matches_played`" — an
        inline projection object, distinct from the Team resource.

        Design: Corner/endpoints/computed_read_projected_ranking_shape
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        m1 = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9212,
        )
        red_bd, blue_bd = _red_wins_no_bonus()
        drive_match_to_finalized(ctx, m1["id"], _six(ctx), red_bd, blue_bd)
        proj = validate_success(
            api_client.get_projected_ranking(
                ctx["event"]["id"], ctx["teams"][0]["team"]["id"], SK
            )
        )
        assert isinstance(proj["projected_matches_played"], int)
        assert proj["projected_matches_played"] == 1
        assert "projected_ranking_score" in proj
        assert "projected_ranking_tie_break" in proj
