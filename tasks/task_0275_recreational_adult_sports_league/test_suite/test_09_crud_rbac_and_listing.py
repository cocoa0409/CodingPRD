"""Resource creation, body validation, RBAC, pagination, and reverse-reachability
listing corners.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    is_valid_uuid,
    make_league_admin_headers, make_team_captain_headers, make_referee_headers,
    build_user_headers,
    ApiErrorId, NON_EXISTENT_UUID,
)
import test_helpers.fixtures as fx
import test_helpers.factories as F

ADMIN = make_league_admin_headers()


def test_create_season_returns_201_draft_with_defaults(api):
    """PRD §3.1: "A new season is born in `DRAFT`, its `clock_now` initialized to its
    creation time, its `version` at 1."
    PRD §3.1: "The partial-refund percentage defaults to 50 when omitted and is an
    integer percent between 0 and 100."

    Design: Corner/entities/create_season_returns_201_with_all_fields
    """
    payload = F.create_season_payload(name="S1")
    season = validate_success(api.create_season(payload, ADMIN), expected_status=201)
    assert season["registration_status"] == "DRAFT"
    assert season["version"] == 1
    assert season["refund_partial_pct"] == 50, "omitted refund_partial_pct defaults to 50"
    assert is_valid_uuid(season["id"])


def test_get_season_not_found(api):
    """PRD §2.7: "The first identifier in the path (or the body) that does not resolve
    to an existing resource causes the request to fail with `ERR_NOT_FOUND` (HTTP 404)
    before any later identifier is examined and before any business rule is evaluated."

    Design: Corner/entities/get_season_not_found_returns_404
    """
    resp = api.get_season(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_division_missing_required_field(api):
    """PRD §2.7: "Body well-formedness, checked at the `ERR_INVALID_REQUEST` (HTTP 422)
    tier, covers: all required fields present, every enum value within its declared
    range, every submitted score being zero or greater, `field_index` falling within
    the inclusive range from 1 to the hosting venue's `field_count`, and `ends_at`
    being strictly later than `starts_at`."

    Design: Corner/entities/create_division_missing_required_field_returns_invalid_request
    """
    season = fx.create_season()
    payload = {"name": "D", "skill_tier": "REC", "min_roster_size": 1,
               "max_roster_size": 8, "registration_fee_cents": 0}  # team_capacity missing
    resp = api.create_division(season["id"], payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_division_invalid_skill_tier_enum(api):
    """PRD §2.7: "Body well-formedness, checked at the `ERR_INVALID_REQUEST` (HTTP 422)
    tier, covers: all required fields present, every enum value within its declared
    range, every submitted score being zero or greater, `field_index` falling within
    the inclusive range from 1 to the hosting venue's `field_count`, and `ends_at`
    being strictly later than `starts_at`."
    PRD §2.10: "A `Division` has a `skill_tier` of `REC`, `INTERMEDIATE`, or
    `COMPETITIVE` and a `standings_tiebreaker` of either `HEAD_TO_HEAD` or
    `POINT_DIFFERENTIAL`."

    Design: Corner/entities/create_division_invalid_enum_skill_tier_returns_invalid_request
    """
    season = fx.create_season()
    payload = F.create_division_payload(skill_tier="PRO")
    resp = api.create_division(season["id"], payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_game_ends_at_not_after_starts_at(api):
    """PRD §2.7: "Body well-formedness, checked at the `ERR_INVALID_REQUEST` (HTTP 422)
    tier, covers: all required fields present, every enum value within its declared
    range, every submitted score being zero or greater, `field_index` falling within
    the inclusive range from 1 to the hosting venue's `field_count`, and `ends_at`
    being strictly later than `starts_at`."

    Design: Corner/entities/game_ends_at_not_after_starts_at_returns_invalid_request
    """
    base = fx.setup_division_with_two_confirmed_teams()
    venue = fx.create_venue()
    payload = F.create_game_payload(
        base["home_team"]["id"], base["away_team"]["id"], venue["id"],
        starts_at="2026-09-15T19:30:00Z", ends_at="2026-09-15T18:00:00Z",
    )
    resp = api.create_game(base["division"]["id"], payload, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_system_fields_ignored_on_player_create(api):
    """PRD §3.3: "A new player begins as a free agent with `conduct_points` of 0 and
    `suspension_status` `CLEAR`."

    Design: Corner/entities/system_fields_ignored_on_player_create
    """
    payload = F.create_player_payload(full_name="Newbie", email="newbie@x.com")
    player = validate_success(api.create_player(payload, ADMIN), expected_status=201)
    assert player["conduct_points"] == 0
    assert player["is_free_agent"] is True
    assert player["suspension_status"] == "CLEAR"
    assert is_valid_uuid(player["id"])


def test_duplicate_player_email_rejected(api):
    """PRD §3.3: "the email must be globally unique among players that are not
    `CANCELLED`, and a collision is rejected with `ERR_DUPLICATE`."

    Design: Corner/entities/duplicate_player_email_returns_duplicate
    """
    validate_success(api.create_player(F.create_player_payload(full_name="First", email="dup@x.com"), ADMIN),
                     expected_status=201)
    resp = api.create_player(F.create_player_payload(full_name="Second", email="dup@x.com"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_team_captain_cannot_schedule_game(api):
    """PRD §2.1: "When a recognized and authenticated caller attempts an operation
    their role is not permitted to perform — or an operation that requires ownership of
    the target resource which the caller does not own — the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Game scheduling is LeagueAdmin-only per the §4 endpoint table.

    Design: Corner/rbac/team_captain_cannot_schedule_game_returns_forbidden
    """
    base = fx.setup_division_with_two_confirmed_teams()
    venue = fx.create_venue()
    payload = F.create_game_payload(base["home_team"]["id"], base["away_team"]["id"], venue["id"])
    resp = api.create_game(base["division"]["id"], payload,
                           make_team_captain_headers(base["home_player"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` does not name a role
    the system recognizes, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    headers = build_user_headers("nobody-1", "Nobody")
    resp = api.create_season(F.create_season_payload(name="NoAuth"), headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_confirm_score_by_team_captain_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `Referee`, `X-User-ID` is the `id` of the
    acting `Referee`. Ownership checks on any resource that references a `Referee`
    compare that resource's `referee_id` to `X-User-ID`; in particular, confirming a
    score is restricted to the referee who holds the game's `HEAD` assignment."

    confirm-score is Referee-only per the §4 endpoint table; a TeamCaptain attempt is
    rejected with `ERR_FORBIDDEN`.

    Design: Corner/rbac/confirm_score_by_team_captain_returns_forbidden
    """
    s = fx.setup_in_play_game_pending()
    ref_headers = make_referee_headers(s["referee"]["id"])
    gv = validate_success(api.get_game(s["game"]["id"], ADMIN))["version"]
    validate_success(api.submit_score(s["game"]["id"], F.submit_score_payload(1, 0, gv), ref_headers))
    resp = api.confirm_score(s["game"]["id"], make_team_captain_headers(s["home_player"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_list_divisions_pagination_envelope(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping in the `meta`
    object: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/list_divisions_pagination_envelope
    """
    season = fx.create_season()
    fx.create_division(season["id"], name="P1", skill_tier="REC")
    fx.create_division(season["id"], name="P2", skill_tier="INTERMEDIATE")
    resp = api.list_divisions(season["id"], ADMIN, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_pagination_limit_out_of_range_rejected(api):
    """PRD §2.3: "A `limit` or `offset` outside these bounds is rejected with
    `ERR_PAGINATION_RANGE` (HTTP 422)."

    Design: Corner/endpoints/pagination_limit_out_of_range_returns_error
    """
    season = fx.create_season()
    resp = api.list_divisions(season["id"], ADMIN, params={"limit": 0, "offset": 0})
    validate_error(resp, ApiErrorId.ERR_PAGINATION_RANGE.value)


def test_games_filter_by_home_team(api):
    """PRD §4 (endpoint table): "List games filtered by team/venue/forfeiting team".
    PRD §3.7: "records the charged team in `forfeiting_team_id` (discoverable by
    filtering the games list on that field)".

    A games-list filtered by `home_team_id` returns only games with that home team.

    Design: Corner/endpoints/games_filter_by_home_team_reverse_reachability
    """
    s = fx.setup_scheduled_game(with_head_referee=False)
    resp = api.list_games(ADMIN, params={"home_team_id": s["home_team"]["id"]})
    data, _meta = validate_paginated(resp)
    returned_ids = [g["id"] for g in data]
    assert s["game"]["id"] in returned_ids, "the scheduled game must be returned for its home team"
    for g in data:
        assert g["home_team_id"] == s["home_team"]["id"], (
            "every returned game must have the filtered home_team_id"
        )
