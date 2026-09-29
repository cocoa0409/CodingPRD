"""Scheduling a contest: the season window, the venue, the load, and the lock."""
from test_helpers import (
    ApiErrorId,
    assert_contest,
    create_contest_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx


def _four_schools_and_a_season(clock="2026-09-02T09:00:00Z", **season_overrides):
    set_clock(clock)
    names = [("Alpha High", "R-NORTH"), ("Beta High", "R-NORTH"),
             ("Gamma High", "R-SOUTH"), ("Delta High", "R-SOUTH")]
    schools = [fx.create_school(name=name, classification="C3A", region_code=region)
               for name, region in names]
    payload = {"required_officials": 1, "contest_limit": 10}
    payload.update(season_overrides)
    season = fx.create_season(**payload)
    return schools, season


def test_fourth_contest_inside_the_rolling_window_is_refused_for_the_away_school(
    api, admin_headers
):
    """PRD §3.7: "Then, among those same games, the service counts how many start
    inside a rolling window running from seven days before the new game's
    `starts_at` up to seven days after it, where the lower bound is included and the
    upper bound is not — a game starting exactly seven days before is inside the
    window, one starting exactly seven days after is outside it. If three or more
    already sit in that window, the answer is `ERR_CONTEST_WINDOW_DENSITY`."
    PRD §3.7: "**The load check** comes last and is run twice, first for the home
    school and then for the away school, with both of its tests applied to a school
    before the next school is considered."

    Design: Corner/calculations/fourth_contest_inside_the_rolling_window_is_rejected_for_the_away_school
    """
    schools, season = _four_schools_and_a_season()
    alpha, beta, gamma, delta = schools
    for host, day in ((beta, "2026-09-10"), (gamma, "2026-09-11"), (delta, "2026-09-12")):
        fx.create_contest(season["id"], host["id"], alpha["id"],
                          f"{day}T18:00:00Z", f"{day}T20:00:00Z",
                          headers=admin_headers, travel_miles=20)

    response = api.create_contest(
        create_contest_payload(season["id"], beta["id"], alpha["id"],
                               "2026-09-13T18:00:00Z", "2026-09-13T20:00:00Z",
                               fx.season_version(season["id"]), travel_miles=20),
        admin_headers,
    )

    validate_error(response, ApiErrorId.ERR_CONTEST_WINDOW_DENSITY.value, 409)
    assert fx.read_season(season["id"])["scheduled_contest_count"] == 3
    rows, _meta = validate_paginated(
        api.list_contests(admin_headers, {"away_school_id": alpha["id"], "limit": 100})
    )
    assert len(rows) == 3


def test_a_game_exactly_seven_days_away_sits_outside_the_rolling_window(api, admin_headers):
    """PRD §3.7: "Then, among those same games, the service counts how many start
    inside a rolling window running from seven days before the new game's
    `starts_at` up to seven days after it, where the lower bound is included and the
    upper bound is not — a game starting exactly seven days before is inside the
    window, one starting exactly seven days after is outside it."

    Design: Corner/calculations/rolling_window_upper_bound_is_exclusive_at_exactly_seven_days
    """
    schools, season = _four_schools_and_a_season()
    alpha, beta = schools[0], schools[1]
    fx.create_contest(season["id"], alpha["id"], beta["id"],
                      "2026-09-13T18:00:00Z", "2026-09-13T20:00:00Z",
                      headers=admin_headers, travel_miles=20)

    response = api.create_contest(
        create_contest_payload(season["id"], beta["id"], alpha["id"],
                               "2026-09-06T18:00:00Z", "2026-09-06T20:00:00Z",
                               fx.season_version(season["id"]), travel_miles=20),
        admin_headers,
    )

    created = validate_success(response, 201)
    assert_contest(created)
    assert created["status"] == "SCHEDULED"
    assert fx.read_season(season["id"])["scheduled_contest_count"] == 2


def test_venue_turnover_rejects_inside_the_hour_and_admits_at_the_hour(api):
    """PRD §3.7: "The service looks at every contest already scheduled at the same
    home venue, in any status and across every season, and counts a contest as
    occupying the venue when the new game's `starts_at` falls strictly before that
    booked game's `ends_at` plus one hour of turnover, and the booked game's
    `starts_at` falls strictly before the new game's `ends_at`. If the number of such
    occupants plus the new game would exceed the home school's
    `venue_concurrent_capacity`, the answer is `ERR_VENUE_TURNOVER_CONFLICT`."
    PRD §3.7: "Note the shape this produces: a new game ending exactly when a booked
    game begins is admitted, but a new game starting anywhere inside the booked
    game's 60-minute trailing turnover is not."

    Design: Corner/calculations/venue_turnover_buffer_rejects_inside_the_hour_but_admits_at_the_hour
    """
    ctx = fx.setup_two_schools_and_open_season(
        clock="2026-09-10T09:00:00Z",
        home_overrides={"name": "North High", "venue_concurrent_capacity": 1},
        season_overrides={"required_officials": 1},
        open_season=False,
    )
    home_headers = fx.make_director_headers(ctx["home"]["id"])
    fx.create_contest(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                      "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z", travel_miles=20)
    version = fx.season_version(ctx["season"]["id"])

    inside_turnover = api.create_contest(
        create_contest_payload(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                               "2026-09-20T20:30:00Z", "2026-09-20T22:30:00Z",
                               version, travel_miles=20),
        home_headers,
    )
    validate_error(inside_turnover, ApiErrorId.ERR_VENUE_TURNOVER_CONFLICT.value, 409)

    at_the_hour = api.create_contest(
        create_contest_payload(ctx["season"]["id"], ctx["home"]["id"], ctx["away"]["id"],
                               "2026-09-20T21:00:00Z", "2026-09-20T23:00:00Z",
                               version, travel_miles=20),
        home_headers,
    )
    admitted = validate_success(at_the_hour, 201)

    assert admitted["status"] == "SCHEDULED"
    assert fx.read_season(ctx["season"]["id"])["scheduled_contest_count"] == 2


def test_season_window_check_is_reported_before_the_rolling_density_check(
    api, admin_headers
):
    """PRD §2.6: "Checks are evaluated in the following fixed order, and the first
    failing check determines the response."
    PRD §2.6: "A contest's start date falls on or after the season's
    `first_contest_date` and on or before its `season_end_date` — otherwise
    `ERR_CONTEST_OUTSIDE_SEASON_WINDOW` (409)."
    PRD §2.6: "The season limit and the rolling-window density admit the new
    contest, for the home school first and then the away school — otherwise
    `ERR_SEASON_CONTEST_LIMIT` (409) or `ERR_CONTEST_WINDOW_DENSITY` (409)."

    Design: Corner/validations/season_window_check_outranks_the_rolling_density_check
    """
    schools, season = _four_schools_and_a_season(season_end_date="2026-11-15")
    alpha, beta, gamma, delta = schools
    for host, day in ((beta, "2026-11-10"), (gamma, "2026-11-11"), (delta, "2026-11-12")):
        fx.create_contest(season["id"], host["id"], alpha["id"],
                          f"{day}T18:00:00Z", f"{day}T20:00:00Z",
                          headers=admin_headers, travel_miles=20)

    response = api.create_contest(
        create_contest_payload(season["id"], beta["id"], alpha["id"],
                               "2026-11-16T18:00:00Z", "2026-11-16T20:00:00Z",
                               fx.season_version(season["id"]), travel_miles=20),
        admin_headers,
    )

    validate_error(response, ApiErrorId.ERR_CONTEST_OUTSIDE_SEASON_WINDOW.value, 409)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_CONTEST_WINDOW_DENSITY.value
    assert fx.read_season(season["id"])["scheduled_contest_count"] == 3


def test_a_school_cannot_play_itself(api, admin_headers):
    """PRD §3.7: "**Opponent sanity** comes third: `home_school_id` must differ from
    `away_school_id`, or the answer is `ERR_SAME_SCHOOL_CONTEST`, and both schools'
    `classification` must equal the season's `classification`, or the answer is
    `ERR_CLASSIFICATION_MISMATCH`."

    Design: Corner/validations/contest_with_the_same_school_on_both_sides_is_rejected
    """
    set_clock("2026-09-02T09:00:00Z")
    school = fx.create_school(name="Alpha High")
    season = fx.create_season()

    response = api.create_contest(
        create_contest_payload(season["id"], school["id"], school["id"],
                               "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z",
                               fx.season_version(season["id"]), travel_miles=0),
        admin_headers,
    )

    validate_error(response, ApiErrorId.ERR_SAME_SCHOOL_CONTEST.value, 409)
    assert fx.read_season(season["id"])["scheduled_contest_count"] == 0


def test_schools_from_another_classification_band_cannot_meet(api, admin_headers):
    """PRD §3.7: "**Opponent sanity** comes third: `home_school_id` must differ from
    `away_school_id`, or the answer is `ERR_SAME_SCHOOL_CONTEST`, and both schools'
    `classification` must equal the season's `classification`, or the answer is
    `ERR_CLASSIFICATION_MISMATCH`."
    PRD §3.7: "Only schools in the same enrolment band may meet."

    Design: Corner/validations/contest_between_mismatched_classifications_is_rejected
    """
    set_clock("2026-09-02T09:00:00Z")
    home = fx.create_school(name="Alpha High", classification="C3A")
    away = fx.create_school(name="Big High", classification="C4A",
                            region_code="R-SOUTH")
    season = fx.create_season(classification="C3A")

    response = api.create_contest(
        create_contest_payload(season["id"], home["id"], away["id"],
                               "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z",
                               fx.season_version(season["id"]), travel_miles=20),
        admin_headers,
    )

    validate_error(response, ApiErrorId.ERR_CLASSIFICATION_MISMATCH.value, 409)


def test_replaying_a_stale_season_version_is_refused_with_412(api, admin_headers):
    """PRD §2.7: "Creating a contest requires `expected_sport_season_version` as a
    mandatory body field carrying the client's last observed `version` of the target
    `SportSeason`. If that value does not equal the season's current `version` —
    because another writer has since added a contest or advanced the calendar — the
    create is rejected with `ERR_STALE_SEASON_VERSION` and HTTP 412, and nothing is
    persisted."

    Design: Corner/cross_cutting_layers/contest_create_with_a_stale_season_version_returns_412
    """
    set_clock("2026-09-02T09:00:00Z")
    home = fx.create_school(name="Alpha High")
    away = fx.create_school(name="Beta High", region_code="R-SOUTH")
    season = fx.create_season()
    stale_version = fx.season_version(season["id"])

    first = api.create_contest(
        create_contest_payload(season["id"], home["id"], away["id"],
                               "2026-09-20T18:00:00Z", "2026-09-20T20:00:00Z",
                               stale_version, travel_miles=20),
        admin_headers,
    )
    validate_success(first, 201)

    second = api.create_contest(
        create_contest_payload(season["id"], away["id"], home["id"],
                               "2026-10-20T18:00:00Z", "2026-10-20T20:00:00Z",
                               stale_version, travel_miles=20),
        admin_headers,
    )

    validate_error(second, ApiErrorId.ERR_STALE_SEASON_VERSION.value, 412)
    assert fx.read_season(season["id"])["scheduled_contest_count"] == 1
    rows, _meta = validate_paginated(
        api.list_contests(admin_headers, {"sport_season_id": season["id"], "limit": 100})
    )
    assert len(rows) == 1
