"""Cross-cutting API surface: authentication, validation priority, RBAC
denials and read allowance, pagination envelope, and list filtering
(PRD §2.1, §2.3, §2.5, §2.8, §3.4)."""
from test_helpers import (
    COORDINATOR,
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    create_league,
    create_locker,
    create_member,
    create_official,
    declare_forfeit,
    make_member_headers,
    make_staff_headers,
    open_league_context,
    register_teams,
    schedule_game,
    season_context,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_request_missing_auth_headers_returns_unauthenticated():
    """PRD §2.1: "Every request carries two headers: `X-User-ID` and
    `X-User-Role`. If either header is missing or empty, or if `X-User-Role`
    is not one of the five declared roles, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.8: "When a request fails multiple checks, the error returned is
    determined by a fixed priority order — lower priority number wins."
    (authentication is priority 1, ahead of request shape.)

    Design: Corner/validations/request_missing_auth_headers_returns_unauthenticated
    """
    # No auth headers at all, with an otherwise-malformed body: the 401 wins.
    resp = api_client.create_member({}, headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_existence_precedes_shape_on_nested_write():
    """PRD §2.8: "When a request fails multiple checks, the error returned is
    determined by a fixed priority order — lower priority number wins."
    (existence is priority 3, ahead of request shape at priority 4.)
    PRD §2.6: "Path resource identifiers are validated for existence left to
    right; a missing path resource yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/existence_precedes_shape_on_nested_write
    """
    # Nonexistent member id AND a body missing the required term field; the
    # caller's X-User-ID matches the path id so the ownership gate passes.
    resp = api_client.create_membership(
        NON_EXISTENT_UUID, {}, make_member_headers(NON_EXISTENT_UUID),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_member_role_cannot_create_league():
    """PRD §2.1: "If the role is valid but not permitted for the endpoint — or
    an entity-backed ownership check fails — the request is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "POST /v1/leagues | Create a league (DRAFT) with divisions |
    RecAdmin".

    Design: Corner/validations/member_role_cannot_create_league
    """
    member = create_member("mm@x.edu", full_name="Mem M")
    resp = api_client.create_league(
        {
            "name": "X", "sport": "SOCCER",
            "divisions": [{"name": "A", "capacity": 2, "skill_min": 1,
                           "skill_max": 10}],
            "registration_open_at": "2026-08-20T00:00:00Z",
            "registration_close_at": "2026-09-05T00:00:00Z",
            "season_start_at": "2026-09-07T00:00:00Z",
            "season_end_at": "2026-12-04T00:00:00Z",
            "team_capacity": 2, "min_teams": 2, "roster_min": 1,
            "roster_max": 2,
        },
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_non_self_membership_purchase_forbidden():
    """PRD §2.1: "A member may sign their own waiver, purchase memberships,
    pay fines, register as a free agent, register for classes, check out
    equipment, and rent lockers — all self-service only."
    PRD §2.8: "**Authorization and ownership** (`ERR_FORBIDDEN`): role
    permitted for the endpoint; entity-backed ownership checks (a `Member`
    caller's `X-User-ID` must equal the path or body `member_id`; roster and
    score-report callers must be the team's captain; registration, checkout,
    locker, fine-payment, waiver, and membership actions are self-service; a
    `Staff` caller must be the assignment's official or the class's
    instructor)."

    Design: Corner/validations/non_self_membership_purchase_forbidden
    """
    member_a = create_member("a@x.edu", full_name="M A")
    member_b = create_member("b@x.edu", full_name="M B")
    # Member B on member A's path: ownership (priority 2) fires before the
    # version guard is ever reached.
    resp = api_client.create_membership(
        member_a["id"],
        {"term": "FALL_2026",
         "expected_member_version": member_a["version"]},
        make_member_headers(member_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_pagination_envelope_on_teams_list():
    """PRD §2.3: "List endpoints accept `limit` and `offset` query parameters.
    `limit` defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
    defaults to 0. Results are sorted by `created_at` ascending. The `meta`
    envelope of a list response includes `limit`, `offset`, `total_count`, and
    `has_more`, in addition to the standard request identifiers."

    Design: Corner/endpoints/pagination_envelope_on_teams_list
    """
    ctx = open_league_context()
    register_teams(ctx["league"]["id"], 3, add_captain_entry=False)
    page_1, meta_1 = validate_paginated(api_client.list_teams(
        COORDINATOR,
        params={"league_id": ctx["league"]["id"], "limit": 2, "offset": 0}))
    assert len(page_1) == 2
    assert meta_1["total_count"] == 3
    assert meta_1["has_more"] is True
    assert meta_1["limit"] == 2
    assert meta_1["offset"] == 0
    page_2, meta_2 = validate_paginated(api_client.list_teams(
        COORDINATOR,
        params={"league_id": ctx["league"]["id"], "limit": 2, "offset": 2}))
    assert len(page_2) == 1
    assert meta_2["total_count"] == 3
    assert meta_2["has_more"] is False
    assert page_1[0]["id"] != page_2[0]["id"]


def test_filtered_list_status_isolation():
    """PRD §2.3: "List endpoints also accept the filter parameters named
    against each of them in §4 (for example, listing memberships may be
    narrowed by `member_id`, `term`, `status`, or `supersedes_membership_id`;
    games by `league_id`, `facility_id`, `home_team_id`, `away_team_id`,
    `status`, `bracket_round`, `next_game_id`, or `forfeiting_team_id`; ...)."

    Design: Corner/endpoints/filtered_list_status_isolation
    """
    set_clock("2026-08-24T00:00:00Z")
    ctx = season_context(num_teams=2)
    g1 = schedule_game(ctx["league"]["id"], ctx["teams"][0]["id"],
                       ctx["teams"][1]["id"], ctx["facility"]["id"],
                       "2026-09-08T18:00:00Z", "2026-09-08T19:30:00Z")
    schedule_game(ctx["league"]["id"], ctx["teams"][0]["id"],
                  ctx["teams"][1]["id"], ctx["facility"]["id"],
                  "2026-09-10T18:00:00Z", "2026-09-10T19:30:00Z")
    set_clock("2026-09-08T18:30:00Z")
    declare_forfeit(g1["id"], ctx["teams"][0]["id"])

    games, meta = validate_paginated(api_client.list_games(
        COORDINATOR,
        params={"league_id": ctx["league"]["id"], "status": "FORFEITED"}))
    assert meta["total_count"] == 1
    assert games[0]["id"] == g1["id"]
    _, meta_all = validate_paginated(api_client.list_games(
        COORDINATOR, params={"league_id": ctx["league"]["id"]}))
    assert meta_all["total_count"] == 2


def test_member_and_staff_can_read_any_get_endpoint():
    """PRD §2.1: "All five roles may call every read endpoint. Write
    authorization per endpoint is enumerated in §4."

    Design: Corner/rbac/member_cannot_access_admin_reads_denied_none
    """
    league = create_league()
    locker = create_locker(locker_number=101, size="M")
    member = create_member("mm@x.edu", full_name="Mem M")
    official = create_official(rate=2000, cert=1)
    league_read = validate_success(api_client.get_league(
        league["id"], make_member_headers(member["id"])))
    assert league_read["name"] == "Hoops"
    locker_read = validate_success(api_client.get_locker(
        locker["id"], make_staff_headers(official["id"])))
    assert locker_read["status"] == "AVAILABLE"
