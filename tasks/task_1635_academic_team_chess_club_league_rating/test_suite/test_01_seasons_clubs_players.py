"""Season, club, coach, and player core entity claims (PRD §2.4, §2.9, §2.10, §3.1)."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_club,
    assert_player,
    assert_season,
    create_club,
    create_club_payload,
    create_coach_payload,
    create_player_payload,
    create_season,
    create_season_payload,
    create_active_season,
    is_valid_uuid,
    setup_one_club,
    validate_error,
    validate_success,
)

def test_season_defaults_applied(api, federation_admin_headers):
    """PRD §3.1: "Three competitive parameters carry defaults: `provisional_game_threshold`
    defaults to 20 and must be at least 1, `base_rating` defaults to 800, and
    `state_bid_slots_per_region` defaults to 2 and must be at least 1."
    PRD §3.1: "A new season begins in `REGISTRATION`, moves to `ACTIVE` when the
    administrator activates it, later to `FINALIZING` for postseason close-out, and
    finally to `COMPLETED`."

    Design: Corner/entities/season_defaults_applied
    """
    season = validate_success(
        api.create_season(create_season_payload(), federation_admin_headers), 201
    )
    assert_season(season)
    assert is_valid_uuid(season["id"]), "id must be a prefix-less UUID (PRD §2.4)"
    assert season["status"] == "REGISTRATION"
    assert season["provisional_game_threshold"] == 20
    assert season["base_rating"] == 800
    assert season["state_bid_slots_per_region"] == 2

    fetched = validate_success(api.get_season(season["id"], federation_admin_headers))
    assert fetched["provisional_game_threshold"] == 20
    assert fetched["base_rating"] == 800
    assert fetched["state_bid_slots_per_region"] == 2

def test_season_missing_required_field_returns_400(api, federation_admin_headers):
    """PRD §2.10: "Request shape — missing required fields, wrong types, out-of-range
    enum values, unknown fields, improperly ordered date ranges, a `reason` shorter
    than ten characters, a zero `amount_cents`, or round and board numbers outside a
    meet's configured bounds all yield `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.1 names "a positive `regular_due_cents`" among the creation parameters.

    Design: Corner/entities/season_missing_required_field_returns_400
    """
    payload = create_season_payload()
    del payload["regular_due_cents"]
    res = api.create_season(payload, federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

def test_coach_invalid_enum_rejected(api, federation_admin_headers):
    """PRD §3.1: "The administrator registers a coach with the owning `club_id`, a
    `full_name`, an `email`, and a `certification_level` of `CLUB`, `CERTIFIED`, or
    `SENIOR`; coaches begin `ACTIVE`."
    PRD §2.10: out-of-range enum values yield ERR_INVALID_REQUEST (400).

    Design: Corner/entities/coach_invalid_enum_rejected
    """
    season = create_season()
    club = create_club(season["id"])
    res = api.create_coach(
        create_coach_payload(club["id"], certification_level="GRANDMASTER"),
        federation_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

def test_player_get_not_found(api, federation_admin_headers):
    """PRD §2.9: "the system validates the existence of each identifier in sequential,
    left-to-right order, and the request is rejected immediately with `ERR_NOT_FOUND`
    at the first identifier that does not resolve."

    Design: Corner/entities/player_get_not_found
    """
    res = api.get_player(NON_EXISTENT_UUID, federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)

def test_player_create_body_fk_not_found(api, federation_admin_headers):
    """PRD §2.9: "Body-supplied foreign keys — fields such as `club_id`, `player_id`,
    `season_id`, `host_club_id`, `away_club_id`, `white_player_id`, `black_player_id`,
    `coach_id`, `meet_id`, and `tournament_id` on creation payloads — resolve the same
    way: an unresolvable reference is rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/player_create_body_fk_not_found
    """
    res = api.create_player(
        create_player_payload(NON_EXISTENT_UUID, full_name="Ghost", grade_level=9),
        federation_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)

def test_player_initial_defaults_and_system_fields(api, federation_admin_headers):
    """PRD §3.1: "Transfers may arrive with federation-seeded history: an optional
    `initial_rating`, which defaults to the `base_rating` of the season the club is
    registered in, and an optional `initial_rated_games`, which defaults to 0 and may
    not be negative."
    PRD §3.1: "From these seeds the system derives the player's competitive profile:
    `rating` begins at the initial rating, `rated_games_played` begins at the seeded
    game count, `peak_rating` begins at the initial rating, `is_provisional` reports
    whether the player remains below the season's provisional threshold, and
    `performance_points` starts at 0."

    Design: Corner/entities/player_initial_defaults_and_system_fields
    """
    ctx = setup_one_club(season_overrides={"provisional_game_threshold": 4, "base_rating": 800})
    player = validate_success(
        api.create_player(
            create_player_payload(ctx["club"]["id"], full_name="Newbie", grade_level=7),
            federation_admin_headers,
        ),
        201,
    )
    assert_player(player)
    assert player["rating"] == 800
    assert player["peak_rating"] == 800
    assert player["rated_games_played"] == 0
    assert player["is_provisional"] is True
    assert player["performance_points"] == 0
    assert player["status"] == "ACTIVE"

def test_season_reopen_conditional_action(api, federation_admin_headers):
    """PRD §3.1: "Finalization is not one-way: reopening returns a `FINALIZING` season
    to `ACTIVE`, and the season may cycle between the two."
    PRD §3.1: "Each of these transitions requires the season to be in exactly the
    listed from-state, otherwise the request fails with `ERR_SEASON_INVALID_STATE`."

    Design: Corner/endpoints/season_reopen_conditional_action
    """
    season = create_active_season()
    # reopen is conditional on FINALIZING: from ACTIVE it must fail
    res = api.reopen_season(season["id"], federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_SEASON_INVALID_STATE)

    finalized = validate_success(api.finalize_season(season["id"], federation_admin_headers))
    assert finalized["status"] == "FINALIZING"
    reopened = validate_success(api.reopen_season(season["id"], federation_admin_headers))
    assert reopened["status"] == "ACTIVE"
