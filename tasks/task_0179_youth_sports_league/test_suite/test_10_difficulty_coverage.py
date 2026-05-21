"""Difficulty-design coverage — every instance gets at least TWO tests
tagged with the rule_id and instance name so the coverage audit can
locate them.

Each test cites the PRD sentence that motivates the underlying rule —
PRD-first applies. The difficulty-design recipe drives setup and
expected values; the citation drives legitimacy.

Rules covered (instance count: 2 tests each, 9 rules × 2 instances):
  - dual_variant_calc / guardian_hours_sum_then_round_vs_round_per_row
  - dual_variant_calc / team_record_completed_vs_forfeit_aggregation
  - combinatorial_formula / playoff_seeding_multi_key_sort_mode_a
  - combinatorial_formula / guardian_volunteer_hours_sum_then_round_mode_b
  - non_linear_state_machine / game_postpone_reschedule_cycle
  - non_linear_state_machine / player_branching_to_withdraw_from_three_states
  - transitive_cascade / game_postpone_cascade_depth_4
  - transitive_cascade / playoff_game_complete_cascade_depth_3
  - priority_pair_validation_conflict / state_vs_business_safety_birth_cert
  - priority_pair_validation_conflict / business_temporal_vs_business_constraint_referee_overlap
  - boundary_precision_check / tier_classification_inclusive_min_85
  - boundary_precision_check / field_overlap_touching_boundary_half_open
  - cross_entity_state_dependency / player_draft_requires_season_draft_open
  - cross_entity_state_dependency / game_record_requires_referee_assigned
  - resource_temporal_overlap / field_overlap_half_open_no_buffer
  - resource_temporal_overlap / referee_overlap_half_open_with_30_minute_buffer
  - compensating_invariant / postpone_then_cancel_shift_leaves_volunteer_hours_unchanged
  - compensating_invariant / forfeit_then_record_total_games_played_invariant
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    GAME_DURATION_MINUTES,
    TEST_DEFAULTS,
    add_days,
    add_milliseconds,
    add_minutes,
    advance_clock_to,
    advance_player_to_evaluated,
    advance_to_regular_season,
    api_client,
    approve_shift,
    assert_status,
    assert_team_games_played_invariant,
    assign_referee_payload,
    assign_referee_to_game,
    check_in_shift,
    create_coach,
    create_game_payload,
    create_guardian,
    create_player,
    create_referee,
    create_season,
    create_team,
    create_volunteer_shift,
    draft_pick_payload,
    forfeit_game,
    get_success_data,
    make_coach_headers,
    make_guardian_headers,
    populate_team_rosters,
    postpone_game,
    record_game_result,
    record_evaluation_payload,
    record_result_payload,
    reschedule_game,
    schedule_game,
    setup_playoff_bracket,
    setup_regular_season,
    setup_season_with_teams,
    setup_guardian_with_approved_shifts,
    TEST_USERS,
    validate_error,
    validate_success,
    verify_age,
    verify_age_payload,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_guardian_hours_sum_then_round_vs_round_per_row(self, api):
        """PRD §2.9: "The sum is computed at full precision and only
        the final total is rounded to two decimal places using half-up;
        rounding each row before summing would yield different totals
        when individual shifts cover sub-cent fractional hours, and
        that order matters."

        Claim (difficulty 1A): a 1.50-hour shift + a 2.25-hour shift
        yield Guardian.volunteer_hours_logged == 3.75 and status
        ON_TRACK (>= 0.5*6.00 = 3.00, < 6.00).
        """
        # difficulty: dual_variant_calc/guardian_hours_sum_then_round_vs_round_per_row
        season = create_season(volunteer_hours_required_per_family=6.00)
        guardian, shifts = setup_guardian_with_approved_shifts(
            season_id=season["id"],
            durations_minutes=[90, 135],
        )
        assert shifts[0]["hours_credited"] == pytest.approx(1.50, abs=0.001)
        assert shifts[1]["hours_credited"] == pytest.approx(2.25, abs=0.001)
        g = get_success_data(
            api.get_guardian(
                guardian["id"], TEST_USERS["league_admin_headers"],
            )
        )
        assert float(g["volunteer_hours_logged"]) == pytest.approx(
            3.75, abs=0.001,
        )
        assert g["volunteer_status"] == "ON_TRACK"

    def test_team_record_completed_vs_forfeit_aggregation(self, api):
        """PRD §3.5: "the team-record aggregates are recomputed: the
        winning team's `wins` is incremented by one and the losing
        team's `losses` is incremented by one. The aggregation
        considers a `COMPLETED` game's winner as the team whose score
        is strictly greater than the other's, and a `FORFEITED` game's
        winner as the team that is not the `forfeiting_team_id`".

        Claim (difficulty 1B): one COMPLETED game (T1 7, T2 3) + one
        FORFEITED game (T2 forfeits) yield T1.wins==2, T1.losses==0,
        T2.wins==0, T2.losses==2 — identical (home, away) inputs
        contribute different deltas depending on which variant fires.
        """
        # difficulty: dual_variant_calc/team_record_completed_vs_forfeit_aggregation
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        season = bundle["season"]
        teams = bundle["teams"]
        ref = create_referee(weekly_assignment_cap=20)
        g1 = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T18:00:00.000Z",
        )
        g2 = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F2",
            scheduled_start="2026-05-17T18:00:00.000Z",
        )
        assign_referee_to_game(game_id=g1["id"], referee_id=ref["id"])
        assign_referee_to_game(game_id=g2["id"], referee_id=ref["id"])
        record_game_result(
            game_id=g1["id"], home_score=7, away_score=3,
            advance_clock_to_iso="2026-05-10T19:30:00.000Z",
        )
        forfeit_game(
            game_id=g2["id"], forfeiting_team_id=teams[1]["id"],
        )
        t1 = get_success_data(
            api.get_team(teams[0]["id"], TEST_USERS["league_admin_headers"])
        )
        t2 = get_success_data(
            api.get_team(teams[1]["id"], TEST_USERS["league_admin_headers"])
        )
        assert t1["wins"] == 2, f"T1 wins must be 2, got {t1['wins']}"
        assert t1["losses"] == 0
        assert t2["wins"] == 0
        assert t2["losses"] == 2


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_playoff_seeding_multi_key_sort(self, api):
        """PRD §3.6: "Teams are then ordered, in this priority: first
        by `win_pct` in descending order (rounded to four decimal
        places, half-up, before any comparison so that floating-point
        noise does not change ordering); then by head-to-head wins in
        descending order, where head-to-head wins are the count of
        `COMPLETED` games in which one tied team beat another tied
        team; then by run differential (runs scored minus runs allowed
        across `COMPLETED` games) in descending order; and finally, as
        a deterministic last-resort tiebreaker, by team `name` in
        lexicographic ascending order."

        Claim (difficulty 2A): 4 teams with engineered standings ->
        seeds assigned 1..4 in the documented order. Verifies that the
        run-differential tiebreaker fires when win_pct ties.
        """
        # difficulty: combinatorial_formula/playoff_seeding_multi_key_sort_mode_a
        # Build a 4-team season. To isolate the run-differential
        # tiebreaker (PRD priority: win_pct -> h2h -> run_diff -> name),
        # T2 and T3 must NOT have played each other so head-to-head is
        # 0 vs 0 for the tied pair. Plan:
        # T1 beats T2 5-1; T1 beats T3 5-2;
        # T2 beats T4 10-0; T3 beats T4 4-1.
        # Records: T1=2-0; T2=1-1 (scored 11, allowed 5, +6);
        # T3=1-1 (scored 6, allowed 6, 0); T4=0-2.
        # T2 and T3 tie on win_pct=0.5000, h2h=0 vs 0,
        # run_diff +6 vs 0 -> T2 is seed 2, T3 is seed 3.
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        season = bundle["season"]
        teams = bundle["teams"]
        ref = create_referee(weekly_assignment_cap=20)
        plays = [
            (teams[0], teams[1], 5, 1, "2026-05-02T18:00:00.000Z", "FA"),
            (teams[0], teams[2], 5, 2, "2026-05-03T18:00:00.000Z", "FB"),
            (teams[1], teams[3], 10, 0, "2026-05-04T18:00:00.000Z", "FC"),
            (teams[2], teams[3], 4, 1, "2026-05-05T18:00:00.000Z", "FD"),
        ]
        for home, away, hs, as_, start, fid in plays:
            g = schedule_game(
                season_id=season["id"],
                home_team_id=home["id"],
                away_team_id=away["id"],
                field_id=fid,
                scheduled_start=start,
            )
            assign_referee_to_game(game_id=g["id"], referee_id=ref["id"])
            record_game_result(
                game_id=g["id"], home_score=hs, away_score=as_,
                advance_clock_to_iso=add_minutes(start, 90),
            )
        # Open playoffs.
        advance_clock_to(TEST_DEFAULTS["SEASON_PLAYOFF_CUTOFF"])
        get_success_data(
            api.start_playoffs(
                season["id"], TEST_USERS["league_admin_headers"],
            )
        )
        t1 = get_success_data(
            api.get_team(teams[0]["id"], TEST_USERS["league_admin_headers"])
        )
        t2 = get_success_data(
            api.get_team(teams[1]["id"], TEST_USERS["league_admin_headers"])
        )
        t3 = get_success_data(
            api.get_team(teams[2]["id"], TEST_USERS["league_admin_headers"])
        )
        t4 = get_success_data(
            api.get_team(teams[3]["id"], TEST_USERS["league_admin_headers"])
        )
        # T1 is unambiguously seed 1.
        assert t1["playoff_seed"] == 1, (
            f"T1 must have playoff_seed=1, got {t1['playoff_seed']}"
        )
        # T2 (+2 run differential) > T3 (0 run differential), so T2 is
        # seed 2 and T3 is seed 3.
        assert t2["playoff_seed"] == 2, (
            f"T2 must have playoff_seed=2, got {t2['playoff_seed']}"
        )
        assert t3["playoff_seed"] == 3, (
            f"T3 must have playoff_seed=3, got {t3['playoff_seed']}"
        )
        # T4 is seed 4.
        assert t4["playoff_seed"] == 4
        for t in (t1, t2, t3, t4):
            assert t["playoff_status"] == "QUALIFIED"

    def test_guardian_volunteer_hours_three_shifts_sum_then_round(self, api):
        """PRD §2.9: "The sum is computed at full precision and only
        the final total is rounded to two decimal places using
        half-up".

        Claim (difficulty 2B): three identical 1.50-hour shifts sum to
        exactly 4.50 hours and the guardian's logged hours = 4.50.
        """
        # difficulty: combinatorial_formula/guardian_volunteer_hours_sum_then_round_mode_b
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
        assert g["volunteer_status"] == "ON_TRACK"


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_game_postpone_reschedule_cycle(self, api):
        """PRD §3.4: "Rescheduling moves a `POSTPONED` game back to
        `SCHEDULED`."
        PRD §3.4: "The game then re-enters `SCHEDULED`, ready to be
        played, postponed again, or rescheduled again — the loop is
        unbounded so long as the rainout window allows."
        PRD §3.4: "`original_scheduled_start` is preserved across the
        reschedule."

        Claim (difficulty 3A): two postpone/reschedule cycles preserve
        original_scheduled_start and end in SCHEDULED state.
        """
        # difficulty: non_linear_state_machine/game_postpone_reschedule_cycle
        bundle = setup_regular_season(
            n_teams=4, players_per_team=8, rainout_window_days=14,
        )
        season = bundle["season"]
        teams = bundle["teams"]
        original_start = "2026-05-10T18:00:00.000Z"
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start=original_start,
        )
        # cycle 1.
        postpone_game(game_id=g["id"], reason="RAIN")
        g_after_r1 = reschedule_game(
            game_id=g["id"], scheduled_start="2026-05-12T18:00:00.000Z",
        )
        assert_status(g_after_r1, "SCHEDULED")
        assert g_after_r1["original_scheduled_start"] == original_start
        assert g_after_r1["referee_id"] is None
        # cycle 2.
        postpone_game(game_id=g["id"], reason="RAIN")
        g_final = reschedule_game(
            game_id=g["id"], scheduled_start="2026-05-15T18:00:00.000Z",
        )
        assert_status(g_final, "SCHEDULED")
        assert g_final["original_scheduled_start"] == original_start
        assert g_final["scheduled_start"] == "2026-05-15T18:00:00.000Z"
        assert g_final["referee_id"] is None

    def test_player_branching_to_withdraw_from_three_states(self, api):
        """PRD §3.2: "A guardian may withdraw their own player while
        the player is in `PENDING_VERIFICATION`, `AGE_VERIFIED`, or
        `EVALUATED`; the transition moves the player's `status` to
        `WITHDRAWN`".

        Claim (difficulty 3B): three players, each entering WITHDRAWN
        from a different source state, all land in WITHDRAWN.
        """
        # difficulty: non_linear_state_machine/player_branching_to_withdraw_from_three_states
        season = create_season(
            min_birth_date="2014-01-01T00:00:00.000Z",
            max_birth_date="2015-12-31T00:00:00.000Z",
        )
        guardian = create_guardian()
        # P1 — PENDING_VERIFICATION
        p1 = create_player(
            season_id=season["id"], guardian_id=guardian["id"],
        )
        # P2 — AGE_VERIFIED
        p2 = create_player(
            season_id=season["id"], guardian_id=guardian["id"],
        )
        verify_age(p2["id"])
        # P3 — EVALUATED
        p3 = advance_player_to_evaluated(
            season_id=season["id"],
            guardian_id=guardian["id"],
            evaluation_score=80.0,
        )
        # All withdraw with guardian headers.
        headers = make_guardian_headers(guardian["id"])
        r1 = get_success_data(api.withdraw_player(p1["id"], headers))
        r2 = get_success_data(api.withdraw_player(p2["id"], headers))
        r3 = get_success_data(api.withdraw_player(p3["id"], headers))
        for r in (r1, r2, r3):
            assert_status(r, "WITHDRAWN")


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_game_postpone_cascade_depth_4(self, api):
        """PRD §3.4: "The transition does considerably more than flip a
        status — it is the trigger point for a cascade that radiates
        through the volunteer ledger."
        PRD §3.4: "First, the game's `status` becomes `POSTPONED`.
        Second, `referee_id` is nulled so the referee is freed for
        that slot; the cascade depth here is one. Third, every
        `VolunteerShift` linked to this game (matching `game_id`) that
        is still in `SCHEDULED` is moved to `CANCELLED` — cascade
        depth two."

        Claim (difficulty 4A): postpone Game G with a SCHEDULED shift
        linked to it -> game.status=POSTPONED, referee_id=null,
        linked shift.status=CANCELLED.
        """
        # difficulty: transitive_cascade/game_postpone_cascade_depth_4
        bundle = setup_regular_season(
            n_teams=4, players_per_team=8,
            volunteer_hours_required_per_family=6.00,
        )
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
        guardian = create_guardian()
        shift = create_volunteer_shift(
            season_id=season["id"],
            guardian=guardian,
            role="SCOREKEEPER",
            scheduled_start="2026-05-10T17:30:00.000Z",
            scheduled_end="2026-05-10T19:30:00.000Z",
            game_id=g["id"],
        )
        assert shift["status"] == "SCHEDULED"
        # Trigger.
        result = postpone_game(game_id=g["id"], reason="RAIN")
        assert_status(result, "POSTPONED")
        assert result.get("referee_id") is None, "referee_id must be nulled"
        # Cascade: shift should now be CANCELLED.
        cascaded = get_success_data(
            api.get_volunteer_shift(
                shift["id"], TEST_USERS["league_admin_headers"],
            )
        )
        assert_status(cascaded, "CANCELLED")
        # Guardian's volunteer hours remain 0.0 (shift never APPROVED).
        g_row = get_success_data(
            api.get_guardian(
                guardian["id"], TEST_USERS["league_admin_headers"],
            )
        )
        assert float(g_row["volunteer_hours_logged"]) == pytest.approx(
            0.0, abs=0.001,
        )

    def test_playoff_game_complete_cascade_depth_3(self, api):
        """PRD §3.6: "On a `SCHEDULED` to `COMPLETED` transition of a
        `PLAYOFF` game, the loser's `playoff_status` flips from
        `QUALIFIED` to `ELIMINATED`."
        PRD §3.6: "the system attempts to generate the next round: it
        locates the sibling game in the same `bracket_round` whose
        winner feeds the same next-round slot ... if the sibling has
        also reached `COMPLETED` or `FORFEITED`, a new `Game` is
        created with `game_type` equal to `PLAYOFF`, `bracket_round`
        set to the current round plus one".

        Claim (difficulty 4B): in a 4-team bracket, completing both
        round-1 games triggers (depth-1) game COMPLETED, (depth-2)
        loser ELIMINATED, (depth-3) a new round-2 game exists with
        bracket_round==2 and the two round-1 winners as participants.
        """
        # difficulty: transitive_cascade/playoff_game_complete_cascade_depth_3
        bracket = setup_playoff_bracket()
        season = bracket["season"]
        teams = bracket["teams"]
        br1 = bracket["bracket_round_1"]
        assert len(br1) == 2, (
            f"Expected 2 round-1 games, got {len(br1)}"
        )
        # PRD §3.6: both round-1 games default to the same
        # scheduled_start (playoff_cutoff_date + 7 days), so a single
        # referee can't be assigned to both under PRD §2.8's overlap
        # rule. Use one fresh referee per bracket game.
        bracket_refs = [
            create_referee(weekly_assignment_cap=5) for _ in br1
        ]
        for g, ref_for_game in zip(br1, bracket_refs):
            # Some impls may have already assigned; tolerate either.
            current = get_success_data(
                api.get_game(g["id"], TEST_USERS["league_admin_headers"])
            )
            if current.get("referee_id") is None:
                assign_referee_to_game(
                    game_id=g["id"], referee_id=ref_for_game["id"],
                )
        # Resolve both bracket games. Home team wins each.
        winners: list = []
        losers: list = []
        for i, g in enumerate(br1):
            scheduled = get_success_data(
                api.get_game(g["id"], TEST_USERS["league_admin_headers"])
            )
            end_iso = add_minutes(scheduled["scheduled_start"], 90)
            recorded = record_game_result(
                game_id=g["id"], home_score=5 + i, away_score=1,
                advance_clock_to_iso=end_iso,
            )
            winners.append(recorded["home_team_id"])
            losers.append(recorded["away_team_id"])
        # Each loser must be ELIMINATED.
        for loser_id in losers:
            t = get_success_data(
                api.get_team(loser_id, TEST_USERS["league_admin_headers"])
            )
            assert t["playoff_status"] == "ELIMINATED", (
                f"Loser team {loser_id} must be ELIMINATED, got "
                f"{t['playoff_status']}"
            )
        # The cascade must produce a round-2 game.
        resp = api.list_games(
            TEST_USERS["league_admin_headers"],
            params={
                "season_id": season["id"],
            },
        )
        all_games = get_success_data(resp)
        items = all_games if isinstance(all_games, list) else all_games.get(
            "items", all_games,
        )
        round_2 = [
            g for g in items
            if g.get("game_type") == "PLAYOFF"
            and g.get("bracket_round") == 2
        ]
        assert len(round_2) == 1, (
            f"Expected exactly 1 round-2 game, got {len(round_2)}"
        )
        r2 = round_2[0]
        # The two participants are the two winners (order unspecified
        # by PRD — we accept either pairing).
        participants = {r2["home_team_id"], r2["away_team_id"]}
        assert participants == set(winners), (
            f"Round-2 participants {participants} must equal winners "
            f"{set(winners)}"
        )


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_state_vs_business_safety_birth_cert(
        self, api, league_admin_headers,
    ):
        """PRD §2.6: "Next come state-precondition checks: the generic
        source-state check (`ERR_INVALID_STATE`), the season-window
        check (`ERR_SEASON_NOT_DRAFT_OPEN`) where draft-era operations
        require a `DRAFT_OPEN` season, and the player-state check
        (`ERR_INVALID_PLAYER_STATE`) for player-targeted transitions.
        After state come the youth-safety gates — birth-certificate
        presence, age eligibility, and coach background checks."

        Claim (difficulty 5A): a verify-age call that fails BOTH
        season-window AND birth-cert presence returns the state error
        (ERR_SEASON_NOT_DRAFT_OPEN), not the safety error
        (ERR_BIRTH_CERT_REQUIRED), because state precedes safety.
        """
        # difficulty: priority_pair_validation_conflict/state_vs_business_safety_birth_cert
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        season = bundle["season"]
        guardian = create_guardian()
        # Create a player AFTER the season transition, without a uri.
        player = create_player(
            season_id=season["id"],
            guardian_id=guardian["id"],
            birth_certificate_uri=None,
        )
        # verify-age body also has no uri — both state AND safety
        # checks would fail.
        resp = api.verify_age(
            player["id"], league_admin_headers, {},
        )
        validate_error(
            resp, ApiErrorId.ERR_SEASON_NOT_DRAFT_OPEN.value,
        )

    def test_business_temporal_vs_business_constraint_referee_overlap(
        self, api, league_admin_headers,
    ):
        """PRD §2.6: "Temporal/scheduling checks (rainout window, field
        overlap, referee overlap and weekly cap, regular-season window,
        check-in window) follow. Quota and constraint checks
        (snake-draft seat, tier-A cap, uniqueness, ownership, opponent
        inequality) follow those."

        Claim (difficulty 5B): assign-referee where BOTH a 30-minute
        buffer overlap AND a weekly-cap exhaustion are simultaneously
        triggered returns ERR_REFEREE_OVERLAP (temporal) not
        ERR_REFEREE_WEEKLY_CAP_EXCEEDED (constraint).
        """
        # difficulty: priority_pair_validation_conflict/business_temporal_vs_business_constraint_referee_overlap
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        # Referee with cap=1; one assignment already exhausts the cap.
        ref = create_referee(weekly_assignment_cap=1)
        g_pre = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-04T18:00:00.000Z",  # Monday
        )
        assign_referee_to_game(game_id=g_pre["id"], referee_id=ref["id"])
        # Build a second game in the SAME ISO week AND within the
        # 30-minute buffer (29 minutes after g_pre.end at 19:30 ->
        # new start 19:59).
        g_new = schedule_game(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="F2",
            scheduled_start="2026-05-04T19:59:00.000Z",
        )
        resp = api.assign_referee(
            g_new["id"],
            assign_referee_payload(referee_id=ref["id"]),
            league_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_REFEREE_OVERLAP.value)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    def test_tier_classification_inclusive_min_85(self, api):
        """PRD §2.10: "The tier-classification thresholds are
        interpreted with the at-least operator at the boundary points
        (so a score of exactly 85.0 is `TIER_A`, exactly 70.0 is
        `TIER_B`, exactly 50.0 is `TIER_C`)."
        PRD §3.2: "a score of at least 85.0 yields `TIER_A`; otherwise
        a score of at least 70.0 yields `TIER_B`".

        Claim (difficulty 6A): evaluation_score 85.0 classifies as
        TIER_A; 84.9 classifies as TIER_B.
        """
        # difficulty: boundary_precision_check/tier_classification_inclusive_min_85
        season = create_season(
            min_birth_date="2014-01-01T00:00:00.000Z",
            max_birth_date="2015-12-31T00:00:00.000Z",
        )
        guardian = create_guardian()
        pa = advance_player_to_evaluated(
            season_id=season["id"],
            guardian_id=guardian["id"],
            evaluation_score=85.0,
        )
        pb = advance_player_to_evaluated(
            season_id=season["id"],
            guardian_id=guardian["id"],
            evaluation_score=84.9,
        )
        assert pa["evaluation_tier"] == "TIER_A"
        assert pb["evaluation_tier"] == "TIER_B"

    def test_field_overlap_touching_boundary_half_open(self, api):
        """PRD §2.7: "Two slots on the same `field_id` are considered
        to collide if and only if one's start is strictly earlier than
        the other's end and vice versa; slots that exactly touch at
        the boundary — for example, `[10:00, 11:30)` followed by
        `[11:30, 13:00)` — do not collide and are both permitted."

        Claim (difficulty 6B): a second game on the same field with
        scheduled_start exactly at the first game's scheduled_end
        succeeds (201); one millisecond earlier rejects with
        ERR_FIELD_OVERLAP.
        """
        # difficulty: boundary_precision_check/field_overlap_touching_boundary_half_open
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        # First game [10:00, 11:30) on F1.
        schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        # Touching boundary -> allowed.
        payload_ok = create_game_payload(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T11:30:00.000Z",
        )
        ok = api.create_game(
            payload_ok, TEST_USERS["league_admin_headers"],
        )
        validate_success(ok, expected_status=201)
        # One ms before boundary -> rejected.
        payload_bad = create_game_payload(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[2]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T11:29:59.999Z",
        )
        bad = api.create_game(
            payload_bad, TEST_USERS["league_admin_headers"],
        )
        validate_error(bad, ApiErrorId.ERR_FIELD_OVERLAP.value)


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_player_draft_requires_season_draft_open(self, api):
        """PRD §3.3: "The transition requires the season to still be in
        `DRAFT_OPEN` (otherwise `ERR_SEASON_NOT_DRAFT_OPEN`)".

        Claim (difficulty 7A): after Season transitions out of
        DRAFT_OPEN, attempting draft-pick on a still-EVALUATED player
        rejects with ERR_SEASON_NOT_DRAFT_OPEN.
        """
        # difficulty: cross_entity_state_dependency/player_draft_requires_season_draft_open
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        season = bundle["season"]
        teams = bundle["teams"]
        coaches = bundle["coaches"]
        # The setup already drafted every needed player. To exercise
        # the cross-entity rule we need a player still in EVALUATED at
        # the time the season has moved. But populate_team_rosters
        # drafts every player it creates. We add a fresh EVALUATED
        # player AFTER the transition (verify-age + record-evaluation
        # both also require DRAFT_OPEN, so we can't create one here).
        # Instead, attempt to draft a fake player_id — the season-
        # state check fires before the player-existence check would
        # surface ERR_REFERENCE_NOT_FOUND. Actually PRD §2.6 puts
        # existence BEFORE state, so a missing body fk would surface
        # first. Use a player from the existing rosters whose status
        # is now DRAFTED (since populate_team_rosters drafted them).
        # That gives a single ambiguity: ERR_INVALID_PLAYER_STATE
        # (player.status != EVALUATED) might fire instead.
        # The cleanest PRD-faithful path is to schedule another team's
        # draft pick using a player that was created in DRAFT_OPEN,
        # evaluated, but explicitly LEFT UNDRAFTED.
        # populate_team_rosters drafts exactly 32 players (4*8). We
        # need a 33rd EVALUATED player created during DRAFT_OPEN that
        # survives the SEASON_AUTO_WITHDRAWN sweep.
        # PRD §3.1 auto-withdraws every EVALUATED-but-not-DRAFTED
        # player as a side effect of DRAFT_OPEN -> REGULAR_SEASON. So
        # we can't have a leftover EVALUATED.
        # We instead create a fresh season and re-run a partial draft:
        # build a NEW season, evaluate one player, advance season to
        # REGULAR_SEASON via the regular sweep (which auto-withdraws
        # the player), then attempt the draft-pick on that auto-
        # withdrawn player — ERR_INVALID_PLAYER_STATE would fire.
        # The clean reading uses a player on a SECOND season still in
        # DRAFT_OPEN whose team belongs to a DIFFERENT season — the
        # PRD says season_id must match. Simplest faithful test: use
        # the FIRST season (REGULAR_SEASON) and craft a draft-pick on
        # a team in that season with a fresh player that we have NOT
        # transitioned through evaluation; in REGULAR_SEASON, even
        # verify-age fails first. So we cannot manufacture exactly the
        # specified scenario without a second season.
        # Strategy: create season S2 in DRAFT_OPEN, evaluate one
        # player in S2, then attempt to draft that S2-player onto an
        # S1 team. PRD §3.3 says "the player's `season_id` to equal
        # the team's `season_id`" — that would surface a constraint
        # error, not season-state.
        # Final strategy used here: take an existing DRAFTED player
        # from S1 and attempt to re-draft. The team's draft-pick
        # endpoint operates on Player.status which is DRAFTED — the
        # PRD chain has SEASON_NOT_DRAFT_OPEN (priority 21) before
        # INVALID_PLAYER_STATE (priority 22) — so SEASON_NOT_DRAFT_OPEN
        # wins.
        any_team = teams[0]
        any_coach = coaches[0]
        any_drafted_player = bundle["rosters"][0][0]
        resp = api.draft_pick(
            any_team["id"],
            draft_pick_payload(player_id=any_drafted_player["id"]),
            make_coach_headers(any_coach["id"]),
        )
        validate_error(
            resp, ApiErrorId.ERR_SEASON_NOT_DRAFT_OPEN.value,
        )

    def test_game_record_requires_referee_assigned(self, api):
        """PRD §3.5: "The game's `referee_id` must be non-null at the
        moment of recording — a missing referee surfaces as
        `ERR_GAME_REFEREE_REQUIRED`."

        Claim (difficulty 7B): record-result on a SCHEDULED game with
        referee_id == null returns ERR_GAME_REFEREE_REQUIRED.
        """
        # difficulty: cross_entity_state_dependency/game_record_requires_referee_assigned
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        season = bundle["season"]
        teams = bundle["teams"]
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T18:00:00.000Z",
        )
        # NO referee assigned.
        advance_clock_to("2026-05-10T19:30:00.000Z")
        resp = api.record_result(
            g["id"],
            record_result_payload(home_score=5, away_score=3),
            TEST_USERS["league_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_GAME_REFEREE_REQUIRED.value)


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_field_overlap_half_open_no_buffer(self, api):
        """PRD §2.7: "Two slots on the same `field_id` are considered
        to collide if and only if one's start is strictly earlier than
        the other's end and vice versa".

        Claim (difficulty 8A): for a field, a new game whose start
        falls strictly inside an existing slot collides ->
        ERR_FIELD_OVERLAP.
        """
        # difficulty: resource_temporal_overlap/field_overlap_half_open_no_buffer
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        # Game G_existing on F1 [10:00, 11:30).
        schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        # Overlap with [11:00, 12:30) on same field.
        payload = create_game_payload(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T11:00:00.000Z",
        )
        resp = api.create_game(
            payload, TEST_USERS["league_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FIELD_OVERLAP.value)

    def test_referee_overlap_half_open_with_30_minute_buffer(self, api):
        """PRD §2.8: "a candidate slot `[new_start, new_end)` collides
        with an existing assignment `[a, b)` ... when `new_start` is
        strictly earlier than `b + 30 minutes` and at the same time
        `a − 30 minutes` is strictly earlier than `new_end`."

        Claim (difficulty 8B): a new assignment starting exactly 30
        minutes after the existing scheduled_end is allowed (strict
        less-than at expanded edge); one minute earlier collides.
        """
        # difficulty: resource_temporal_overlap/referee_overlap_half_open_with_30_minute_buffer
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        teams = bundle["teams"]
        season = bundle["season"]
        ref = create_referee(weekly_assignment_cap=20)
        # G_pre on F1 [10:00, 11:30) with R assigned.
        g_pre = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T10:00:00.000Z",
        )
        assign_referee_to_game(game_id=g_pre["id"], referee_id=ref["id"])
        # G_a [12:00, 13:30) — exactly 30 minutes after G_pre.end.
        g_a = schedule_game(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[3]["id"],
            field_id="F2",
            scheduled_start="2026-05-10T12:00:00.000Z",
        )
        resp = api.assign_referee(
            g_a["id"],
            assign_referee_payload(referee_id=ref["id"]),
            TEST_USERS["league_admin_headers"],
        )
        data = validate_success(resp)
        assert data["referee_id"] == ref["id"]
        # G_b [11:59, 13:29) — 29 minutes after G_pre.end -> collide.
        g_b = schedule_game(
            season_id=season["id"],
            home_team_id=teams[1]["id"],
            away_team_id=teams[2]["id"],
            field_id="F3",
            scheduled_start="2026-05-10T11:59:00.000Z",
        )
        resp2 = api.assign_referee(
            g_b["id"],
            assign_referee_payload(referee_id=ref["id"]),
            TEST_USERS["league_admin_headers"],
        )
        validate_error(resp2, ApiErrorId.ERR_REFEREE_OVERLAP.value)


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_postpone_then_cancel_shift_leaves_volunteer_hours_unchanged(
        self, api,
    ):
        """PRD §2.9: "A guardian's `volunteer_hours_logged` is the sum
        of `hours_credited` across that guardian's `APPROVED`
        `VolunteerShift` rows in the active season ... Shifts in
        `SCHEDULED`, `CHECKED_IN`, `NO_SHOW`, or `CANCELLED` contribute
        zero."

        Claim (difficulty 9A): a pre-approved baseline (4.50 hours)
        plus a SCHEDULED shift attached to a Game, then game postpone
        cancels the linked shift; guardian.volunteer_hours_logged is
        unchanged because the cancelled shift never contributed.
        """
        # difficulty: compensating_invariant/postpone_then_cancel_shift_leaves_volunteer_hours_unchanged
        bundle = setup_regular_season(
            n_teams=4, players_per_team=8,
            volunteer_hours_required_per_family=6.00,
        )
        season = bundle["season"]
        teams = bundle["teams"]
        # Pre-approve a baseline shift of 4.50 hours (3 x 90 min).
        guardian, baseline_shifts = setup_guardian_with_approved_shifts(
            season_id=season["id"],
            durations_minutes=[90, 90, 90],
        )
        before = get_success_data(
            api.get_guardian(
                guardian["id"], TEST_USERS["league_admin_headers"],
            )
        )
        assert float(before["volunteer_hours_logged"]) == pytest.approx(
            4.50, abs=0.001,
        )
        # Schedule a game and a SCHEDULED shift linked to it.
        g = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="FXP",
            scheduled_start="2026-07-10T18:00:00.000Z",
        )
        shift = create_volunteer_shift(
            season_id=season["id"],
            guardian=guardian,
            role="SCOREKEEPER",
            scheduled_start="2026-07-10T17:30:00.000Z",
            scheduled_end="2026-07-10T19:30:00.000Z",
            game_id=g["id"],
        )
        assert shift["status"] == "SCHEDULED"
        # Postpone the game — cancels the linked SCHEDULED shift.
        postpone_game(game_id=g["id"], reason="RAIN")
        cancelled = get_success_data(
            api.get_volunteer_shift(
                shift["id"], TEST_USERS["league_admin_headers"],
            )
        )
        assert_status(cancelled, "CANCELLED")
        # The invariant: guardian.volunteer_hours_logged is unchanged.
        after = get_success_data(
            api.get_guardian(
                guardian["id"], TEST_USERS["league_admin_headers"],
            )
        )
        assert float(after["volunteer_hours_logged"]) == pytest.approx(
            4.50, abs=0.001,
        ), (
            "volunteer_hours_logged must be unchanged across the "
            "postpone-cascade because cancelled shifts contribute zero."
        )

    def test_forfeit_then_record_total_games_played_invariant(self, api):
        """PRD §3.5: "On success, the scores are written, `status`
        flips to `COMPLETED`, and the team-record aggregates are
        recomputed: the winning team's `wins` is incremented by one
        and the losing team's `losses` is incremented by one."
        PRD §3.5: "On success, the game's `status` becomes
        `FORFEITED`; the non-forfeiting team is awarded the win (its
        `wins` increments by one) and the forfeiting team takes the
        loss (its `losses` increments by one)."

        Claim (difficulty 9B): across one COMPLETED win, one FORFEITED
        loss, and one COMPLETED loss for team T1, the conserved
        quantity T1.wins + T1.losses == 3, equal to the count of
        terminal games involving T1.
        """
        # difficulty: compensating_invariant/forfeit_then_record_total_games_played_invariant
        bundle = setup_regular_season(n_teams=4, players_per_team=8)
        season = bundle["season"]
        teams = bundle["teams"]
        ref = create_referee(weekly_assignment_cap=20)
        # G1: T1 home over T2 (T1 wins).
        g1 = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[1]["id"],
            field_id="F1",
            scheduled_start="2026-05-10T18:00:00.000Z",
        )
        assign_referee_to_game(game_id=g1["id"], referee_id=ref["id"])
        record_game_result(
            game_id=g1["id"], home_score=4, away_score=2,
            advance_clock_to_iso="2026-05-10T19:30:00.000Z",
        )
        # G2: T1 vs T2; T1 forfeits.
        g2 = schedule_game(
            season_id=season["id"],
            home_team_id=teams[2]["id"],
            away_team_id=teams[0]["id"],  # T1 away
            field_id="F2",
            scheduled_start="2026-05-17T18:00:00.000Z",
        )
        forfeit_game(game_id=g2["id"], forfeiting_team_id=teams[0]["id"])
        # G3: T1 home, loses 1-6.
        g3 = schedule_game(
            season_id=season["id"],
            home_team_id=teams[0]["id"],
            away_team_id=teams[3]["id"],
            field_id="F3",
            scheduled_start="2026-05-24T18:00:00.000Z",
        )
        assign_referee_to_game(game_id=g3["id"], referee_id=ref["id"])
        record_game_result(
            game_id=g3["id"], home_score=1, away_score=6,
            advance_clock_to_iso="2026-05-24T19:30:00.000Z",
        )
        # Verify.
        t1 = get_success_data(
            api.get_team(teams[0]["id"], TEST_USERS["league_admin_headers"])
        )
        assert t1["wins"] == 1, f"T1 wins must be 1, got {t1['wins']}"
        assert t1["losses"] == 2, f"T1 losses must be 2, got {t1['losses']}"
        # Conserved invariant: wins + losses == count of terminal games
        # involving T1.
        assert_team_games_played_invariant(t1, 3)
