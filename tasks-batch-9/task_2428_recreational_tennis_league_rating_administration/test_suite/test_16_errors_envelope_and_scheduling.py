"""Envelope, identity, clock and fixture-scheduling refusals."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CLOCK_NOT_MONOTONIC,
    ERR_INVALID_PAGINATION,
    ERR_LEAGUE_NOT_IN_PLAY,
    ERR_MATCH_RESULT_STATE_INVALID,
    ERR_MATCH_START_OUTSIDE_WINDOW,
    ERR_MISSING_ROLE_HEADER,
    ERR_MISSING_USER_ID,
    ERR_NOT_TEAM_CAPTAIN,
    ERR_ROLE_NOT_PERMITTED,
    ERR_SCORECARD_ALREADY_OPEN,
    ERR_SCORECARD_LINE_INVALID,
    ERR_SCORECARD_STATE_FORBIDS_ACTION,
    ERR_SELF_VERIFICATION_FORBIDDEN,
    ERR_STALE_MATCH_VERSION,
    ERR_TEAM_LEAGUE_MISMATCH,
    ERR_TEAM_STATE_INVALID,
    ERR_UNKNOWN_ROLE,
)
from test_helpers.constants import (
    CLOCK_DEFAULT,
    RESULT_PENDING,
    RESULT_REPORTED,
    REVIEW_VERIFY,
    SCHED_SCHEDULED,
    SCHED_UNSCHEDULED,
    SCORECARD_SUBMITTED,
    SCORECARD_VERIFIED,
    STAGE_REGULAR,
)
from test_helpers.fixtures import (
    Scenario,
    six_a_side_league,
    standard_three_lines,
    two_team_league,
)
from test_helpers.test_users import (
    LEAGUE_COORDINATOR,
    SECTION_ADMIN,
    headers_without_role,
    make_committee_chair_headers,
    make_role_headers,
)


def _one_section_one_player(api):
    """A single enrolled player, so a valid page can never be mistaken for empty."""
    s = Scenario(api)
    s.set_clock(CLOCK_DEFAULT)
    s.create_section()
    s.add_player("ph1", full_name="Hank Halfvolley")
    return s


def test_a_page_size_above_one_hundred_is_refused_before_any_filter_runs(api):
    """101 is outside the closed band while 100 is the last admissible page size.

    PRD 2.3: "`limit` controls page size: it defaults to 10 when omitted, has a
    minimum accepted value of 1 and a maximum accepted value of 100."

    Design: Corner/errors/players_list_with_limit_101_returns_400_invalid_pagination
    """
    s = _one_section_one_player(api)
    validate_error(
        api.list_players(SECTION_ADMIN, {"limit": 101, "offset": 0}),
        ERR_INVALID_PAGINATION,
        400,
    )
    validate_error(
        api.list_players(SECTION_ADMIN, {"limit": 0, "offset": 0}),
        ERR_INVALID_PAGINATION,
        400,
    )
    validate_error(
        api.list_players(SECTION_ADMIN, {"limit": 10, "offset": -1}),
        ERR_INVALID_PAGINATION,
        400,
    )

    at_the_cap, cap_meta = validate_paginated(
        api.list_players(SECTION_ADMIN, {"limit": 100, "offset": 0})
    )
    assert cap_meta["limit"] == 100
    assert cap_meta["total_count"] == 1
    assert at_the_cap[0]["id"] == s.player_id("ph1")

    _defaults, default_meta = validate_paginated(api.list_players(SECTION_ADMIN))
    assert default_meta["limit"] == 10
    assert default_meta["offset"] == 0
    assert default_meta["has_more"] is False


def test_a_request_with_no_role_header_is_rejected_on_the_header(api):
    """Identity is resolved before the resource, and the role header comes first.

    PRD 2.1: "If `X-User-Role` is absent or empty the request is refused with
    `ERR_MISSING_ROLE_HEADER` (HTTP 401)."

    Design: Corner/errors/unauthenticated_player_read_returns_401_missing_role_header
    """
    s = _one_section_one_player(api)
    player_id = s.player_id("ph1")

    response = api.get_player(player_id, headers_without_role(player_id))
    validate_error(response, ERR_MISSING_ROLE_HEADER, 401)
    assert response.json()["data"]["error_id"] != ERR_MISSING_USER_ID

    validate_error(
        api.get_player(player_id, make_role_headers("", player_id)),
        ERR_MISSING_ROLE_HEADER,
        401,
    )

    readable = get_success_data(api.get_player(player_id, SECTION_ADMIN))
    assert readable["id"] == player_id


def test_an_unrecognised_role_string_is_a_401_and_never_a_403(api):
    """A role outside the six declared strings never reaches the endpoint's list.

    PRD 2.1: "If it is present but is not one of those six exact strings, the
    refusal is `ERR_UNKNOWN_ROLE` (HTTP 401)."

    Design: Corner/errors/player_read_with_an_invalid_role_header_returns_401_unknown_role
    """
    s = _one_section_one_player(api)
    player_id = s.player_id("ph1")

    response = api.get_player(player_id, make_role_headers("Referee", player_id))
    validate_error(response, ERR_UNKNOWN_ROLE, 401)
    assert response.json()["data"]["error_id"] != ERR_ROLE_NOT_PERMITTED
    assert response.status_code != 403

    # The read itself is broadly permitted, so only the role string was at fault.
    permitted = get_success_data(
        api.get_player(player_id, make_committee_chair_headers(player_id))
    )
    assert permitted["id"] == player_id


def test_the_logical_clock_refuses_to_move_backwards_but_accepts_a_restamp(api):
    """One second earlier is refused; the identical instant is not a backwards move.

    PRD 2.5: "The clock may only ever move forward: if the supplied instant is
    earlier than the clock's present value, the request is refused with
    `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422). Supplying an instant equal to the present
    value is not a backwards move and is accepted."

    Design: Corner/errors/clock_set_backwards_returns_422_clock_not_monotonic
    """
    s = _one_section_one_player(api)
    validate_error(
        api.set_clock("2026-07-31T23:59:59Z", SECTION_ADMIN),
        ERR_CLOCK_NOT_MONOTONIC,
        422,
    )
    get_success_data(api.set_clock(CLOCK_DEFAULT, SECTION_ADMIN))

    # The refused move did not roll the clock back either.
    enrolled = get_success_data(
        api.create_player(
            f.player_payload(s.section["id"], "Tim Topspin"), SECTION_ADMIN
        ),
        201,
    )
    assert enrolled["created_at"].startswith("2026-08-01T00:00:00")


def test_a_fixture_may_not_name_the_same_team_on_both_sides(api):
    """The mismatch code covers the self-pairing as well as a foreign side.

    PRD 3.5: "Both sides must belong to the named league and must differ from each
    other; a side drawn from another league, or the same team named twice, is
    refused with `ERR_TEAM_LEAGUE_MISMATCH`."

    Design: Corner/errors/fixture_with_identical_home_and_away_returns_422_team_league_mismatch
    """
    s = two_team_league(api, roster_size=2)
    validate_error(
        api.create_match(
            f.match_payload(
                s.league["id"], s.teams["th"]["id"], s.teams["th"]["id"]
            ),
            LEAGUE_COORDINATOR,
        ),
        ERR_TEAM_LEAGUE_MISMATCH,
        422,
    )

    _matches, meta = validate_paginated(
        api.list_matches(
            SECTION_ADMIN, {"league_id": s.league["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0

    created = get_success_data(
        api.create_match(
            f.match_payload(
                s.league["id"], s.teams["th"]["id"], s.teams["ta"]["id"]
            ),
            LEAGUE_COORDINATOR,
        ),
        201,
    )
    assert created["schedule_status"] == SCHED_UNSCHEDULED


def test_a_slot_must_be_future_dated_and_inside_the_regular_season(api):
    """Yesterday is refused, so is a REGULAR start past the season end.

    PRD 3.5: "A start instant in the past, or on the wrong side of the season
    boundary for its stage, is refused with `ERR_MATCH_START_OUTSIDE_WINDOW`."

    Design: Corner/errors/scheduling_a_start_in_the_past_returns_422_match_start_outside_window
    """
    s = two_team_league(
        api,
        roster_size=2,
        league_kwargs={"season_end_at": "2026-09-30T00:00:00Z"},
    )
    s.set_clock("2026-08-10T00:00:00Z")
    s.create_match("m1", "th", "ta")
    fixture = s.refresh_match("m1")
    assert fixture["version"] == 1

    response = api.schedule_match(
        fixture["id"],
        f.schedule_payload(
            s.facility["id"], "2026-08-09T18:00:00Z", fixture["version"], 3
        ),
        LEAGUE_COORDINATOR,
    )
    validate_error(response, ERR_MATCH_START_OUTSIDE_WINDOW, 422)
    # The declared version is the live one, so the OCC check cannot be the cause.
    assert response.json()["data"]["error_id"] != ERR_STALE_MATCH_VERSION

    untouched = s.refresh_match("m1")
    assert untouched["schedule_status"] == SCHED_UNSCHEDULED
    assert untouched["facility_id"] is None
    assert untouched["scheduled_start_at"] is None
    assert untouched["version"] == 1

    validate_error(
        api.schedule_match(
            untouched["id"],
            f.schedule_payload(
                s.facility["id"], "2026-10-01T18:00:00Z", untouched["version"], 3
            ),
            LEAGUE_COORDINATOR,
        ),
        ERR_MATCH_START_OUTSIDE_WINDOW,
        422,
    )

    accepted = get_success_data(
        api.schedule_match(
            untouched["id"],
            f.schedule_payload(
                s.facility["id"], "2026-08-15T18:00:00Z", untouched["version"], 3
            ),
            LEAGUE_COORDINATOR,
        )
    )
    assert accepted["schedule_status"] == SCHED_SCHEDULED


def test_a_fixture_cannot_be_created_while_registration_is_still_open(api):
    """Rosters must at least be locked; being registered is not enough.

    PRD 3.5: "Fixture creation requires the league to be at `ROSTERS_LOCKED`,
    `IN_PLAY` or `PLAYOFFS`; a league at any other stage refuses with
    `ERR_LEAGUE_NOT_IN_PLAY`, and the same code guards scheduling, confirmation and
    marking played."

    Design: Corner/errors/match_creation_while_registration_is_open_returns_409_league_not_in_play
    """
    s = two_team_league(api, roster_size=2, start=False)
    payload = f.match_payload(
        s.league["id"],
        s.teams["th"]["id"],
        s.teams["ta"]["id"],
        stage=STAGE_REGULAR,
    )

    response = api.create_match(payload, LEAGUE_COORDINATOR)
    validate_error(response, ERR_LEAGUE_NOT_IN_PLAY, 409)
    # REGISTERED is an admissible team state for being named on a fixture.
    assert response.json()["data"]["error_id"] != ERR_TEAM_STATE_INVALID

    _matches, meta = validate_paginated(
        api.list_matches(
            SECTION_ADMIN, {"league_id": s.league["id"], "limit": 100, "offset": 0}
        )
    )
    assert meta["total_count"] == 0

    s.set_clock("2026-08-08T00:00:00Z")
    s.lock_rosters()
    created = get_success_data(api.create_match(payload, LEAGUE_COORDINATOR), 201)
    assert created["schedule_status"] == SCHED_UNSCHEDULED
    assert created["league_id"] == s.league["id"]


# ---------------------------------------------------------------------------
def _played_match_without_a_card(api):
    """M1 is PLAYED and PENDING with the clock parked on its scheduled end."""
    s = six_a_side_league(api)
    s.create_match("m1", "th", "ta")
    s.schedule_match("m1", "2026-08-15T18:00:00Z", 3)
    s.confirm_match("m1")
    s.set_clock("2026-08-15T21:00:00Z")
    s.mark_played("m1")
    return s


def _reported_match_with_the_home_card_open(api):
    """The home captain's card is SUBMITTED, so the match sits at REPORTED."""
    s = _played_match_without_a_card(api)
    s.submit_scorecard("m1", standard_three_lines(s))
    return s


def _away_view_of_the_same_match(s):
    """A competing card that reverses lines 1 and 3."""
    return [
        f.scorecard_line(
            1,
            [s.player_id("ph1"), s.player_id("ph2")],
            [s.player_id("pa1"), s.player_id("pa2")],
            [f.set_score(4, 6), f.set_score(3, 6)],
        ),
        f.scorecard_line(
            2,
            [s.player_id("ph3"), s.player_id("ph4")],
            [s.player_id("pa3"), s.player_id("pa4")],
            [f.set_score(6, 0), f.set_score(6, 0)],
        ),
        f.scorecard_line(
            3,
            [s.player_id("ph5"), s.player_id("ph6")],
            [s.player_id("pa5"), s.player_id("pa6")],
            [f.set_score(4, 6), f.set_score(3, 6)],
        ),
    ]


def test_a_competing_card_on_a_reported_match_is_refused_on_the_result_state(api):
    """Rank 25 answers before the single-open-card rule ever gets to speak.

    PRD 3.6: "The submission drives the match's `result_status` from `PENDING` to
    `REPORTED` and the scorecard itself arrives at `status` `SUBMITTED` with
    `amendment_count` 0, `dispute_reason` null, an empty `disputed_line_numbers`
    array, `verified_by_captain_player_id` null and `verified_at` null."

    Design: Corner/errors/second_scorecard_on_a_reported_match_returns_409_match_result_state_invalid
    """
    s = _reported_match_with_the_home_card_open(api)
    response = api.create_scorecard(
        f.scorecard_payload(s.matches["m1"]["id"], _away_view_of_the_same_match(s)),
        s.captain_headers("ta"),
    )
    validate_error(response, ERR_MATCH_RESULT_STATE_INVALID, 409)
    reported = response.json()["data"]["error_id"]
    assert reported != ERR_SCORECARD_ALREADY_OPEN
    assert reported != ERR_NOT_TEAM_CAPTAIN

    cards, meta = validate_paginated(
        api.list_scorecards(
            SECTION_ADMIN,
            {"match_id": s.matches["m1"]["id"], "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert cards[0]["submitted_by_captain_player_id"] == s.player_id("ph1")

    on_file = get_success_data(
        api.get_scorecard(s.scorecards["sc1"]["id"], SECTION_ADMIN)
    )
    assert on_file["status"] == SCORECARD_SUBMITTED
    assert on_file["lines"][0]["set_scores"] == [
        {"home_games": 6, "away_games": 4},
        {"home_games": 6, "away_games": 0},
    ]
    assert s.refresh_match("m1")["result_status"] == RESULT_REPORTED


def test_the_submitting_captain_may_not_verify_its_own_scorecard(api):
    """Captaincy of one side is not enough; review belongs to the other side.

    PRD 3.6: "The reviewer must be the captain of the side that did **not** submit
    - the submitting captain attempting to verify their own scorecard is refused
    with `ERR_SELF_VERIFICATION_FORBIDDEN`, and so is a non-submitting captain
    attempting an amendment."

    Design: Corner/errors/submitting_captain_reviewing_its_own_card_returns_409_self_verification_forbidden
    """
    s = _reported_match_with_the_home_card_open(api)
    card_id = s.scorecards["sc1"]["id"]

    response = api.review_scorecard(
        card_id, {"decision": REVIEW_VERIFY}, s.captain_headers("th")
    )
    validate_error(response, ERR_SELF_VERIFICATION_FORBIDDEN, 409)
    reported = response.json()["data"]["error_id"]
    assert reported != ERR_NOT_TEAM_CAPTAIN
    assert reported != ERR_SCORECARD_STATE_FORBIDS_ACTION

    still_open = get_success_data(api.get_scorecard(card_id, SECTION_ADMIN))
    assert still_open["status"] == SCORECARD_SUBMITTED
    assert still_open["verified_at"] is None
    assert still_open["verified_by_captain_player_id"] is None

    match = s.refresh_match("m1")
    assert match["result_status"] == RESULT_REPORTED
    assert match["line_results"] == []
    assert s.refresh_player("ph1")["verified_line_count"] == 0

    verified = get_success_data(
        api.review_scorecard(
            card_id, {"decision": REVIEW_VERIFY}, s.captain_headers("ta")
        )
    )
    assert verified["status"] == SCORECARD_VERIFIED


def test_a_card_whose_line_structure_is_wrong_is_refused_on_its_shape(api):
    """Too few lines, duplicated numbers and an illegal set all fail the same check.

    PRD 3.6: "There must be exactly as many entries as the league's
    `lines_per_match`, their `line_number` values must run within 1 through
    `lines_per_match` with no duplicates, and each side of each line must name two
    *distinct* player identifiers. The `set_scores` array must describe legal tennis
    sets: a set is won either at 6 games with the loser on at most 4, or at 7 games
    with the loser on 5 or 6; a line is best of three sets; and a third set may
    instead be a 10-point tiebreak, which is recorded as a set of 1 games to 0."

    Design: Corner/errors/card_with_two_lines_in_a_three_line_league_returns_422_scorecard_line_invalid
    """
    s = _played_match_without_a_card(api)
    canonical = standard_three_lines(s)

    validate_error(
        api.create_scorecard(
            f.scorecard_payload(s.matches["m1"]["id"], canonical[:2]),
            s.captain_headers("th"),
        ),
        ERR_SCORECARD_LINE_INVALID,
        422,
    )

    duplicated = [dict(canonical[0]), dict(canonical[0]), dict(canonical[1])]
    duplicated[2] = dict(duplicated[2], line_number=2)
    validate_error(
        api.create_scorecard(
            f.scorecard_payload(s.matches["m1"]["id"], duplicated),
            s.captain_headers("th"),
        ),
        ERR_SCORECARD_LINE_INVALID,
        422,
    )

    illegal_set = [
        canonical[0],
        canonical[1],
        dict(canonical[2], set_scores=[f.set_score(6, 5)]),
    ]
    validate_error(
        api.create_scorecard(
            f.scorecard_payload(s.matches["m1"]["id"], illegal_set),
            s.captain_headers("th"),
        ),
        ERR_SCORECARD_LINE_INVALID,
        422,
    )

    _cards, meta = validate_paginated(
        api.list_scorecards(
            SECTION_ADMIN,
            {"match_id": s.matches["m1"]["id"], "limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 0
    assert s.refresh_match("m1")["result_status"] == RESULT_PENDING

    accepted = get_success_data(
        api.create_scorecard(
            f.scorecard_payload(s.matches["m1"]["id"], canonical),
            s.captain_headers("th"),
        ),
        201,
    )
    assert accepted["status"] == SCORECARD_SUBMITTED
