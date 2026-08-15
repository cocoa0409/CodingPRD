"""Forfeit-driven suspension cycle, playoff eligibility boundaries, bracket
shape, and league auto-completion (PRD §3.4, §3.5)."""
import pytest

from test_helpers import (
    COORDINATOR,
    REC_ADMIN,
    ApiErrorId,
    api_client,
    create_official,
    create_score_report_payload,
    declare_forfeit,
    finalize_game,
    make_member_headers,
    playoff_championship_context,
    report_scores,
    schedule_game,
    season_context,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _suspension_setup():
    """4-game season between X (home, teams[0]) and Y (away, teams[1])."""
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_context(num_teams=2)
    games = [
        schedule_game(ctx["league"]["id"], ctx["teams"][0]["id"],
                      ctx["teams"][1]["id"], ctx["facility"]["id"], s, e)
        for s, e in [
            ("2026-09-08T18:00:00Z", "2026-09-08T19:30:00Z"),
            ("2026-09-10T18:00:00Z", "2026-09-10T19:30:00Z"),
            ("2026-09-15T18:00:00Z", "2026-09-15T19:30:00Z"),
            ("2026-09-17T18:00:00Z", "2026-09-17T19:30:00Z"),
        ]
    ]
    ctx["games"] = games
    return ctx


def test_third_forfeit_suspends_and_cascade_forfeits_remaining_game():
    """PRD §3.4: "The **suspension sweep** fires whenever a finalize or
    forfeit has incremented a team's `forfeit_count`: if the team is `ACTIVE`
    and its `forfeit_count` has reached 3, the team moves `ACTIVE → SUSPENDED`
    and every one of its remaining `SCHEDULED` or `RESCHEDULE_REQUIRED` games
    is cascade-forfeited — each becomes `FORFEITED` with `forfeiting_team_id`
    set to the suspended team, per-game forfeit effects apply (standings and
    the automatic sportsmanship 1), except that all non-terminal officiating
    assignments on those games are `CANCELLED` with pay reversed and nobody is
    marked `WORKED`."

    Design: Difficulty/non_linear_state_machine/team_suspension_reinstatement_cycle
    """
    ctx = _suspension_setup()
    team_x = ctx["teams"][0]
    for game, past in zip(ctx["games"][:2],
                          ["2026-09-08T18:30:00Z", "2026-09-10T18:30:00Z"]):
        set_clock(past)
        declare_forfeit(game["id"], team_x["id"])
    mid = validate_success(api_client.get_team(team_x["id"], REC_ADMIN))
    assert mid["status"] == "ACTIVE"
    assert mid["forfeit_count"] == 2

    set_clock("2026-09-15T18:30:00Z")
    declare_forfeit(ctx["games"][2]["id"], team_x["id"])
    team_x_after = validate_success(api_client.get_team(
        team_x["id"], REC_ADMIN))
    assert team_x_after["status"] == "SUSPENDED"
    # The remaining SCHEDULED game is cascade-forfeited onto X.
    g4 = validate_success(api_client.get_game(
        ctx["games"][3]["id"], REC_ADMIN))
    assert g4["status"] == "FORFEITED"
    assert g4["forfeiting_team_id"] == team_x["id"]
    assert team_x_after["forfeit_count"] == 4, (
        "per-game forfeit effects of the cascade also increment the count"
    )


def test_reinstate_does_not_reset_forfeit_count():
    """PRD §3.4: "A coordinator may reinstate a `SUSPENDED` team while its
    league is `IN_SEASON` (either condition failing is `ERR_INVALID_STATE`);
    reinstatement does **not** reset `forfeit_count`, so a later finalize or
    forfeit that re-evaluates the threshold while the count is still at least
    3 will re-suspend the team."
    PRD §3.4: "The forfeiting team's `losses` increments by 1, its
    `forfeit_count` increments by 1, and it receives an automatic
    sportsmanship 1: `sportsmanship_points_total` up by 1 and
    `sportsmanship_rating_count` up by 1. The opponent's `wins` increments by
    1 and its `points` by 3, with no sportsmanship entry."

    Design: Difficulty/non_linear_state_machine/team_suspension_reinstatement_cycle
    """
    ctx = _suspension_setup()
    team_x, team_y = ctx["teams"][0], ctx["teams"][1]
    for game, past in zip(ctx["games"][:3],
                          ["2026-09-08T18:30:00Z", "2026-09-10T18:30:00Z",
                           "2026-09-15T18:30:00Z"]):
        set_clock(past)
        declare_forfeit(game["id"], team_x["id"])
    # Four automatic-1 ratings in total (three manual + the cascade-forfeit).
    team_x_mid = validate_success(api_client.get_team(
        team_x["id"], REC_ADMIN))
    assert team_x_mid["sportsmanship_rating"] == pytest.approx(1.00)
    team_y_mid = validate_success(api_client.get_team(
        team_y["id"], REC_ADMIN))
    assert team_y_mid["wins"] == 4
    assert team_y_mid["points"] == 12

    reinstated = validate_success(api_client.reinstate_team(
        team_x["id"], COORDINATOR))
    assert reinstated["status"] == "ACTIVE"
    team_x_after = validate_success(api_client.get_team(
        team_x["id"], REC_ADMIN))
    assert team_x_after["forfeit_count"] == 4, (
        "reinstatement must not reset forfeit_count"
    )
    g4 = validate_success(api_client.get_game(
        ctx["games"][3]["id"], REC_ADMIN))
    assert g4["status"] == "FORFEITED", (
        "terminal game states are not resurrected by reinstatement"
    )


def _boundary_league_at_playoff_gate():
    """Five-team single-division league whose regular season resolves to:
    Alpha 12pts / rating 4.50; Beta 0pts / rating 2.00 / 1 forfeit;
    Gamma 3pts / 4.00; Delta 0pts / 3.00; Echo 0pts / 4.00.
    Ratings come from matching score reports (each captain rates the
    opponent) plus Beta's automatic-1 from the forfeited game."""
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_context(
        num_teams=5,
        divisions=[{"name": "A", "capacity": 6, "skill_min": 1,
                    "skill_max": 10}],
        team_capacity=6, min_teams=5,
    )
    league_id = ctx["league"]["id"]
    facility_id = ctx["facility"]["id"]
    a, b, c, d, e = ctx["teams"]
    ca, cb, cc, cd, ce = ctx["captains"]
    # g1 A(home)-B, g2 A-C, g3 C(home)-B, g4 A-D, g5 A-E.
    g1 = schedule_game(league_id, a["id"], b["id"], facility_id,
                       "2026-09-08T18:00:00Z", "2026-09-08T19:30:00Z")
    g2 = schedule_game(league_id, a["id"], c["id"], facility_id,
                       "2026-09-10T18:00:00Z", "2026-09-10T19:30:00Z")
    g3 = schedule_game(league_id, c["id"], b["id"], facility_id,
                       "2026-09-15T18:00:00Z", "2026-09-15T19:30:00Z")
    g4 = schedule_game(league_id, a["id"], d["id"], facility_id,
                       "2026-09-17T18:00:00Z", "2026-09-17T19:30:00Z")
    g5 = schedule_game(league_id, a["id"], e["id"], facility_id,
                       "2026-09-22T18:00:00Z", "2026-09-22T19:30:00Z")
    set_clock("2026-09-25T00:00:00Z")
    # g1: A rates B 3, B rates A 5. g2: A rates C 4, C rates A 4.
    report_scores(g1["id"], ca, cb, 2, 1, home_rates_opponent=3,
                  away_rates_opponent=5)
    report_scores(g2["id"], ca, cc, 2, 1, home_rates_opponent=4,
                  away_rates_opponent=4)
    # g3: B forfeits -> automatic sportsmanship 1; C wins with no rating.
    declare_forfeit(g3["id"], b["id"])
    # g4: A rates D 3, D rates A 5. g5: A rates E 4, E rates A 4.
    report_scores(g4["id"], ca, cd, 2, 1, home_rates_opponent=3,
                  away_rates_opponent=5)
    report_scores(g5["id"], ca, ce, 2, 1, home_rates_opponent=4,
                  away_rates_opponent=4)
    return ctx


def test_rating_exactly_300_eligible_while_200_excluded():
    """PRD §3.5: "Eligibility is computed over the league's `ACTIVE` teams: a
    team is eligible when its status is `ACTIVE`, its `sportsmanship_rating` —
    with null treated as 0.00 — is at least 3.00 (a rating of exactly 3.00 is
    eligible), and its `forfeit_count` is at most 1 (exactly 1 forfeit is
    eligible)."
    PRD §3.4: "A team's `sportsmanship_rating` is then its
    `sportsmanship_points_total` divided by `sportsmanship_rating_count`,
    rounded half-up to two decimal places; while a team has received no
    ratings, the rating is null and is treated as 0.00 for playoff
    eligibility."

    Design: Difficulty/boundary_precision_check/sportsmanship_boundary_playoff_eligibility
    """
    ctx = _boundary_league_at_playoff_gate()
    a, b, c, d, e = ctx["teams"]
    beta = validate_success(api_client.get_team(b["id"], REC_ADMIN))
    delta = validate_success(api_client.get_team(d["id"], REC_ADMIN))
    # (3 received + 1 automatic) / 2 ratings; 1 forfeit remains eligible on
    # the forfeit axis, but the rating bound is failed.
    assert beta["sportsmanship_rating"] == pytest.approx(2.00)
    assert beta["forfeit_count"] == 1
    assert delta["sportsmanship_rating"] == pytest.approx(3.00)

    league = validate_success(api_client.start_playoffs(
        ctx["league"]["id"], COORDINATOR))
    assert league["status"] == "PLAYOFFS"
    games, _ = validate_paginated(api_client.list_games(
        COORDINATOR,
        params={"league_id": ctx["league"]["id"],
                "bracket_round": "SEMIFINAL"}))
    participants = {g["home_team_id"] for g in games} | {
        g["away_team_id"] for g in games}
    assert delta["id"] in participants, (
        "exactly 3.00 passes the inclusive eligibility bound"
    )
    assert beta["id"] not in participants, (
        "2.00 < 3.00 fails eligibility"
    )


def test_semifinal_bracket_shape_and_seeding_tiebreak():
    """PRD §3.5: "Seeding ranks the eligible teams of each division by, in
    order: `points` descending; head-to-head points descending among tied
    teams (only points earned in games between the tied teams count);
    `sportsmanship_rating` descending with null treated as 0.00;
    `forfeit_count` ascending; and finally team `created_at` ascending. A
    division with 4 or more eligible teams produces two `SEMIFINAL` games —
    seed 1 at home against seed 4 away, and seed 2 at home against seed 3
    away. A division with 2 or 3 eligible teams produces a single
    `CHAMPIONSHIP` game, seed 1 at home against seed 2 away. A division with
    fewer than 2 eligible teams produces no bracket."
    PRD §3.5: "System-created playoff games bypass the usual initial state and
    are born `RESCHEDULE_REQUIRED` with `facility_id`, `start_at`, and
    `end_at` null and `division_name` null; a coordinator schedules them
    through the reschedule action of §3.3."

    Design: Difficulty/boundary_precision_check/sportsmanship_boundary_playoff_eligibility
    """
    ctx = _boundary_league_at_playoff_gate()
    a, b, c, d, e = ctx["teams"]
    league = validate_success(api_client.start_playoffs(
        ctx["league"]["id"], COORDINATOR))
    assert league["status"] == "PLAYOFFS"
    games, meta = validate_paginated(api_client.list_games(
        COORDINATOR,
        params={"league_id": ctx["league"]["id"],
                "bracket_round": "SEMIFINAL"}))
    assert meta["total_count"] == 2, (
        "4 eligible teams (Alpha, Gamma, Delta, Echo) produce two semifinals"
    )
    for shell in games:
        assert shell["status"] == "RESCHEDULE_REQUIRED"
        assert shell["facility_id"] is None
        assert shell["start_at"] is None
        assert shell["end_at"] is None
    pairings = {(g["home_team_id"], g["away_team_id"]) for g in games}
    # Seeds: Alpha 12pts #1, Gamma 3pts #2; Delta and Echo tied at 0 points
    # with no head-to-head, broken by sportsmanship 4.00 (Echo #3) over
    # 3.00 (Delta #4).
    assert pairings == {
        (a["id"], d["id"]),   # seed 1 home vs seed 4 away
        (c["id"], e["id"]),   # seed 2 home vs seed 3 away
    }


def test_playoff_tie_rejected_and_auto_completion():
    """PRD §3.4: "One caveat: on a playoff game (any `bracket_round` other
    than `REGULAR`), a matching report with equal scores is rejected with
    `ERR_TIE_NOT_ALLOWED` — playoff games cannot end tied."
    PRD §3.5: "When a `CHAMPIONSHIP` game resolves such that every division
    bracket produced at playoff launch now has its championship in `FINAL` or
    `FORFEITED`, the league automatically moves `PLAYOFFS → COMPLETED`, and
    every team still `ACTIVE` or `SUSPENDED` moves to `COMPLETED`."

    Design: Corner/state_machines/playoff_tie_rejected_and_auto_completion
    """
    ctx = playoff_championship_context()
    shell = ctx["championship"]
    assert shell["status"] == "RESCHEDULE_REQUIRED"
    assert shell["start_at"] is None and shell["facility_id"] is None
    # Seed 1 (Alpha, 3 points vs 0) hosts the championship.
    moved = validate_success(api_client.reschedule_game(
        shell["id"],
        {"start_at": "2026-09-10T18:00:00Z",
         "end_at": "2026-09-10T19:00:00Z",
         "facility_id": ctx["facility"]["id"]},
        COORDINATOR,
    ))
    assert moved["status"] == "SCHEDULED"
    assert moved["home_team_id"] == ctx["teams"][0]["id"]

    set_clock("2026-09-10T19:30:00Z")
    validate_success(api_client.submit_score_report(
        shell["id"], create_score_report_payload("HOME", 1, 1, 5),
        make_member_headers(ctx["captains"][0]["id"]),
    ), 201)
    resp = api_client.submit_score_report(
        shell["id"], create_score_report_payload("AWAY", 1, 1, 4),
        make_member_headers(ctx["captains"][1]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TIE_NOT_ALLOWED)
    game = validate_success(api_client.get_game(shell["id"], REC_ADMIN))
    assert game["status"] == "PLAYED_PENDING_CONFIRM"

    final = finalize_game(shell["id"], 2, 1, 4, 5, 60)
    assert final["status"] == "FINAL"
    league = validate_success(api_client.get_league(
        ctx["league"]["id"], REC_ADMIN))
    assert league["status"] == "COMPLETED"
    team_a = validate_success(api_client.get_team(
        ctx["teams"][0]["id"], REC_ADMIN))
    assert team_a["status"] == "COMPLETED"


def test_error_no_eligible_teams():
    """PRD §3.5: "Eligibility is computed over the league's `ACTIVE` teams: a
    team is eligible when its status is `ACTIVE`, its `sportsmanship_rating`
    — with null treated as 0.00 — is at least 3.00 (a rating of exactly 3.00
    is eligible), and its `forfeit_count` is at most 1 (exactly 1 forfeit is
    eligible). If fewer than 2 teams league-wide are eligible, the launch
    fails with `ERR_NO_ELIGIBLE_TEAMS`."

    Design: Corner/errors/error_no_eligible_teams
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_context(num_teams=2)
    resp = api_client.start_playoffs(ctx["league"]["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_TEAMS)


def test_error_official_cert_too_low_on_playoff():
    """PRD §3.6: "The target must be an `OFFICIAL` (otherwise
    `ERR_STAFF_NOT_OFFICIAL`, HTTP 422). For a `SEMIFINAL` or `CHAMPIONSHIP`
    game the official's `certification_level` must be at least 2 (otherwise
    `ERR_OFFICIAL_CERT_TOO_LOW`); regular-season games require only level 1 or
    better."
    PRD §3.6: "Its `provisional_pay_cents` is estimated at creation: the
    game's `duration_minutes` multiplied by the official's
    `base_hourly_rate_cents` and by a certification multiplier — 1.0 at level
    1, 1.25 at level 2, 1.5 at level 3 — divided by 60, rounded half-up to
    whole cents."

    Design: Corner/errors/error_official_cert_too_low_on_playoff
    """
    ctx = playoff_championship_context()
    moved = validate_success(api_client.reschedule_game(
        ctx["championship"]["id"],
        {"start_at": "2026-09-10T18:00:00Z",
         "end_at": "2026-09-10T19:00:00Z",
         "facility_id": ctx["facility"]["id"]},
        COORDINATOR,
    ))
    official_low = create_official(rate=2000, cert=1, name="Ref Low")
    official_high = create_official(rate=2000, cert=3, name="Ref Hi")
    resp = api_client.create_officiating_assignment(
        moved["id"], {"staff_id": official_low["id"]}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_OFFICIAL_CERT_TOO_LOW)
    data = validate_success(api_client.create_officiating_assignment(
        moved["id"], {"staff_id": official_high["id"]}, COORDINATOR), 201)
    assert data["provisional_pay_cents"] == 3000  # 60 * 2000 * 1.5 / 60
