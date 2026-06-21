"""CRUD, defaults, required-field, and type-constraint claims for the core
configuration entities (League, Official, Availability, ConflictDeclaration).

Each test translates exactly one corner-design instance (Corner queue B).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    NON_EXISTENT_UUID,
    create_league_payload, create_official_payload, create_availability_payload,
    create_conflict_declaration_payload,
    assert_league, assert_official, assert_conflict_declaration,
    TEST_USERS, make_official_headers,
)

ADMIN = TEST_USERS["league_admin_headers"]


def test_create_league_applies_defaults(api):
    """PRD §3.1: "Three postseason thresholds may be supplied or left to default:
    `postseason_min_games`, the minimum number of regular-season games an official
    must have worked to qualify, defaults to 8; `postseason_min_rating`, the minimum
    mean evaluation rating on the one-to-five scale, defaults to 3.5; and
    `postseason_max_noshows`, the most no-shows tolerated while staying eligible,
    defaults to 0."
    PRD §3.1: "A freshly created league begins in `SETUP`."

    Design: Corner/entities/create_league_returns_201_with_defaults_applied
    """
    res = api.create_league(create_league_payload(
        name="L", sport="BASKETBALL", base_game_fee_cents=10000,
        mileage_rate_cents_per_mile=50), ADMIN)
    league = validate_success(res, 201)
    assert_league(league)
    assert league["status"] == "SETUP"
    assert league["postseason_min_games"] == 8
    assert league["postseason_min_rating"] == 3.5
    assert league["postseason_max_noshows"] == 0
    assert league["version"] == 1


def test_league_initial_state_is_setup(api):
    """PRD §3.1: "A freshly created league begins in `SETUP`."

    Design: Corner/state_machines/league_lifecycle_initial_state_setup
    """
    res = api.create_league(create_league_payload(name="L"), ADMIN)
    league = validate_success(res, 201)
    assert league["status"] == "SETUP"


def test_get_league_not_found(api):
    """PRD §2.7: "A reference to a resource that does not exist — whether named in
    the path or the body — is rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/get_league_not_found_returns_404
    """
    res = api.get_league(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_list_leagues_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned" and
    "Every list response carries the pagination bookkeeping in the `meta` object:
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/list_leagues_pagination_envelope
    """
    api.create_league(create_league_payload(name="L1", sport="BASKETBALL"), ADMIN)
    api.create_league(create_league_payload(name="L2", sport="SOCCER"), ADMIN)
    data, meta = validate_paginated(api.list_leagues(ADMIN, params={"limit": 1, "offset": 0}))
    assert len(data) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True


def test_create_official_missing_required_field(api):
    """PRD §2.9: "structural input validity — required fields present, enums
    recognized, numeric ranges respected — is the last gate, surfacing
    `ERR_INVALID_REQUEST`."
    PRD §3.1: "a home location given as `home_lat` and `home_lon` (decimal degrees,
    used for travel-radius math)".

    Design: Corner/entities/create_official_missing_required_field_returns_invalid_request
    """
    league = validate_success(api.create_league(create_league_payload(), ADMIN), 201)
    payload = {"league_id": league["id"], "full_name": "O", "home_lon": -75.0}
    res = api.create_official(payload, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_official_defaults(api):
    """PRD §3.1: "an optional `max_travel_miles` cap (defaulting to 50)" and
    "The official's `rank` may be supplied and defaults to `ROOKIE`" and
    "Every official starts with a `status` of `ACTIVE`".

    Design: Corner/entities/create_official_defaults_rank_rookie_status_active
    """
    league = validate_success(api.create_league(create_league_payload(sport="SOCCER"), ADMIN), 201)
    res = api.create_official(create_official_payload(league["id"]), ADMIN)
    official = validate_success(res, 201)
    assert official["rank"] == "ROOKIE"
    assert official["status"] == "ACTIVE"
    assert official["max_travel_miles"] == 50


def test_official_computed_fields_initial_values(api):
    """PRD §3.1: "Several official fields are read-only and maintained by the
    system: `games_worked_count` (the number of this official's assignments that
    reached `COMPLETED` this season), `noshow_count` (the count that reached
    `NO_SHOW`), `penalty_points` (the running penalty total from declines and
    no-shows, mirroring the season ledger), `mean_rating` (the mean evaluation
    score over completed assignments, carried to two decimals, null when no
    evaluations exist), `reliability_score` (a denormalized gauge, described in
    §3.7)".
    PRD §3.7: "It is 100 minus the season ledger's `penalty_points`, floored at 0".

    Design: Corner/entities/official_computed_fields_initial_values
    """
    league = validate_success(api.create_league(create_league_payload(sport="HOCKEY"), ADMIN), 201)
    league = validate_success(api.activate_league(league["id"], ADMIN), 200)
    official = validate_success(api.create_official(create_official_payload(league["id"]), ADMIN), 201)
    fetched = validate_success(api.get_official(official["id"], ADMIN), 200)
    assert fetched["games_worked_count"] == 0
    assert fetched["penalty_points"] == 0
    assert fetched["reliability_score"] == 100
    assert fetched["mean_rating"] is None


def test_create_official_invalid_rank_enum_rejected(api):
    """PRD §2.9: "structural input validity — required fields present, enums
    recognized, numeric ranges respected — is the last gate, surfacing
    `ERR_INVALID_REQUEST`."
    PRD §3.1: "the rank ladder runs `ROOKIE`, `CERTIFIED`, `SENIOR`, `MASTER`".

    Design: Corner/entities/create_official_invalid_enum_rank_rejected
    """
    league = validate_success(api.create_league(create_league_payload(), ADMIN), 201)
    res = api.create_official(
        create_official_payload(league["id"], rank="GRANDMASTER"), ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_create_official_wrong_parent_league_not_found(api):
    """PRD §2.7: "A reference to a resource that does not exist — whether named in
    the path or the body — is rejected with `ERR_NOT_FOUND`."

    Design: Corner/entities/create_official_wrong_parent_league_returns_not_found
    """
    res = api.create_official(create_official_payload(NON_EXISTENT_UUID), ADMIN)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_availability_window_end_before_start_rejected(api):
    """PRD §3.2: "the end must be strictly later than the start; a window whose
    `window_end_utc` is not strictly after its `window_start_utc` is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/availability_window_end_before_start_rejected
    """
    league = validate_success(api.create_league(create_league_payload(sport="SOCCER"), ADMIN), 201)
    official = validate_success(api.create_official(create_official_payload(league["id"]), ADMIN), 201)
    res = api.create_availability(create_availability_payload(
        official["id"],
        window_start_utc="2026-06-20T20:00:00Z",
        window_end_utc="2026-06-20T18:00:00Z"),
        make_official_headers(official["id"]))
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)


def test_conflict_declaration_immutable_no_version(api):
    """PRD §2.4: "a `ConflictDeclaration` and an `Evaluation` are immutable once
    written, so each carries only `id` and `created_at` — they have neither an
    `updated_at` field nor a `version` field, and they are never the target of an
    update or a concurrency check."

    Design: Corner/entities/conflict_declaration_immutable_id_created_at_only
    """
    league = validate_success(api.create_league(create_league_payload(), ADMIN), 201)
    official = validate_success(api.create_official(create_official_payload(league["id"]), ADMIN), 201)
    res = api.create_conflict_declaration(create_conflict_declaration_payload(
        official["id"], scope="TEAM", team_name="Hawks"), ADMIN)
    declaration = validate_success(res, 201)
    assert_conflict_declaration(declaration)
    assert declaration.get("id")
    assert "version" not in declaration


def test_conflict_declaration_team_scope_missing_team_name_rejected(api):
    """PRD §3.2: "A scope that does not match the field supplied — a `TEAM` scope
    without a `team_name`, or an `OFFICIAL` scope without a `peer_official_id` — is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/errors/conflict_declaration_team_scope_missing_team_name_rejected
    """
    league = validate_success(api.create_league(create_league_payload(), ADMIN), 201)
    official = validate_success(api.create_official(create_official_payload(league["id"]), ADMIN), 201)
    res = api.create_conflict_declaration(
        {"official_id": official["id"], "scope": "TEAM"}, ADMIN)
    validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)
