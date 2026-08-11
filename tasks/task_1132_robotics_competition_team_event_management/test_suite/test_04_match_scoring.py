"""Match scoring: provisional vs final variants, score floor, ranking-point
thresholds, scorekeeper/referee segregation, queue completeness (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_queue_slots,
    attach_breakdowns_and_score,
    create_manual_match,
    drive_match_to_scored,
    finalize_match,
    make_head_referee_headers,
    queue_and_take_field,
    setup_matches_running,
    validate_error,
    validate_success,
    api_client,
)

QM = TEST_USERS["queue_manager_headers"]

# Six participants: first three red, last three blue (positions RED_1..BLUE_3).
def _six(ctx):
    return [entry["team"]["id"] for entry in ctx["teams"][:6]]


class TestProvisionalVsFinal:
    def test_provisional_score_omits_card_penalty(self):
        """PRD §3.5: "The `score_match` formula in its provisional variant
        computes, for each alliance color, a base of `auto_points +
        teleop_points + endgame_points`, adds `foul_points_awarded`, and
        subtracts the product of `tech_foul_count` and 5. Card penalties are
        not applied at this stage."

        Design: Difficulty/dual_variant_calc/score_match_provisional_vs_final_card_penalty
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        match = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9101,
        )
        scored, _ = drive_match_to_scored(
            ctx, match["id"], _six(ctx),
            {"auto_points": 30, "teleop_points": 80, "endgame_points": 25,
             "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "YELLOW"},
            {"auto_points": 20, "teleop_points": 70, "endgame_points": 20,
             "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"},
        )
        assert scored["status"] == "SCORED"
        assert scored["red_score"] == 135  # 30+80+25; YELLOW not applied yet
        assert scored["blue_score"] == 110

    def test_final_score_applies_card_penalty(self):
        """PRD §3.5: "On `SCORED → FINALIZED`, `score_match` re-runs in its
        **final** variant: the provisional formula is extended by subtracting a
        card penalty — 0 if `card_issued` is `NONE`, 10 if `YELLOW`, 30 if
        `RED`. A match that provisional-scored at 120 and was then
        yellow-carded finalizes at 110."

        Design: Difficulty/dual_variant_calc/score_match_provisional_vs_final_card_penalty
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        match = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9102,
        )
        scored, _ = drive_match_to_scored(
            ctx, match["id"], _six(ctx),
            {"auto_points": 30, "teleop_points": 80, "endgame_points": 25,
             "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "YELLOW"},
            {"auto_points": 20, "teleop_points": 70, "endgame_points": 20,
             "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"},
        )
        finalized = finalize_match(ctx, match["id"])
        assert finalized["status"] == "FINALIZED"
        assert finalized["red_score"] == 125  # 135 - 10 (YELLOW)
        assert finalized["blue_score"] == 110
        assert finalized["red_score"] != scored["red_score"]


class TestScoreFloor:
    def test_scores_floor_at_zero(self):
        """PRD §3.5: "The gross is floored at zero, so a provisional alliance
        score is never negative." and "The final score is again floored at
        zero."

        Design: Corner/calculations/score_match_floor_at_zero
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        match = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9103,
        )
        scored, _ = drive_match_to_scored(
            ctx, match["id"], _six(ctx),
            # 0 base + 0 fouls - 20*5 tech = -100 -> floored to 0
            {"auto_points": 0, "teleop_points": 0, "endgame_points": 0,
             "foul_points_awarded": 0, "tech_foul_count": 20, "card_issued": "RED"},
            {"auto_points": 0, "teleop_points": 0, "endgame_points": 0,
             "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"},
        )
        assert scored["red_score"] == 0
        finalized = finalize_match(ctx, match["id"])
        # Final variant subtracts RED card (30) as well: still floored at 0.
        assert finalized["red_score"] == 0


class TestRankingPointThresholds:
    def test_auto_bonus_uses_strict_greater_than_25(self):
        """PRD §3.5: "Bonus points are added when the alliance's breakdown
        exceeds fixed thresholds — strictly greater than 25 `auto_points`
        earns 1 bonus ranking point ... The bonuses use strict greater-than,
        not greater-than-or-equal; exactly 25 auto points earns no bonus."

        Design: Difficulty/boundary_precision_check/ranking_points_auto_threshold_strict_gt
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        match = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9104,
        )
        scored, _ = drive_match_to_scored(
            ctx, match["id"], _six(ctx),
            # RED: 25 auto (no bonus), loses 75-76 -> 0 RP
            {"auto_points": 25, "teleop_points": 50, "endgame_points": 0,
             "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"},
            # BLUE: 26 auto (>25 -> +1), wins -> 2 + 1 = 3 RP
            {"auto_points": 26, "teleop_points": 50, "endgame_points": 0,
             "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"},
        )
        assert scored["red_ranking_points"] == 0
        assert scored["blue_ranking_points"] == 3

    def test_endgame_bonus_uses_strict_greater_than_20(self):
        """PRD §3.5: "strictly greater than 20 `endgame_points` earns another 1
        bonus ranking point."

        Design: Difficulty/boundary_precision_check/ranking_points_auto_threshold_strict_gt
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        match = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9105,
        )
        scored, _ = drive_match_to_scored(
            ctx, match["id"], _six(ctx),
            # RED: endgame 20 (no bonus), loses 80-81 -> 0 RP
            {"auto_points": 10, "teleop_points": 50, "endgame_points": 20,
             "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"},
            # BLUE: endgame 21 (>20 -> +1), wins -> 2 + 1 = 3 RP
            {"auto_points": 10, "teleop_points": 50, "endgame_points": 21,
             "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"},
        )
        assert scored["red_ranking_points"] == 0
        assert scored["blue_ranking_points"] == 3


class TestScoreFinalizeSegregation:
    def test_same_human_cannot_score_and_finalize(self):
        """PRD §3.5: "the same human may not both score and finalize — the
        referee's `X-User-ID` is compared against the `Person.id` of the
        scorekeeper who performed the score transition, and a match is
        rejected with `ERR_SEGREGATION_VIOLATION`."

        Design: Corner/validations/segregation_violation_score_finalize_same_user
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        match = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9106,
        )
        drive_match_to_scored(
            ctx, match["id"], _six(ctx),
            {"auto_points": 10, "teleop_points": 40, "endgame_points": 10,
             "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"},
            {"auto_points": 5, "teleop_points": 20, "endgame_points": 5,
             "foul_points_awarded": 0, "tech_foul_count": 0, "card_issued": "NONE"},
        )
        # Finalize as HeadReferee but with the SAME Person id that scored.
        resp = api_client.finalize_match(
            ctx["event"]["id"], match["id"],
            make_head_referee_headers(ctx["scorekeeper"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION)


class TestQueueCompleteness:
    def test_queue_with_incomplete_slots_rejected(self):
        """PRD §3.5: queueing "requires all 6 `QueueSlot` rows for the match to
        exist — otherwise `ERR_INCOMPLETE_QUEUE` (HTTP 409)".

        Design: Corner/state_machines/match_queue_with_incomplete_slots_returns_error
        """
        ctx = setup_matches_running(num_teams=6, field_count=2)
        match = create_manual_match(
            ctx, ctx["teams"][0]["team"]["id"], ctx["teams"][3]["team"]["id"],
            match_number=9107,
        )
        add_queue_slots(ctx, match["id"], _six(ctx)[:4])  # only 4 of 6 slots
        resp = api_client.queue_match(ctx["event"]["id"], match["id"], QM)
        validate_error(resp, ApiErrorId.ERR_INCOMPLETE_QUEUE)
