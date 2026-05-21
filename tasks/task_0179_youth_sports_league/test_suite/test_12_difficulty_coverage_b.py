"""Difficulty-design coverage — second test per instance.

Every difficulty-design `instances[*]` entry MUST be covered by at
least TWO tests. test_10_difficulty_coverage.py provides one test per
instance; this file provides the second.

Each test is tagged with the rule_id and instance name so the
coverage audit can locate it. Each test cites a PRD sentence
distinct-but-supporting the same underlying rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    TEST_USERS,
    add_minutes,
    add_milliseconds,
    add_days,
    advance_clock_to,
    advance_player_to_evaluated,
    api_client,
    approve_shift,
    assert_status,
    assert_team_games_played_invariant,
    assign_referee_payload,
    assign_referee_to_game,
    check_in_shift,
    create_game_payload,
    create_guardian,
    create_player,
    create_referee,
    create_season,
    create_volunteer_shift,
    draft_pick_payload,
    forfeit_game,
    forfeit_payload,
    get_success_data,
    make_coach_headers,
    make_guardian_headers,
    populate_team_rosters,
    postpone_game,
    record_game_result,
    record_evaluation_payload,
    record_result_payload,
    reschedule_game,
    reschedule_payload,
    schedule_game,
    setup_guardian_with_approved_shifts,
    setup_playoff_bracket,
    setup_regular_season,
    setup_season_with_teams,
    validate_error,
    validate_success,
    verify_age,
    verify_age_payload,
)


# ===========================================================================
# Rule 1B — dual_variant_calc
# ===========================================================================
class TestDualVariantCalcSecond:

    def test_guardian_hours_sum_then_round_three_shifts(self, api):
        """PRD §2.9: "The sum is computed at full precision and only
        the final total is rounded to two decimal places using
        half-up".

        Claim (difficulty 1A second test): three approved 90-minute
        shifts (each 1.50 hours) sum to 4.50 hours — distinct from the
        two-shift case in test_10.
        """
        # difficulty: dual_variant_calc/guardian_hours_sum_then_round_vs_round_per_row
        season = create_season(volunteer_hours_required_per_family=6.00)
        guardian, shifts = setup_guardian_with_approved_shifts(
            season_id=season["id"],
            durations_minutes=[90, 90, 90],
        )
        for s in shifts:
            assert s["hours_credited"] == pytest.approx(1.50, abs=0.001)
        g = get_success_data(
            api.get_guardian(
                guardian["id"], TEST_USERS["league_admin_headers"],
            )
        )
        assert float(g["volunteer_hours_logged"]) == pytest.approx(
            4.50, abs=0.001,
        )

    def test_team_record_completed_only_path(self, api):
        """PRD §3.5: "On success, the scores are written, `status`
        flips to `COMPLETED`, and the team-record aggregates are
        recomputed: the winning team's `wins` is incremented by one
        and the losing team's `losses` is incremented by one."

        Claim (difficulty 1B second test): a single COMPLETED game
        with strictly greater home_score yields home.wins += 1,
        away.losses += 1 — exercises the COMPLETED variant alone.
        """
        # difficulty: dual_variant_calc/team_record_completed_vs_forfeit_aggregation
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        season = bundle["season"]
        teams = bundle["teams"]
        ref = create_referee(weekly_assignment_cap=10)
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T18:00:00.000Z",
        )
        assign_referee_to_game(game_id=g["id"], referee_id=ref["id"])
        record_game_result(
            game_id=g["id"], home_score=5, away_score=2,
            advance_clock_to_iso="2026-05-10T19:30:00.000Z",
        )
        t0 = get_success_data(
            api.get_team(teams[0]["id"], TEST_USERS["league_admin_headers"])
        )
        t1 = get_success_data(
            api.get_team(teams[1]["id"], TEST_USERS["league_admin_headers"])
        )
        assert t0["wins"] == 1 and t0["losses"] == 0
        assert t1["wins"] == 0 and t1["losses"] == 1


# ===========================================================================
# Rule 2B — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormulaSecond:

    def test_playoff_seeding_undefeated_team_seed_1(self, api):
        """PRD §3.6: "Teams are then ordered, in this priority: first
        by `win_pct` in descending order (rounded to four decimal
        places, half-up, before any comparison so that floating-point
        noise does not change ordering)".

        Claim (difficulty 2A second test): the undefeated team
        receives playoff_seed == 1 even with only one completed game
        in record — verifies win_pct DESC is the top-level sort key.
        """
        # difficulty: combinatorial_formula/playoff_seeding_multi_key_sort_mode_a
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        season = bundle["season"]
        teams = bundle["teams"]
        ref = create_referee(weekly_assignment_cap=20)
        # T0 wins against T1; T2 loses to T3; nobody plays again.
        for h_idx, a_idx, hs, as_, start, fid in [
            (0, 1, 9, 1, "2026-05-02T18:00:00.000Z", "FQA"),
            (3, 2, 5, 0, "2026-05-03T18:00:00.000Z", "FQB"),
        ]:
            g = schedule_game(
                season_id=season["id"],
                home_team_id=teams[h_idx]["id"],
                away_team_id=teams[a_idx]["id"],
                field_id=fid,
                scheduled_start=start,
            )
            assign_referee_to_game(game_id=g["id"], referee_id=ref["id"])
            record_game_result(
                game_id=g["id"], home_score=hs, away_score=as_,
                advance_clock_to_iso=add_minutes(start, 90),
            )
        advance_clock_to(TEST_DEFAULTS["SEASON_PLAYOFF_CUTOFF"])
        get_success_data(
            api.start_playoffs(
                season["id"], TEST_USERS["league_admin_headers"],
            )
        )
        t0 = get_success_data(
            api.get_team(teams[0]["id"], TEST_USERS["league_admin_headers"])
        )
        t1 = get_success_data(
            api.get_team(teams[1]["id"], TEST_USERS["league_admin_headers"])
        )
        # T0 is 1-0 (win_pct 1.0000). T1 is 0-1 (win_pct 0.0000).
        assert t0["playoff_seed"] is not None
        assert t0["playoff_seed"] == 1, (
            f"T0 (undefeated) must be seed 1, got {t0['playoff_seed']}"
        )
        # T1 is bottom.
        assert t1["playoff_seed"] == 4

    def test_two_shifts_sum_to_three_hours_mode_b(self, api):
        """PRD §2.9: "The sum is computed at full precision and only
        the final total is rounded to two decimal places using
        half-up".

        Claim (difficulty 2B second test): two 90-minute shifts yield
        exactly 3.00 logged hours — sum-then-round across N=2 shifts
        is consistent with the recipe formula.
        """
        # difficulty: combinatorial_formula/guardian_volunteer_hours_sum_then_round_mode_b
        season = create_season(volunteer_hours_required_per_family=6.00)
        guardian, shifts = setup_guardian_with_approved_shifts(
            season_id=season["id"],
            durations_minutes=[90, 90],
        )
        g = get_success_data(
            api.get_guardian(
                guardian["id"], TEST_USERS["league_admin_headers"],
            )
        )
        assert float(g["volunteer_hours_logged"]) == pytest.approx(
            3.00, abs=0.001,
        )


# ===========================================================================
# Rule 3B — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachineSecond:

    def test_game_postpone_reschedule_single_cycle(self, api):
        """PRD §3.4: "Rescheduling moves a `POSTPONED` game back to
        `SCHEDULED`."
        PRD §3.4: "`original_scheduled_start` is preserved across the
        reschedule."

        Claim (difficulty 3A second test): a single
        postpone+reschedule cycle returns the game to SCHEDULED with
        original_scheduled_start preserved.
        """
        # difficulty: non_linear_state_machine/game_postpone_reschedule_cycle
        bundle = setup_regular_season(
            n_teams=4, players_per_team=8, rainout_window_days=14,
        )
        season = bundle["season"]
        teams = bundle["teams"]
        original = "2026-05-10T18:00:00.000Z"
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start=original,
        )
        postpone_game(game_id=g["id"], reason="RAIN")
        new = "2026-05-13T18:00:00.000Z"
        result = reschedule_game(
            game_id=g["id"], scheduled_start=new,
        )
        assert_status(result, "SCHEDULED")
        assert result["original_scheduled_start"] == original
        assert result["scheduled_start"] == new

    def test_player_two_branches_to_withdraw(self, api):
        """PRD §3.2: "A guardian may withdraw their own player while
        the player is in `PENDING_VERIFICATION`, `AGE_VERIFIED`, or
        `EVALUATED`".

        Claim (difficulty 3B second test): a guardian withdraws two
        players from two different source states; both land in
        WITHDRAWN.
        """
        # difficulty: non_linear_state_machine/player_branching_to_withdraw_from_three_states
        season = create_season()
        guardian = create_guardian()
        # P1 — PENDING_VERIFICATION (no verify call yet).
        p1 = create_player(
            season_id=season["id"], guardian_id=guardian["id"],
        )
        # P2 — AGE_VERIFIED.
        p2 = create_player(
            season_id=season["id"], guardian_id=guardian["id"],
        )
        verify_age(p2["id"])
        headers = make_guardian_headers(guardian["id"])
        r1 = get_success_data(api.withdraw_player(p1["id"], headers))
        r2 = get_success_data(api.withdraw_player(p2["id"], headers))
        assert r1["status"] == "WITHDRAWN"
        assert r2["status"] == "WITHDRAWN"


# ===========================================================================
# Rule 4B — transitive_cascade
# ===========================================================================
class TestTransitiveCascadeSecond:

    def test_postpone_cascade_no_shift_baseline(self, api):
        """PRD §3.4: "First, the game's `status` becomes `POSTPONED`.
        Second, `referee_id` is nulled so the referee is freed for
        that slot".

        Claim (difficulty 4A second test): postpone with no linked
        shifts still produces depth-1 effects (status=POSTPONED,
        referee_id=null).
        """
        # difficulty: transitive_cascade/game_postpone_cascade_depth_4
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        season = bundle["season"]
        teams = bundle["teams"]
        ref = create_referee(weekly_assignment_cap=10)
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T18:00:00.000Z",
        )
        assign_referee_to_game(game_id=g["id"], referee_id=ref["id"])
        result = postpone_game(game_id=g["id"], reason="FIELD_UNAVAILABLE")
        assert_status(result, "POSTPONED")
        assert result.get("referee_id") is None

    def test_loser_eliminated_after_first_playoff_complete(self, api):
        """PRD §3.6: "On a `SCHEDULED` to `COMPLETED` transition of a
        `PLAYOFF` game, the loser's `playoff_status` flips from
        `QUALIFIED` to `ELIMINATED`."

        Claim (difficulty 4B second test): completing a single round-1
        playoff game flips the loser to ELIMINATED (depth-2 effect on
        the cross-entity Team row).
        """
        # difficulty: transitive_cascade/playoff_game_complete_cascade_depth_3
        bracket = setup_playoff_bracket()
        season = bracket["season"]
        ref = bracket["referee"]
        br1 = bracket["bracket_round_1"]
        assert len(br1) == 2
        # Pick the first round-1 game and finish it; assign ref if not
        # already assigned.
        g = get_success_data(
            api.get_game(br1[0]["id"], TEST_USERS["league_admin_headers"])
        )
        if g.get("referee_id") is None:
            assign_referee_to_game(game_id=g["id"], referee_id=ref["id"])
        end_iso = add_minutes(g["scheduled_start"], 90)
        result = record_game_result(
            game_id=g["id"], home_score=7, away_score=2,
            advance_clock_to_iso=end_iso,
        )
        loser_id = result["away_team_id"]
        t = get_success_data(
            api.get_team(loser_id, TEST_USERS["league_admin_headers"])
        )
        assert t["playoff_status"] == "ELIMINATED"


# ===========================================================================
# Rule 5B — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflictSecond:

    def test_state_check_fires_when_only_state_fails(
        self, api, league_admin_headers,
    ):
        """PRD §3.2: "The verification is only valid while the season
        is in `DRAFT_OPEN`; an attempt after that surfaces as
        `ERR_SEASON_NOT_DRAFT_OPEN`."

        Claim (difficulty 5A second test): an isolated season-state
        failure (the player HAS a uri) still returns
        ERR_SEASON_NOT_DRAFT_OPEN — confirming the rule is independent
        of the safety check.
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_birth_cert
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        season = bundle["season"]
        guardian = create_guardian()
        # Player created with a uri so birth-cert check does NOT fail.
        player = create_player(
            season_id=season["id"],
            guardian_id=guardian["id"],
            birth_certificate_uri="https://example.com/bc.pdf",
        )
        resp = api.verify_age(player["id"], league_admin_headers)
        validate_error(
            resp, ApiErrorId.ERR_SEASON_NOT_DRAFT_OPEN.value,
        )

    def test_referee_overlap_alone_fires_temporal(
        self, api, league_admin_headers,
    ):
        """PRD §2.8: "A collision surfaces as `ERR_REFEREE_OVERLAP`."

        Claim (difficulty 5B second test): a pure referee-overlap
        scenario (cap is wide) still surfaces ERR_REFEREE_OVERLAP —
        confirming the temporal rule is independent of the cap rule.
        """
        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_constraint_referee_overlap
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        ref = create_referee(weekly_assignment_cap=20)  # cap not in play
        g_pre = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        assign_referee_to_game(game_id=g_pre["id"], referee_id=ref["id"])
        g_new = schedule_game(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="F2",
            scheduled_start="2026-05-10T11:00:00.000Z",  # inside the buffer
        )
        resp = api.assign_referee(
            g_new["id"],
            assign_referee_payload(referee_id=ref["id"]),
            league_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFEREE_OVERLAP.value)


# ===========================================================================
# Rule 6B — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheckSecond:

    def test_tier_70_inclusive_boundary(self, api):
        """PRD §2.10: "exactly 70.0 is `TIER_B`".
        PRD §3.2: "otherwise a score of at least 70.0 yields `TIER_B`".

        Claim (difficulty 6A second test): evaluation_score exactly
        70.0 classifies as TIER_B and 69.9 as TIER_C — distinct
        boundary point from the 85.0 case in test_10.
        """
        # difficulty: boundary_precision_check/tier_classification_inclusive_min_85
        season = create_season()
        guardian = create_guardian()
        pa = advance_player_to_evaluated(
            season_id=season["id"],
            guardian_id=guardian["id"],
            evaluation_score=70.0,
        )
        pb = advance_player_to_evaluated(
            season_id=season["id"],
            guardian_id=guardian["id"],
            evaluation_score=69.9,
        )
        assert pa["evaluation_tier"] == "TIER_B"
        assert pb["evaluation_tier"] == "TIER_C"

    def test_field_overlap_strict_one_ms_inside_window(self, api):
        """PRD §2.7: "Two slots on the same `field_id` are considered
        to collide if and only if one's start is strictly earlier than
        the other's end and vice versa".

        Claim (difficulty 6B second test): a new game on F1 starting
        precisely 1 ms BEFORE the existing scheduled_end collides ->
        ERR_FIELD_OVERLAP (strict less-than).
        """
        # difficulty: boundary_precision_check/field_overlap_touching_boundary_half_open
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        payload = create_game_payload(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T11:29:59.999Z",
        )
        resp = api.create_game(
            payload, TEST_USERS["league_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FIELD_OVERLAP.value)


# ===========================================================================
# Rule 7B — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependencySecond:

    def test_player_draft_in_draft_open_succeeds(self, api):
        """PRD §3.3: "On a successful pick, the player's `team_id` is
        set to the team's `id`, `draft_pick_overall` is set to the
        next overall pick number across the season, and the player's
        `status` flips to `DRAFTED`."

        Claim (difficulty 7A second test): the SAME draft-pick call
        succeeds when Season.status == 'DRAFT_OPEN' — establishing the
        cross-entity link between Player and Season.
        """
        # difficulty: cross_entity_state_dependency/player_draft_requires_season_draft_open
        season, teams, coaches = setup_season_with_teams(n_teams=4)
        guardian = create_guardian()
        # Evaluate a player while season still DRAFT_OPEN.
        player = advance_player_to_evaluated(
            season_id=season["id"],
            guardian_id=guardian["id"],
            evaluation_score=70.0,
        )
        team_at_pos_1 = next(t for t in teams if t["draft_position"] == 1)
        coach_at_pos_1 = next(
            c for c, t in zip(coaches, teams) if t["draft_position"] == 1
        )
        resp = api.draft_pick(
            team_at_pos_1["id"],
            draft_pick_payload(player_id=player["id"]),
            make_coach_headers(coach_at_pos_1["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "DRAFTED"
        assert data["team_id"] == team_at_pos_1["id"]

    def test_record_with_referee_assigned_succeeds(self, api):
        """PRD §3.5: "The game's `referee_id` must be non-null at the
        moment of recording".

        Claim (difficulty 7B second test): the SAME record-result call
        succeeds when referee_id IS bound — establishing the cross-
        entity link with Referee.
        """
        # difficulty: cross_entity_state_dependency/game_record_requires_referee_assigned
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        ref = create_referee(weekly_assignment_cap=10)
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T18:00:00.000Z",
        )
        assign_referee_to_game(game_id=g["id"], referee_id=ref["id"])
        result = record_game_result(
            game_id=g["id"], home_score=4, away_score=2,
            advance_clock_to_iso="2026-05-10T19:30:00.000Z",
        )
        assert result["status"] == "COMPLETED"
        assert result["referee_id"] == ref["id"]


# ===========================================================================
# Rule 8B — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlapSecond:

    def test_field_overlap_different_field_no_collision(self, api):
        """PRD §2.7: "Two slots on the same `field_id`".

        Claim (difficulty 8A second test): a second game with
        identical window but DIFFERENT field_id is permitted —
        confirms the rule is scoped per field.
        """
        # difficulty: resource_temporal_overlap/field_overlap_half_open_no_buffer
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="FA",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        payload = create_game_payload(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="FB",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        resp = api.create_game(
            payload, TEST_USERS["league_admin_headers"],
        )
        data = validate_success(resp, expected_status=201)
        # field_id is per-test-salted by conftest for isolation
        assert data["field_id"].endswith("FB")

    def test_referee_buffer_29_minutes_collides(self, api):
        """PRD §2.8: "a candidate slot `[new_start, new_end)` collides
        with an existing assignment `[a, b)` ... when `new_start` is
        strictly earlier than `b + 30 minutes`".

        Claim (difficulty 8B second test): a new assignment starting
        29 minutes after the existing scheduled_end collides ->
        ERR_REFEREE_OVERLAP.
        """
        # difficulty: resource_temporal_overlap/referee_overlap_half_open_with_30_minute_buffer
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        ref = create_referee(weekly_assignment_cap=20)
        g_pre = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        assign_referee_to_game(game_id=g_pre["id"], referee_id=ref["id"])
        # 29 minutes after end (11:30) = 11:59.
        g_b = schedule_game(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="F2",
            scheduled_start="2026-05-10T11:59:00.000Z",
        )
        resp = api.assign_referee(
            g_b["id"],
            assign_referee_payload(referee_id=ref["id"]),
            TEST_USERS["league_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_REFEREE_OVERLAP.value)


# ===========================================================================
# Rule 9B — compensating_invariant
# ===========================================================================
class TestCompensatingInvariantSecond:

    def test_postpone_cancels_shift_does_not_credit_hours(self, api):
        """PRD §2.9: "Shifts in `SCHEDULED`, `CHECKED_IN`, `NO_SHOW`,
        or `CANCELLED` contribute zero."
        PRD §3.4: "every `VolunteerShift` linked to this game (matching
        `game_id`) that is still in `SCHEDULED` is moved to
        `CANCELLED`".

        Claim (difficulty 9A second test): zero-baseline guardian +
        scheduled-then-cancelled-by-postpone shift leaves
        volunteer_hours_logged == 0.0 (cancelled shifts contribute
        zero per the invariant).
        """
        # difficulty: compensating_invariant/postpone_then_cancel_shift_leaves_volunteer_hours_unchanged
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        season = bundle["season"]
        teams = bundle["teams"]
        guardian = create_guardian()
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="FB1",
            scheduled_start="2026-06-10T18:00:00.000Z",
        )
        shift = create_volunteer_shift(
            season_id=season["id"],
            guardian=guardian,
            role="CONCESSIONS",
            scheduled_start="2026-06-10T17:30:00.000Z",
            scheduled_end="2026-06-10T19:30:00.000Z",
            game_id=g["id"],
        )
        assert shift["status"] == "SCHEDULED"
        postpone_game(game_id=g["id"], reason="SAFETY")
        cancelled = get_success_data(
            api.get_volunteer_shift(
                shift["id"], TEST_USERS["league_admin_headers"],
            )
        )
        assert cancelled["status"] == "CANCELLED"
        g_row = get_success_data(
            api.get_guardian(
                guardian["id"], TEST_USERS["league_admin_headers"],
            )
        )
        assert float(g_row["volunteer_hours_logged"]) == pytest.approx(
            0.0, abs=0.001,
        )

    def test_team_record_wl_invariant_after_two_terminals(self, api):
        """PRD §3.5: "the team-record aggregates are recomputed: the
        winning team's `wins` is incremented by one and the losing
        team's `losses` is incremented by one."

        Claim (difficulty 9B second test): after a COMPLETED win and
        a FORFEITED loss for team T0, T0.wins + T0.losses == 2,
        matching the count of terminal games involving T0.
        """
        # difficulty: compensating_invariant/forfeit_then_record_total_games_played_invariant
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        season = bundle["season"]
        teams = bundle["teams"]
        ref = create_referee(weekly_assignment_cap=20)
        # G1: T0 wins over T1.
        g1 = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T18:00:00.000Z",
        )
        assign_referee_to_game(game_id=g1["id"], referee_id=ref["id"])
        record_game_result(
            game_id=g1["id"], home_score=3, away_score=0,
            advance_clock_to_iso="2026-05-10T19:30:00.000Z",
        )
        # G2: T0 forfeits to T2.
        g2 = schedule_game(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[0]["id"],
            field_id="F2",
            scheduled_start="2026-05-17T18:00:00.000Z",
        )
        forfeit_game(game_id=g2["id"], forfeiting_team_id=teams[0]["id"])
        t0 = get_success_data(
            api.get_team(teams[0]["id"], TEST_USERS["league_admin_headers"])
        )
        assert t0["wins"] == 1
        assert t0["losses"] == 1
        assert_team_games_played_invariant(t0, 2)
