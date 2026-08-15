"""Team counters, roster rules, division placement, and the free-agent
selector (PRD §3.2, §3.3)."""
from test_helpers import (
    COORDINATOR,
    REC_ADMIN,
    ApiErrorId,
    api_client,
    close_league,
    create_eligible_member,
    create_member,
    create_team,
    make_member_headers,
    open_league_context,
    place_team,
    register_teams,
    set_clock,
    start_season,
    validate_error,
    validate_success,
)


def test_team_computed_counters_after_roster_adds():
    """PRD §3.2: "each `Team` is created with `league_id`, `name`,
    `captain_member_id`, and a self-assessed `skill_rating` from 1 to 10, and
    begins in `REGISTERED` status with `division_name` null and all counters
    (`wins`, `losses`, `ties`, `points`, `forfeit_count`,
    `sportsmanship_points_total`, `sportsmanship_rating_count`,
    `active_roster_count`) at zero."
    PRD §3.2: "A successful add creates an `ACTIVE` roster entry — `CAPTAIN`
    if the member is the team's captain, else `PLAYER` — and increments the
    team's `active_roster_count`."
    PRD §3.4: "while a team has received no ratings, the rating is null and
    is treated as 0.00 for playoff eligibility."

    Design: Corner/entities/team_computed_counters_after_roster_adds
    """
    ctx = open_league_context()
    captain = create_eligible_member("ca@x.edu", full_name="Cap A")
    team = create_team(ctx["league"]["id"], "Alpha", captain["id"])
    assert team["status"] == "REGISTERED"
    assert team["division_name"] is None
    assert team["active_roster_count"] == 0
    assert team["points"] == 0
    assert team["forfeit_count"] == 0
    assert team["sportsmanship_rating"] is None

    entry = validate_success(api_client.add_roster_entry(
        team["id"], {"member_id": captain["id"]},
        make_member_headers(captain["id"]),
    ), 201)
    assert entry["role"] == "CAPTAIN"
    assert entry["status"] == "ACTIVE"
    team_after = validate_success(api_client.get_team(team["id"], REC_ADMIN))
    assert team_after["active_roster_count"] == 1


def test_roster_remove_captain_returns_error():
    """PRD §3.2: "The captain's own entry can never be removed — any attempt
    is rejected with `ERR_CAPTAIN_REMOVAL_FORBIDDEN` — and removals against a
    locked roster or a non-`ACTIVE` entry are `ERR_INVALID_STATE`."

    Design: Corner/state_machines/roster_remove_captain_returns_error
    """
    ctx = open_league_context()
    captain = create_eligible_member("ca@x.edu", full_name="Cap A")
    team = create_team(ctx["league"]["id"], "Alpha", captain["id"])
    entry = validate_success(api_client.add_roster_entry(
        team["id"], {"member_id": captain["id"]},
        make_member_headers(captain["id"]),
    ), 201)
    # Even the coordinator cannot remove the captain's entry.
    resp = api_client.remove_roster_entry(entry["id"], COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_CAPTAIN_REMOVAL_FORBIDDEN)
    entry_after = validate_success(api_client.get_roster_entry(
        entry["id"], REC_ADMIN))
    assert entry_after["status"] == "ACTIVE"
    team_after = validate_success(api_client.get_team(team["id"], REC_ADMIN))
    assert team_after["active_roster_count"] == 1


def test_roster_remove_after_lock_returns_invalid_state():
    """PRD §3.3: "On success, every `PLACED` team becomes `ACTIVE` and rosters
    lock: roster additions and removals are rejected while a team is `ACTIVE`
    or `SUSPENDED`."
    PRD §3.2: "The captain's own entry can never be removed — any attempt is
    rejected with `ERR_CAPTAIN_REMOVAL_FORBIDDEN` — and removals against a
    locked roster or a non-`ACTIVE` entry are `ERR_INVALID_STATE`."

    Design: Corner/state_machines/roster_remove_after_lock_returns_invalid_state
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = open_league_context()
    captain_a = create_eligible_member("ca@x.edu", full_name="Cap A")
    player = create_eligible_member("pp@x.edu", full_name="Pla P")
    team_a = create_team(ctx["league"]["id"], "Alpha", captain_a["id"])
    entry_p = validate_success(api_client.add_roster_entry(
        team_a["id"], {"member_id": captain_a["id"]},
        make_member_headers(captain_a["id"]),
    ), 201)
    entry_p = validate_success(api_client.add_roster_entry(
        team_a["id"], {"member_id": player["id"]},
        make_member_headers(captain_a["id"]),
    ), 201)
    captain_b = create_eligible_member("cb@x.edu", full_name="Cap B")
    team_b = create_team(ctx["league"]["id"], "Beta", captain_b["id"])
    validate_success(api_client.add_roster_entry(
        team_b["id"], {"member_id": captain_b["id"]},
        make_member_headers(captain_b["id"]),
    ), 201)
    close_league(ctx["league"]["id"])
    place_team(team_a["id"], "A")
    place_team(team_b["id"], "A")
    start_season(ctx["league"]["id"])

    resp = api_client.remove_roster_entry(
        entry_p["id"], make_member_headers(captain_a["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    entry_after = validate_success(api_client.get_roster_entry(
        entry_p["id"], REC_ADMIN))
    assert entry_after["status"] == "ACTIVE"


def test_error_member_already_in_league():
    """PRD §3.2: "The added member must clear the eligibility gates of §2.9
    (suspension, waiver, membership), must not already hold an `ACTIVE` roster
    entry on any team of the same league (`ERR_MEMBER_ALREADY_IN_LEAGUE`), and
    the add must not push the team's `active_roster_count` beyond the league's
    `roster_max` (`ERR_ROSTER_FULL`)."

    Design: Corner/errors/error_member_already_in_league
    """
    ctx = open_league_context()
    teams, _ = register_teams(ctx["league"]["id"], 2)
    member_x = create_eligible_member("mx@x.edu", full_name="Mem X")
    validate_success(api_client.add_roster_entry(
        teams[0]["id"], {"member_id": member_x["id"]},
        make_member_headers(teams[0]["captain_member_id"]),
    ), 201)
    resp = api_client.add_roster_entry(
        teams[1]["id"], {"member_id": member_x["id"]},
        make_member_headers(teams[1]["captain_member_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_MEMBER_ALREADY_IN_LEAGUE)


def test_error_roster_full():
    """PRD §3.2: "The added member must clear the eligibility gates of §2.9
    (suspension, waiver, membership), must not already hold an `ACTIVE` roster
    entry on any team of the same league (`ERR_MEMBER_ALREADY_IN_LEAGUE`), and
    the add must not push the team's `active_roster_count` beyond the league's
    `roster_max` (`ERR_ROSTER_FULL`)."

    Design: Corner/errors/error_roster_full
    """
    ctx = open_league_context(roster_min=1, roster_max=1)
    teams, _ = register_teams(ctx["league"]["id"], 1)
    player = create_eligible_member("pp@x.edu", full_name="Pla P")
    resp = api_client.add_roster_entry(
        teams[0]["id"], {"member_id": player["id"]},
        make_member_headers(teams[0]["captain_member_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ROSTER_FULL)


def test_error_free_agent_double_pool():
    """PRD §3.2: "the league must be `REGISTRATION_OPEN` (otherwise
    `ERR_LEAGUE_NOT_ACCEPTING_REGISTRATIONS`), the member must clear the
    eligibility gates, must not already hold an `ACTIVE` roster entry in the
    league (`ERR_MEMBER_ALREADY_IN_LEAGUE`), and must not already have a
    `POOLED` entry in this league (`ERR_ALREADY_IN_POOL`)."

    Design: Corner/errors/error_free_agent_double_pool
    """
    ctx = open_league_context()
    agent = create_eligible_member("fa@x.edu", full_name="Fa A")
    validate_success(api_client.register_free_agent(
        ctx["league"]["id"], {"member_id": agent["id"]},
        make_member_headers(agent["id"]),
    ), 201)
    resp = api_client.register_free_agent(
        ctx["league"]["id"], {"member_id": agent["id"]},
        make_member_headers(agent["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ALREADY_IN_POOL)


def test_free_agent_selector_fewest_roster_then_empty_pool():
    """PRD §3.2: "A coordinator may later place a `POOLED` free agent: the
    selector considers teams of the league in `REGISTERED` or `PLACED` status
    whose `active_roster_count` is below `roster_max`; if the pool entry's
    `preferred_division_name` is set, only teams whose `division_name` equals
    it remain candidates — strictly, with no fallback to other divisions;
    candidates are ranked by `active_roster_count` ascending with ties broken
    by earlier team `created_at`; the head receives a new `ACTIVE` `PLAYER`
    roster entry, the pool entry becomes `PLACED`, and the team's
    `active_roster_count` increments. An empty candidate set is rejected with
    `ERR_NO_TEAM_AVAILABLE`."

    Design: Corner/calculations/free_agent_selector_fewest_roster_then_empty_pool
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = open_league_context()
    # Alpha carries captain + one player (roster 2); Beta carries only its
    # captain (roster 1).
    captain_a = create_eligible_member("ca@x.edu", full_name="Cap A")
    player = create_eligible_member("pp@x.edu", full_name="Pla P")
    team_a = create_team(ctx["league"]["id"], "Alpha", captain_a["id"])
    validate_success(api_client.add_roster_entry(
        team_a["id"], {"member_id": captain_a["id"]},
        make_member_headers(captain_a["id"])), 201)
    validate_success(api_client.add_roster_entry(
        team_a["id"], {"member_id": player["id"]},
        make_member_headers(captain_a["id"])), 201)
    captain_b = create_eligible_member("cb@x.edu", full_name="Cap B")
    team_b = create_team(ctx["league"]["id"], "Beta", captain_b["id"])
    validate_success(api_client.add_roster_entry(
        team_b["id"], {"member_id": captain_b["id"]},
        make_member_headers(captain_b["id"])), 201)
    agent_1 = create_eligible_member("f1@x.edu", full_name="Fa One")
    agent_2 = create_eligible_member("f2@x.edu", full_name="Fa Two")
    validate_success(api_client.register_free_agent(
        ctx["league"]["id"], {"member_id": agent_1["id"]},
        make_member_headers(agent_1["id"])), 201)
    validate_success(api_client.register_free_agent(
        ctx["league"]["id"],
        {"member_id": agent_2["id"], "preferred_division_name": "A"},
        make_member_headers(agent_2["id"])), 201)

    # No preference: fewest ACTIVE roster entries wins -> Beta (1 < 2).
    placed = validate_success(api_client.place_free_agent(
        ctx["league"]["id"], {"member_id": agent_1["id"]}, COORDINATOR))
    assert placed["team_id"] == team_b["id"]
    assert placed["role"] == "PLAYER"
    assert placed["status"] == "ACTIVE"

    # Strict preference for "A" while no team is placed in "A" yet (both are
    # REGISTERED with division_name null): empty candidate set, no fallback.
    resp = api_client.place_free_agent(
        ctx["league"]["id"], {"member_id": agent_2["id"]}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_NO_TEAM_AVAILABLE)
    league_after = validate_success(api_client.get_league(
        ctx["league"]["id"], REC_ADMIN))
    pool = {e["member_id"]: e["status"] for e in
            league_after["free_agent_pool"]}
    assert pool[agent_1["id"]] == "PLACED"
    assert pool[agent_2["id"]] == "POOLED"


def test_division_skill_bounds_inclusive():
    """PRD §3.3: "During `SCHEDULING`, the coordinator places each
    `REGISTERED` team into a division: the league must be `SCHEDULING`
    (otherwise `ERR_INVALID_STATE`), the named division must exist in the
    league's `divisions` (otherwise `ERR_DIVISION_NOT_FOUND`), the team's
    `skill_rating` must lie within the division's `skill_min`–`skill_max`
    bounds, both bounds inclusive (otherwise `ERR_DIVISION_SKILL_MISMATCH`,
    which is checked *before* capacity), and the division must currently hold
    fewer teams than its `capacity` (otherwise `ERR_DIVISION_FULL`)."

    Design: Corner/calculations/division_skill_bounds_inclusive
    """
    ctx = open_league_context(divisions=[
        {"name": "Pro", "capacity": 4, "skill_min": 3, "skill_max": 5},
    ])
    captain_a = create_member("ca@x.edu", full_name="Cap A")
    captain_b = create_member("cb@x.edu", full_name="Cap B")
    team_a = create_team(ctx["league"]["id"], "Alpha", captain_a["id"],
                         skill_rating=5)
    team_b = create_team(ctx["league"]["id"], "Beta", captain_b["id"],
                         skill_rating=6)
    close_league(ctx["league"]["id"])
    placed = place_team(team_a["id"], "Pro")
    assert placed["status"] == "PLACED", (
        "skill_rating == skill_max must place cleanly (inclusive bound)"
    )
    resp = api_client.place_division(
        team_b["id"], {"division_name": "Pro"}, COORDINATOR)
    validate_error(resp, ApiErrorId.ERR_DIVISION_SKILL_MISMATCH)
    team_b_after = validate_success(api_client.get_team(
        team_b["id"], REC_ADMIN))
    assert team_b_after["status"] == "REGISTERED"


def test_error_division_not_found_and_full():
    """PRD §3.3: "During `SCHEDULING`, the coordinator places each
    `REGISTERED` team into a division: the league must be `SCHEDULING`
    (otherwise `ERR_INVALID_STATE`), the named division must exist in the
    league's `divisions` (otherwise `ERR_DIVISION_NOT_FOUND`), the team's
    `skill_rating` must lie within the division's `skill_min`–`skill_max`
    bounds, both bounds inclusive (otherwise `ERR_DIVISION_SKILL_MISMATCH`,
    which is checked *before* capacity), and the division must currently hold
    fewer teams than its `capacity` (otherwise `ERR_DIVISION_FULL`)."

    Design: Corner/errors/error_division_not_found_and_full
    """
    ctx = open_league_context(divisions=[
        {"name": "A", "capacity": 1, "skill_min": 1, "skill_max": 10},
    ])
    captain_a = create_member("ca@x.edu", full_name="Cap A")
    captain_b = create_member("cb@x.edu", full_name="Cap B")
    team_a = create_team(ctx["league"]["id"], "Alpha", captain_a["id"])
    team_b = create_team(ctx["league"]["id"], "Beta", captain_b["id"])
    close_league(ctx["league"]["id"])
    place_team(team_a["id"], "A")

    resp_unknown = api_client.place_division(
        team_b["id"], {"division_name": "ZZ"}, COORDINATOR)
    validate_error(resp_unknown, ApiErrorId.ERR_DIVISION_NOT_FOUND)
    resp_full = api_client.place_division(
        team_b["id"], {"division_name": "A"}, COORDINATOR)
    validate_error(resp_full, ApiErrorId.ERR_DIVISION_FULL)
    team_b_after = validate_success(api_client.get_team(
        team_b["id"], REC_ADMIN))
    assert team_b_after["status"] == "REGISTERED"


def test_non_captain_cannot_add_roster():
    """PRD §2.8: "**Authorization and ownership** (`ERR_FORBIDDEN`): role
    permitted for the endpoint; entity-backed ownership checks (a `Member`
    caller's `X-User-ID` must equal the path or body `member_id`; roster and
    score-report callers must be the team's captain; registration, checkout,
    locker, fine-payment, waiver, and membership actions are self-service; a
    `Staff` caller must be the assignment's official or the class's
    instructor)."

    Design: Corner/validations/non_captain_cannot_add_roster
    """
    ctx = open_league_context()
    captain = create_member("ca@x.edu", full_name="Cap A")
    member_x = create_eligible_member("mx@x.edu", full_name="Mem X")
    team = create_team(ctx["league"]["id"], "Alpha", captain["id"])
    # MX is eligible but is not the team's captain.
    resp = api_client.add_roster_entry(
        team["id"], {"member_id": member_x["id"]},
        make_member_headers(member_x["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
