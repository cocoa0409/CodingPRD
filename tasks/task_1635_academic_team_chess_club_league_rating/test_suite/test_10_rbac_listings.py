"""RBAC, validation-ladder ordering, auth headers, and list/pagination claims
(PRD §2.1, §2.3, §2.9, §2.10, §3.1, §4)."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_active_season,
    create_club,
    create_coach,
    create_player,
    create_player_payload,
    create_season,
    create_season_payload,
    setup_one_club,
    setup_two_club_league,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["federation_admin_headers"]

def test_missing_auth_header_returns_400(api):
    """PRD §2.10: "Presence of the authentication headers — a missing or empty
    `X-User-ID` or `X-User-Role` yields
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."
    PRD §2.1: "A request in which either header is missing or empty is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/errors/missing_auth_header_returns_400
    """
    res = api.list_seasons(headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

def test_rbac_coach_cannot_create_season(api):
    """PRD §2.1: "Access to each operation is further restricted by role; an attempt to
    perform an action outside of the caller's designated role is rejected with
    `ERR_INSUFFICIENT_PERMISSIONS`."
    PRD §4 assigns POST /api/seasons to "FederationAdmin" only.

    Design: Corner/rbac/rbac_coach_cannot_create_season
    """
    coach_headers = build_user_headers("00000000-0000-0000-0000-000000000001", "ClubCoach")
    res = api.create_season(create_season_payload(), coach_headers)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

def test_validation_role_precedes_existence(api):
    """PRD §2.10: "Every request is evaluated against a fixed ladder of checks, and the
    first failing rung determines the error returned." Rung 2 is "Role permission —
    the caller's role must be listed for the endpoint, otherwise
    `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)"; rung 3 is "Path identifiers resolve,
    left to right — otherwise `ERR_NOT_FOUND` (HTTP 404)".

    Design: Corner/validations/validation_role_precedes_existence
    """
    coach_headers = build_user_headers("00000000-0000-0000-0000-000000000001", "ClubCoach")
    # FederationAdmin-only endpoint + nonexistent path id: the role rung fails first.
    res = api.activate_season(NON_EXISTENT_UUID, coach_headers)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert res.status_code == 403, "role (403) precedes existence (404)"

def test_validation_existence_precedes_state(api, federation_admin_headers):
    """PRD §2.10: rung 3 "Path identifiers resolve, left to right — otherwise
    `ERR_NOT_FOUND` (HTTP 404)" precedes rung 8 "State checks".

    Design: Corner/validations/validation_existence_precedes_state
    """
    res = api.complete_meet(NON_EXISTENT_UUID, federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)

def test_rbac_coach_other_club_player_forbidden(api):
    """PRD §2.1: "A `ClubCoach` therefore operates only within the scope of their own
    club: its players, its memberships, meets in which the club is host or away,
    entries of its own players, disputes on its own meets, and bids issued to the
    club."
    PRD §2.10: "Entity-backed ownership — a `ClubCoach` acting outside their club's
    scope, a `Proctor` confirming another coach's assignment, or a coach withdrawing a
    dispute they did not raise yields `ERR_FORBIDDEN_RESOURCE_OWNERSHIP` (HTTP 403)."

    Design: Corner/rbac/rbac_coach_other_club_player_forbidden
    """
    ctx = setup_two_club_league()
    res = api.create_player(
        create_player_payload(ctx["club_b"]["id"], full_name="Poach", grade_level=9),
        build_user_headers(ctx["coach_a"]["id"], "ClubCoach"),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN_RESOURCE_OWNERSHIP)

def test_rbac_all_roles_can_list_seasons(api):
    """PRD §4: "In the table below, "All roles" means all five roles defined in §2.1."
    and GET /api/seasons is listed for "All roles".
    PRD §2.1: "The system recognizes five distinct roles: `FederationAdmin`,
    `ClubCoach`, `Proctor`, `Treasurer`, and `Auditor`."

    Design: Corner/rbac/rbac_all_roles_can_list_seasons
    """
    create_season()
    callers = [
        TEST_USERS["federation_admin_headers"],
        build_user_headers("00000000-0000-0000-0000-000000000002", "ClubCoach"),
        build_user_headers("00000000-0000-0000-0000-000000000002", "Proctor"),
        TEST_USERS["treasurer_headers"],
        TEST_USERS["auditor_headers"],
    ]
    for headers in callers:
        res = api.list_seasons(headers)
        body = res.json()
        assert res.status_code == 200, f"role {headers['X-User-Role']} may list seasons"
        assert body["response_type"] == "array"
        assert body["meta"]["total_count"] == 1

def test_clubs_list_pagination_defaults(api, auditor_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of
    100. The `offset` parameter specifies the number of items to skip and defaults to
    0."
    PRD §2.3: "Paginated list responses include the following fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/endpoints/clubs_list_pagination_defaults
    """
    season = create_season()
    for i in range(12):
        create_club(season["id"], name=f"C{i + 1:02d}")

    page1, meta1 = validate_paginated(
        api.list_clubs(auditor_headers, params={"season_id": season["id"]})
    )
    assert len(page1) == 10, "default limit is 10"
    assert meta1["limit"] == 10 and meta1["offset"] == 0
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_clubs(auditor_headers,
                       params={"season_id": season["id"], "limit": 10, "offset": 10})
    )
    assert len(page2) == 2
    assert meta2["has_more"] is False
    assert {c["id"] for c in page1}.isdisjoint({c["id"] for c in page2})

def test_players_filtered_list_subset(api, federation_admin_headers):
    """PRD §3.1: "The players list filters by `club_id`, `status`, and
    `is_provisional`."

    Design: Corner/endpoints/players_filtered_list_subset
    """
    ctx = setup_two_club_league(players_a=[{}, {}], players_b=[{}], waive=False)
    p1, p2 = ctx["players_a"]
    validate_success(api.deactivate_player(p2["id"], federation_admin_headers))

    club_a_players, meta = validate_paginated(
        api.list_players(federation_admin_headers, params={"club_id": ctx["club_a"]["id"]})
    )
    assert meta["total_count"] == 2
    assert {p["id"] for p in club_a_players} == {p1["id"], p2["id"]}

    active_only, meta2 = validate_paginated(
        api.list_players(federation_admin_headers,
                         params={"club_id": ctx["club_a"]["id"], "status": "ACTIVE"})
    )
    assert meta2["total_count"] == 1
    assert active_only[0]["id"] == p1["id"]

def test_club_reinstate_when_not_suspended_rejected(api, federation_admin_headers):
    """PRD §3.1: "Suspension is permitted from either `GOOD_STANDING` or `DELINQUENT`;
    reinstatement returns the club to `GOOD_STANDING`, except that a club whose balance
    is still negative after reinstatement lands in `DELINQUENT` instead. Calling
    suspend or reinstate from any other state is rejected with
    `ERR_CLUB_INVALID_STATE`."

    Design: Corner/errors/club_reinstate_when_not_suspended_rejected
    """
    season = create_active_season()
    club = create_club(season["id"], name="Alpha")
    assert club["status"] == "GOOD_STANDING"
    res = api.reinstate_club(club["id"], federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_CLUB_INVALID_STATE)

def test_coach_double_deactivate_rejected(api, federation_admin_headers):
    """PRD §3.1: "Deactivation moves a coach to `INACTIVE` and, as a cascade, releases
    every proctor assignment still `ASSIGNED` to that coach; reactivation restores
    `ACTIVE`. Either transition attempted from the wrong state fails with
    `ERR_COACH_INVALID_STATE`."

    Design: Corner/errors/coach_double_deactivate_rejected
    """
    ctx = setup_one_club()
    coach = ctx["coach"]
    validate_success(api.deactivate_coach(coach["id"], federation_admin_headers))
    res = api.deactivate_coach(coach["id"], federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_COACH_INVALID_STATE)

def test_player_double_deactivate_rejected(api, federation_admin_headers):
    """PRD §3.1: "A player begins `ACTIVE`; a coach of the club or the administrator may
    deactivate to `INACTIVE` and reactivate back, while only the administrator may
    suspend a player from either `ACTIVE` or `INACTIVE`."
    PRD §3.1: "Wrong-state calls fail with `ERR_PLAYER_INVALID_STATE`."

    Design: Corner/errors/player_double_deactivate_rejected
    """
    ctx = setup_one_club()
    player = create_player(ctx["club"]["id"], full_name="P")
    validate_success(api.deactivate_player(player["id"], federation_admin_headers))
    res = api.deactivate_player(player["id"], federation_admin_headers)
    validate_error(res, ApiErrorId.ERR_PLAYER_INVALID_STATE)
