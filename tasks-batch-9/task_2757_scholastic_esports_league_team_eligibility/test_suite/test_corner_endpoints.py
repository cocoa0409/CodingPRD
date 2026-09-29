"""Breadth tests for the ``endpoints`` design section.

These tests exercise the transport surface rather than the domain: the §2.2
envelope, the §2.3 pagination contract, the §2.10 reverse-lookup filters, the
"action endpoints answer 200 with the whole updated entity" rule of §4, and the
one decision endpoint whose two branches require and forbid the same field.
"""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    INTEGRITY_OFFICER_ID,
    INTEGRITY_OFFICER_ID_2,
    integrity_officer_headers,
    league_admin_headers,
    make_athletic_director_headers,
    make_coach_headers,
    make_district_admin_headers,
    recruiter_headers,
)

MISSING_ID = "00000000-0000-4000-8000-000000000000"


def _envelope(response):
    """The whole parsed body, for the envelope-shape assertions of §2.2."""
    return response.json()


def _ids(rows):
    return [row["id"] for row in rows]


# ==========================================================================
# Instance: title_collection_reads_honour_the_envelope_pagination_contract_and_
#           path_existence
# ==========================================================================
def _build_three_titles(api):
    """Two POOL-A titles at the default T rating and one M-rated POOL-B title, so
    every declared filter on the catalogue has a row it must exclude."""
    titles = []
    for overrides in (
        {"server_pool_id": "POOL-A"},
        {"server_pool_id": "POOL-A"},
        {"server_pool_id": "POOL-B", "age_rating": "M"},
    ):
        response = api.create_title(F.title_payload(**overrides), league_admin_headers())
        validate_success(response, 201)
        titles.append(A.data_of(response, 201))
    return titles


def test_the_title_catalogue_honours_the_envelope_and_pagination_contract(api):
    """Defaults on create, then the envelope, the page window, the filters, the
    two rejected limits and the entity-specific 404.

    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."  PRD §2.3: "`limit` caps the number of
    records returned; it defaults to 10, its minimum accepted value is 1 and its
    maximum accepted value is 100 ... A `limit` outside the range 1 through 100,
    or a negative `offset`, is a malformed request and is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."  And: "`total_count` reports the size of
    the full filtered result set before the limit and offset are applied, and
    `has_more` is true exactly when records remain beyond the returned page."
    PRD §2.10: "Lists additionally filter on the natural status and
    classification fields — ... a title's `age_rating` or `server_pool_id`".
    PRD §2.7 rung 4: "Every identifier embedded in the URL path resolves to a
    live record ... drawn from ... `ERR_TITLE_NOT_FOUND` ... each HTTP 404."

    Design: Corner/endpoints/title_collection_reads_honour_the_envelope_pagination_contract_and_path_existence
    """
    first, second, third = _build_three_titles(api)
    for title in (first, second, third):
        assert title["version"] == 1
        assert title["created_at"] == title["updated_at"]
        assert title["min_player_age"] == 13
        assert title["server_pool_capacity"] == 1
        assert title["match_duration_minutes"] == 60
    assert first["age_rating"] == "T"
    assert second["age_rating"] == "T"
    assert third["age_rating"] == "M"
    assert first["server_pool_id"] == "POOL-A"
    assert third["server_pool_id"] == "POOL-B"

    coach_headers = make_coach_headers("coach-viewer")
    item = api.get_title(first["id"], coach_headers)
    validate_success(item)
    item_body = _envelope(item)
    assert item_body["response_type"] == "object"
    assert item_body["data"]["id"] == first["id"]
    assert item_body["meta"]["api_request_id"].startswith("req_")
    A.assert_three_digit_millis(item_body["meta"]["api_request_timestamp"])

    listing = api.list_titles(None, coach_headers)
    rows, meta = validate_paginated(listing)
    assert _envelope(listing)["response_type"] == "array"
    assert len(rows) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api.list_titles({"limit": 1, "offset": 0}, league_admin_headers())
    )
    assert len(rows) == 1
    assert meta["limit"] == 1
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    rows, meta = validate_paginated(
        api.list_titles({"limit": 1, "offset": 2}, league_admin_headers())
    )
    assert len(rows) == 1
    assert meta["offset"] == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api.list_titles({"offset": 99}, league_admin_headers())
    )
    assert rows == []
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    rows, meta = validate_paginated(
        api.list_titles({"age_rating": "M"}, league_admin_headers())
    )
    assert _ids(rows) == [third["id"]]
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api.list_titles({"server_pool_id": "POOL-A"}, league_admin_headers())
    )
    assert sorted(_ids(rows)) == sorted([first["id"], second["id"]])
    assert meta["total_count"] == 2

    validate_error(
        api.list_titles({"limit": 0}, league_admin_headers()),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api.list_titles({"limit": 101}, league_admin_headers()),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    validate_error(
        api.get_title(MISSING_ID, league_admin_headers()),
        ApiErrorId.ERR_TITLE_NOT_FOUND.value,
        404,
    )


# ==========================================================================
# Instance: action_endpoints_return_the_whole_updated_entity_and_optional_notes_
#           may_be_omitted
# ==========================================================================
def _build_team_with_one_starter_slot(api):
    """A DRAFT team holding one unverified STARTER slot, and the certified coach
    who owns it (created 1, certified 2, so the next certification act is 3)."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_coach(api, school["id"])
    title = fx.make_title(api)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    coach = fx.certify_coach(api, coach)
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])
    student = fx.make_student(api, school["id"])
    slot = fx.add_slot(api, team["id"], student["id"], coach["id"], "STARTER")
    return {
        "school": school,
        "coach": coach,
        "team": team,
        "student": student,
        "slot": slot,
    }


def test_action_endpoints_answer_200_with_the_whole_entity_from_either_role(api):
    """An empty body still fires the declared side effects, and the same action
    behaves identically for both of its authorized roles.

    PRD §4: "Operations that bring a brand-new resource into existence answer
    with HTTP 201 Created; every other successful operation — reads, lists, state
    transitions, action endpoints and the clock control — answers with HTTP 200
    OK."  And: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field" (§2.2).  PRD §3.2: "Suspending sets `certification_status` to
    `SUSPENDED` and leaves the expiry and the certification timestamp where they
    are."  PRD §3.5: "On success `released_at` is stamped from the logical clock,
    `participation_status` becomes `RELEASED`, the team's `starter_slots_used` is
    decremented and its `starter_slots_available` incremented".

    Design: Corner/endpoints/action_endpoints_return_the_whole_updated_entity_and_optional_notes_may_be_omitted
    """
    world = _build_team_with_one_starter_slot(api)
    coach = world["coach"]
    assert coach["version"] == 2
    assert coach["background_check_expires_on"] == "2027-06-30"

    released_response = api.release_roster_slot(
        world["slot"]["id"], {}, make_coach_headers(coach["id"])
    )
    validate_success(released_response)
    released = A.data_of(released_response)
    assert released["id"] == world["slot"]["id"]
    assert released["team_id"] == world["team"]["id"]
    assert released["student_id"] == world["student"]["id"]
    assert released["slot_role"] == "STARTER"
    A.assert_slot_axes(released, participation_status="RELEASED")
    assert released["released_at"] == "2026-08-01T00:00:00.000Z"
    assert released["version"] == 2
    A.assert_common_fields(released)

    freed_team = fx.get_team(api, world["team"]["id"])
    assert freed_team["starter_slots_used"] == 0
    assert freed_team["starter_slots_available"] == 3
    team_version = freed_team["version"]
    student_version = fx.get_student(api, world["student"]["id"])["version"]

    suspend_response = api.certify_coach(
        coach["id"], {"action": "SUSPEND"}, league_admin_headers()
    )
    validate_success(suspend_response)
    suspended = A.data_of(suspend_response)
    assert suspended["certification_status"] == "SUSPENDED"
    assert suspended["version"] == 3
    assert suspended["background_check_expires_on"] == "2027-06-30"
    assert suspended["certified_at"] == "2026-08-01T00:00:00.000Z"
    A.assert_common_fields(suspended)

    recertify_response = api.certify_coach(
        coach["id"],
        {"action": "CERTIFY", "background_check_expires_on": "2028-06-30"},
        make_athletic_director_headers(world["school"]["id"]),
    )
    validate_success(recertify_response)
    recertified = A.data_of(recertify_response)
    assert recertified["certification_status"] == "CERTIFIED"
    assert recertified["background_check_expires_on"] == "2028-06-30"
    assert recertified["version"] == 4

    assert fx.get_coach(api, coach["id"]) == recertified

    assert fx.get_team(api, world["team"]["id"])["version"] == team_version
    assert fx.get_student(api, world["student"]["id"])["version"] == student_version


# ==========================================================================
# Instance: every_fk_reverse_lookup_filter_is_scoped_and_composable
# ==========================================================================
def _build_two_districts_of_everything(api):
    """Two districts, two titles, three approvals with two different outcomes,
    three seasons, two teams and two cases — every filter below has a row it must
    exclude."""
    district_one = fx.make_district(api)
    district_two = fx.make_district(api)
    school_one = fx.make_school(api, district_one["id"])
    school_two = fx.make_school(api, district_two["id"])
    coach_one = fx.make_certified_coach(api, school_one["id"])
    coach_two = fx.make_certified_coach(api, school_two["id"])
    title_one = fx.make_title(api)
    title_two = fx.make_title(api)

    approval_one_one = fx.decide_title_approval(
        api,
        fx.request_title_approval(
            api, district_one["id"], title_one["id"], school_one["id"]
        ),
        "APPROVE",
    )
    approval_one_two = fx.decide_title_approval(
        api,
        fx.request_title_approval(
            api, district_one["id"], title_two["id"], school_one["id"]
        ),
        "DENY",
    )
    approval_two_one = fx.decide_title_approval(
        api,
        fx.request_title_approval(
            api, district_two["id"], title_one["id"], school_two["id"]
        ),
        "APPROVE",
    )

    season_one = fx.make_season(api, title_one["id"])
    season_two = fx.make_season(api, title_one["id"])
    season_three = fx.make_season(api, title_two["id"])

    team_one = fx.make_team(
        api,
        season_one["id"],
        school_one["id"],
        title_one["id"],
        coach_one["id"],
        name="North Alpha",
    )
    team_two = fx.make_team(
        api,
        season_one["id"],
        school_two["id"],
        title_one["id"],
        coach_two["id"],
        name="South Bravo",
    )
    student_one = fx.make_student(api, school_one["id"])
    student_two = fx.make_student(api, school_two["id"])
    fx.add_slot(api, team_one["id"], student_one["id"], coach_one["id"], "STARTER")
    fx.add_slot(api, team_two["id"], student_two["id"], coach_two["id"], "STARTER")

    case_one = fx.open_student_case(
        api, team_one["id"], student_one["id"], case_type="ACCOUNT_SHARING"
    )
    case_two = fx.open_student_case(
        api, team_two["id"], student_two["id"], case_type="SMURFING"
    )
    fx.investigate_case(api, case_two["id"], officer_id=INTEGRITY_OFFICER_ID)

    return {
        "districts": (district_one, district_two),
        "schools": (school_one, school_two),
        "titles": (title_one, title_two),
        "approvals": (approval_one_one, approval_one_two, approval_two_one),
        "seasons": (season_one, season_two, season_three),
        "teams": (team_one, team_two),
        "students": (student_one, student_two),
        "cases": (case_one, case_two),
    }


def test_every_declared_reverse_lookup_narrows_and_ands_with_its_neighbours(api):
    """Each foreign key is independently reverse-reachable, filters AND, and an
    unsatisfiable pair returns an empty page rather than the whole table.

    PRD §2.10: "Parentage is carried by foreign-key fields inside request bodies,
    and each such field is offered back as an optional list filter so that the
    children of a parent remain discoverable — ... title approvals by
    `district_id`, `title_id` or `requested_by_school_id`; seasons by `title_id`;
    ... and fair-play cases by `team_id`, `subject_student_id` or
    `subject_match_id`. Lists additionally filter on the natural status and
    classification fields — ... a school's or season's or team's or approval's or
    case's `status`, ... and a case's `case_type`."  PRD §2.3: "`total_count`
    reports the size of the full filtered result set before the limit and offset
    are applied".

    Design: Corner/endpoints/every_fk_reverse_lookup_filter_is_scoped_and_composable
    """
    world = _build_two_districts_of_everything(api)
    district_one, district_two = world["districts"]
    _school_one, school_two = world["schools"]
    title_one, title_two = world["titles"]
    approval_one_one, approval_one_two, approval_two_one = world["approvals"]
    season_one, season_two, season_three = world["seasons"]
    team_one, _team_two = world["teams"]
    _student_one, student_two = world["students"]
    case_one, case_two = world["cases"]
    admin = league_admin_headers()

    rows, meta = validate_paginated(
        api.list_title_approvals({"district_id": district_one["id"]}, admin)
    )
    assert sorted(_ids(rows)) == sorted(
        [approval_one_one["id"], approval_one_two["id"]]
    )
    assert approval_two_one["id"] not in _ids(rows)
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api.list_title_approvals({"title_id": title_one["id"]}, admin)
    )
    assert sorted(_ids(rows)) == sorted(
        [approval_one_one["id"], approval_two_one["id"]]
    )
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api.list_title_approvals(
            {"district_id": district_one["id"], "status": "APPROVED"}, admin
        )
    )
    assert _ids(rows) == [approval_one_one["id"]]
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api.list_title_approvals(
            {"requested_by_school_id": school_two["id"]},
            make_district_admin_headers(district_two["id"]),
        )
    )
    assert _ids(rows) == [approval_two_one["id"]]
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api.list_seasons({"title_id": title_one["id"]}, recruiter_headers())
    )
    assert sorted(_ids(rows)) == sorted([season_one["id"], season_two["id"]])
    assert meta["total_count"] == 2

    rows, meta = validate_paginated(
        api.list_seasons({"title_id": title_two["id"], "status": "DRAFT"}, admin)
    )
    assert _ids(rows) == [season_three["id"]]
    assert rows[0]["status"] == "DRAFT"

    rows, meta = validate_paginated(
        api.list_fair_play_cases({"team_id": team_one["id"]}, admin)
    )
    assert _ids(rows) == [case_one["id"]]
    assert rows[0]["status"] == "REPORTED"
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api.list_fair_play_cases({"subject_student_id": student_two["id"]}, admin)
    )
    assert _ids(rows) == [case_two["id"]]
    assert meta["total_count"] == 1

    rows, meta = validate_paginated(
        api.list_fair_play_cases(
            {"case_type": "SMURFING"},
            integrity_officer_headers(INTEGRITY_OFFICER_ID),
        )
    )
    assert _ids(rows) == [case_two["id"]]
    assert rows[0]["case_type"] == "SMURFING"
    assert rows[0]["status"] == "INVESTIGATING"

    unsatisfiable = api.list_fair_play_cases(
        {"team_id": team_one["id"], "status": "INVESTIGATING"}, admin
    )
    rows, meta = validate_paginated(unsatisfiable)
    assert rows == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert meta["limit"] == 10
    assert meta["offset"] == 0


# ==========================================================================
# Instance: computed_reads_expose_every_derived_field_without_recomputing_or_
#           mutating
# ==========================================================================
def _build_seeded_season_with_one_forfeit_and_one_pending_match(api):
    """A seeded REGULAR_SEASON carrying two matches on the title's POOL-A: the
    first forfeited by the away side, the second still SCHEDULED."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api, server_pool_id="POOL-A")
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    teams = []
    for name in ("North Alpha", "North Bravo"):
        student = fx.make_student_with_term(api, school["id"], term_gpa=3.500)
        team = fx.make_team(
            api, season["id"], school["id"], title["id"], coach["id"], name=name
        )
        fx.make_active_starter(api, team["id"], coach["id"], student, "STARTER")
        teams.append(team)
    fx.open_registration(api, season["id"])
    teams = [fx.lock_roster(api, fx.register_team(api, team)) for team in teams]
    fx.advance_season(api, season["id"], "ROSTER_LOCKED")
    fx.advance_season(api, season["id"], "REGULAR_SEASON")
    home, away = teams
    first = fx.schedule_match(
        api, season["id"], home["id"], away["id"], "2026-10-01T18:00:00.000Z"
    )
    second = fx.schedule_match(
        api, season["id"], home["id"], away["id"], "2026-10-02T18:00:00.000Z"
    )
    fx.forfeit_match(api, first["id"], away["id"], reason_note="no players available")
    fx.run_seeding(api, season["id"])
    return {
        "coach": coach,
        "season": season,
        "home": home,
        "away": away,
        "first": first,
        "second": second,
    }


def test_computed_reads_serve_the_pinned_derived_fields_and_bump_nothing(api):
    """Every derived Match and Team figure is read back exactly as the last write
    pinned it, from either role, twice, without moving a version.

    PRD §3.7: "`scheduled_end_at` is derived as `scheduled_start_at` plus the
    title's `match_duration_minutes` and is pinned at creation ... The match
    copies the title's `server_pool_id`".  And the forfeit: "the opponent is
    credited 3 `match_points` ... `result_status` becomes `ADJUDICATED`,
    `result_confirmed_at` is stamped from the clock and `dispute_deadline_at` is
    that instant plus the district's `dispute_window_hours`".  PRD §3.9: "Under
    `MATCH_POINT_BASIS` a team's `seed_points` is simply its accumulated
    `match_points`" and "Teams at a `seed_position` at or below the season's
    `playoff_slots` take status `PLAYOFF_SEEDED`".  PRD §2.5: "`version` (integer):
    a counter that increments by exactly one on every mutation of that record."

    Design: Corner/endpoints/computed_reads_expose_every_derived_field_without_recomputing_or_mutating
    """
    world = _build_seeded_season_with_one_forfeit_and_one_pending_match(api)
    admin = league_admin_headers()
    home, away = world["home"], world["away"]

    coach_read = api.get_match(
        world["first"]["id"], make_coach_headers(world["coach"]["id"])
    )
    validate_success(coach_read)
    forfeited = A.data_of(coach_read)
    assert forfeited["scheduled_end_at"] == "2026-10-01T19:00:00.000Z"
    assert forfeited["server_pool_id"] == "POOL-A"
    A.assert_match_state(
        forfeited, play_status="FORFEITED", result_status="ADJUDICATED"
    )
    assert forfeited["forfeiting_team_id"] == away["id"]
    assert forfeited["winner_team_id"] == home["id"]
    assert forfeited["home_points_awarded"] == 3
    assert forfeited["away_points_awarded"] == 0
    assert forfeited["result_confirmed_at"] == "2026-08-01T00:00:00.000Z"
    assert forfeited["dispute_deadline_at"] == "2026-08-03T00:00:00.000Z"
    assert forfeited["home_games_won"] is None
    assert forfeited["away_games_won"] is None

    rows, meta = validate_paginated(
        api.list_matches({"season_id": world["season"]["id"]}, admin)
    )
    assert sorted(_ids(rows)) == sorted([world["first"]["id"], world["second"]["id"]])
    assert meta["total_count"] == 2

    rows, _meta = validate_paginated(
        api.list_matches({"play_status": "SCHEDULED"}, admin)
    )
    assert _ids(rows) == [world["second"]["id"]]
    assert rows[0]["dispute_deadline_at"] is None
    assert rows[0]["home_points_awarded"] == 0

    rows, _meta = validate_paginated(
        api.list_matches({"forfeiting_team_id": away["id"]}, admin)
    )
    assert _ids(rows) == [world["first"]["id"]]

    rows, _meta = validate_paginated(
        api.list_matches(
            {"winner_team_id": home["id"], "result_status": "ADJUDICATED"}, admin
        )
    )
    assert _ids(rows) == [world["first"]["id"]]

    rows, meta = validate_paginated(
        api.list_teams({"season_id": world["season"]["id"]}, recruiter_headers())
    )
    assert meta["total_count"] == 2
    by_id = {row["id"]: row for row in rows}
    winner = by_id[home["id"]]
    loser = by_id[away["id"]]
    assert winner["match_points"] == 3
    assert winner["forfeit_wins"] == 1
    assert winner["wins"] == 0
    A.assert_seed_points(winner["seed_points"], 3.0000)
    assert winner["seed_position"] == 1
    assert winner["seed_stale"] is False
    assert winner["status"] == "PLAYOFF_SEEDED"
    assert loser["match_points"] == 0
    assert loser["forfeits_charged"] == 1
    A.assert_seed_points(loser["seed_points"], 0.0000)
    assert loser["seed_position"] == 2
    assert loser["seed_stale"] is False
    assert loser["status"] == "PLAYOFF_SEEDED"
    for team in (winner, loser):
        assert team["game_differential"] == 0
        A.assert_integrity_score(team["integrity_score"], 100.00)

    season_read = api.get_season(world["season"]["id"], admin)
    validate_success(season_read)
    season = A.data_of(season_read)
    assert season["seeding_state"] == "SEEDED"
    assert season["seeding_basis_applied"] == "MATCH_POINT_BASIS"
    assert season["seed_order"] == [home["id"], away["id"]]
    assert season["registered_team_count"] == 2
    A.assert_match_point_pool(season, 3)

    match_rows, _meta = validate_paginated(
        api.list_matches({"season_id": world["season"]["id"]}, admin)
    )
    awarded = sum(
        row["home_points_awarded"] + row["away_points_awarded"] for row in match_rows
    )
    A.assert_match_point_pool(season, awarded)

    assert A.data_of(api.get_season(world["season"]["id"], admin)) == season

    assert A.data_of(api.get_match(world["first"]["id"], admin)) == forfeited


# ==========================================================================
# Instance: the_decision_endpoints_two_branches_require_and_forbid_the_same_field
# ==========================================================================
def _build_two_investigating_cases_on_one_team(api):
    """One DRAFT team, two unverified slots and two INVESTIGATING cases — one per
    student — both taken by the same investigator."""
    district = fx.make_district(api)
    school = fx.make_school(api, district["id"])
    coach = fx.make_certified_coach(api, school["id"])
    title = fx.make_title(api)
    fx.approve_title_for_district(api, district["id"], title["id"], school["id"])
    season = fx.make_season(api, title["id"])
    team = fx.make_team(api, season["id"], school["id"], title["id"], coach["id"])
    students = [fx.make_student(api, school["id"]) for _ in range(2)]
    slots = [
        fx.add_slot(api, team["id"], student["id"], coach["id"], "STARTER")
        for student in students
    ]
    cases = []
    for student in students:
        case = fx.open_student_case(
            api, team["id"], student["id"], case_type="ACCOUNT_SHARING"
        )
        fx.investigate_case(api, case["id"], officer_id=INTEGRITY_OFFICER_ID)
        cases.append(case)
    return {"team": team, "students": students, "slots": slots, "cases": cases}


def test_the_same_severity_field_is_required_by_one_branch_and_forbidden_by_the_other(
    api,
):
    """Both halves of the discriminated obligation are rejected on shape, the
    DISMISS branch changes nothing, and a dismissal never enters the repeat
    ladder.

    PRD §3.8: "`SUSTAIN` requires a `severity` of `MINOR`, `MAJOR` or `SEVERE`;
    `DISMISS` requires `severity` to be absent. Violating either is
    `ERR_INVALID_REQUEST`."  And: "`DISMISS` moves the case `INVESTIGATING →
    DISMISSED`, writes `decider_user_id` from `X-User-ID`, stamps `decided_at`
    from the logical clock, leaves `sanction_type` at `NONE`, and changes
    **nothing else at all** ... and the dismissed case never enters the penalty
    set."  And: "**Integrity scoring** works on the set of cases charged to a team
    whose status is `SUSTAINED` or `SUSTAINED_FINAL` ... Cases in `DISMISSED` or
    `OVERTURNED` are outside the set entirely. Each case in the set is numbered
    from 1 in that order, and that number is stored as its `repeat_index`."

    Design: Corner/endpoints/the_decision_endpoints_two_branches_require_and_forbid_the_same_field
    """
    world = _build_two_investigating_cases_on_one_team(api)
    first_case, second_case = world["cases"]
    first_student, second_student = world["students"]
    first_slot, second_slot = world["slots"]
    decider = integrity_officer_headers(INTEGRITY_OFFICER_ID_2)

    validate_error(
        api.decide_case(
            first_case["id"],
            {"decision": "SUSTAIN", "decision_note": "no severity supplied"},
            decider,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    assert fx.get_case(api, first_case["id"])["status"] == "INVESTIGATING"

    validate_error(
        api.decide_case(
            first_case["id"],
            {
                "decision": "DISMISS",
                "severity": "MINOR",
                "decision_note": "severity supplied anyway",
            },
            decider,
        ),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )
    untouched = fx.get_case(api, first_case["id"])
    assert untouched["status"] == "INVESTIGATING"
    assert untouched["decider_user_id"] is None
    assert untouched["decided_at"] is None

    dismissed_response = api.decide_case(
        first_case["id"],
        {"decision": "DISMISS", "decision_note": "shared IP was the school lab"},
        decider,
    )
    validate_success(dismissed_response)
    dismissed = A.data_of(dismissed_response)
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["decider_user_id"] == INTEGRITY_OFFICER_ID_2
    assert dismissed["decided_at"] == "2026-08-01T00:00:00.000Z"
    assert dismissed["severity"] is None
    assert dismissed["severity_weight"] == 0
    assert dismissed["repeat_index"] is None
    assert dismissed["applied_penalty"] == 0
    assert dismissed["sanction_type"] == "NONE"

    assert fx.get_student(api, first_student["id"])["fair_play_status"] == "CLEAR"
    A.assert_slot_axes(
        fx.get_slot(api, first_slot["id"]), participation_status="PROSPECTIVE"
    )
    quiet_team = fx.get_team(api, world["team"]["id"])
    A.assert_integrity_score(quiet_team["integrity_score"], 100.00)
    assert quiet_team["status"] == "DRAFT"

    sustained_response = api.decide_case(
        second_case["id"],
        {
            "decision": "SUSTAIN",
            "severity": "MINOR",
            "decision_note": "credential sharing confirmed",
        },
        decider,
    )
    validate_success(sustained_response)
    sustained = A.data_of(sustained_response)
    assert sustained["status"] == "SUSTAINED"
    assert sustained["severity"] == "MINOR"
    assert sustained["severity_weight"] == 10
    assert sustained["repeat_index"] == 1
    A.assert_integrity_score(sustained["applied_penalty"], 10.00)
    assert sustained["sanction_type"] == "STUDENT_SUSPENSION"

    A.assert_integrity_score(
        fx.get_team(api, world["team"]["id"])["integrity_score"], 90.00
    )
    assert fx.get_student(api, second_student["id"])["fair_play_status"] == "SANCTIONED"
    A.assert_slot_axes(
        fx.get_slot(api, second_slot["id"]), participation_status="PROSPECTIVE"
    )
