"""League lifecycle preconditions and capacity gates (PRD §3.2, §3.3, §3.5)."""
from test_helpers import (
    COORDINATOR,
    REC_ADMIN,
    ApiErrorId,
    api_client,
    close_league,
    create_eligible_member,
    create_league,
    create_member,
    create_team,
    make_member_headers,
    open_league_context,
    place_team,
    register_teams,
    schedule_game,
    scheduling_context,
    season_context,
    set_clock,
    validate_error,
    validate_success,
)


def test_league_open_registration_requires_divisions():
    """PRD §3.2: "A `LeagueCoordinator` opens registration, moving the league
    `DRAFT → REGISTRATION_OPEN`; this requires the `divisions` array to be
    non-empty (otherwise `ERR_LEAGUE_NOT_READY_FOR_SEASON`) and the
    registration/season date chain above to hold (otherwise
    `ERR_VALIDATION`)."

    Design: Corner/state_machines/league_open_registration_requires_divisions
    """
    league = create_league(name="NoDiv", sport="SOCCER", divisions=[])
    resp = api_client.open_registration(league["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_LEAGUE_NOT_READY_FOR_SEASON)
    league_after = validate_success(api_client.get_league(
        league["id"], REC_ADMIN))
    assert league_after["status"] == "DRAFT"


def test_league_close_registration_too_few_teams():
    """PRD §3.3: "Once registration closes, the coordinator closes
    registration, moving the league `REGISTRATION_OPEN → SCHEDULING`; this
    requires at least `min_teams` teams in `REGISTERED` or `PLACED` status
    (otherwise `ERR_TOO_FEW_TEAMS`)."

    Design: Corner/state_machines/league_close_registration_too_few_teams
    """
    ctx = open_league_context()
    captain = create_member("ca@x.edu", full_name="Cap A")
    create_team(ctx["league"]["id"], "Alpha", captain["id"])
    resp = api_client.close_registration(ctx["league"]["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_TOO_FEW_TEAMS)
    league_after = validate_success(api_client.get_league(
        ctx["league"]["id"], REC_ADMIN))
    assert league_after["status"] == "REGISTRATION_OPEN"


def test_league_start_season_requires_placement():
    """PRD §3.3: "Starting the season (`SCHEDULING → IN_SEASON`) requires at
    least `min_teams` teams in `REGISTERED` or `PLACED` (otherwise
    `ERR_TOO_FEW_TEAMS`), every such team to have been placed — a lingering
    `REGISTERED` team without a division fails with
    `ERR_LEAGUE_NOT_READY_FOR_SEASON` — and every `PLACED` team to have
    `active_roster_count` at least `roster_min` (likewise
    `ERR_LEAGUE_NOT_READY_FOR_SEASON`)."

    Design: Corner/state_machines/league_start_season_requires_placement
    """
    ctx = scheduling_context(num_teams=2, place=False)
    # Place only the first team; the second lingers REGISTERED.
    place_team(ctx["teams"][0]["id"], "A")
    resp = api_client.start_season(ctx["league"]["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_LEAGUE_NOT_READY_FOR_SEASON)
    league_after = validate_success(api_client.get_league(
        ctx["league"]["id"], REC_ADMIN))
    assert league_after["status"] == "SCHEDULING"


def test_league_start_playoffs_blocked_by_unfinished_game():
    """PRD §3.5: "This is refused while any game of the league is still
    `SCHEDULED`, `RESCHEDULE_REQUIRED`, `PLAYED_PENDING_CONFIRM`, or
    `DISPUTED` (`ERR_PLAYOFFS_NOT_READY`)."

    Design: Corner/state_machines/league_start_playoffs_blocked_by_unfinished_game
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_context(num_teams=2)
    schedule_game(ctx["league"]["id"], ctx["teams"][0]["id"],
                  ctx["teams"][1]["id"], ctx["facility"]["id"],
                  "2026-09-08T18:00:00Z", "2026-09-08T19:30:00Z")
    resp = api_client.start_playoffs(ctx["league"]["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_PLAYOFFS_NOT_READY)
    league_after = validate_success(api_client.get_league(
        ctx["league"]["id"], REC_ADMIN))
    assert league_after["status"] == "IN_SEASON"


def test_error_league_full_on_third_team():
    """PRD §3.2: "Team creation is refused when the league is not
    `REGISTRATION_OPEN` (`ERR_LEAGUE_NOT_ACCEPTING_REGISTRATIONS`), when the
    captain already captains a non-`WITHDRAWN` team in the same league
    (`ERR_TEAM_ALREADY_IN_LEAGUE`), or when adding the team would exceed
    `team_capacity` (`ERR_LEAGUE_FULL`)."

    Design: Corner/errors/error_league_full_on_third_team
    """
    ctx = open_league_context(team_capacity=2, min_teams=2, roster_max=2)
    teams, _ = register_teams(ctx["league"]["id"], 2, add_captain_entry=False)
    third_captain = create_member("cc@x.edu", full_name="Cap C")
    resp = api_client.create_team(
        {"league_id": ctx["league"]["id"], "name": "Gamma",
         "captain_member_id": third_captain["id"], "skill_rating": 5},
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_LEAGUE_FULL)


def test_error_team_already_in_league():
    """PRD §3.2: "Team creation is refused when the league is not
    `REGISTRATION_OPEN` (`ERR_LEAGUE_NOT_ACCEPTING_REGISTRATIONS`), when the
    captain already captains a non-`WITHDRAWN` team in the same league
    (`ERR_TEAM_ALREADY_IN_LEAGUE`), or when adding the team would exceed
    `team_capacity` (`ERR_LEAGUE_FULL`)."

    Design: Corner/errors/error_team_already_in_league
    """
    ctx = open_league_context()
    captain = create_member("ca@x.edu", full_name="Cap A")
    create_team(ctx["league"]["id"], "Alpha", captain["id"])
    resp = api_client.create_team(
        {"league_id": ctx["league"]["id"], "name": "Alpha II",
         "captain_member_id": captain["id"], "skill_rating": 5},
        COORDINATOR,
    )
    validate_error(resp, ApiErrorId.ERR_TEAM_ALREADY_IN_LEAGUE)


def test_error_registration_after_close():
    """PRD §3.2: "While the league is `REGISTRATION_OPEN` and the team is
    `REGISTERED` or `PLACED`, the team's captain may add players, supplying a
    `member_id`."
    PRD §2.8: "State preconditions (`ERR_INVALID_STATE`, `ERR_MEMBER_SUSPENDED`,
    `ERR_LEAGUE_NOT_ACCEPTING_REGISTRATIONS`, `ERR_GAME_NOT_REPORTABLE`):
    evaluated path-scope first, then body-referenced entities — the league
    status gate, then team status, then member status, then the target
    resource's own transition legality."

    Design: Corner/errors/error_registration_after_close
    """
    ctx = open_league_context()
    teams, _ = register_teams(ctx["league"]["id"], 2, add_captain_entry=False)
    close_league(ctx["league"]["id"])
    player = create_eligible_member("pp@x.edu", full_name="Pla P")
    resp = api_client.add_roster_entry(
        teams[0]["id"], {"member_id": player["id"]},
        make_member_headers(teams[0]["captain_member_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_LEAGUE_NOT_ACCEPTING_REGISTRATIONS)
