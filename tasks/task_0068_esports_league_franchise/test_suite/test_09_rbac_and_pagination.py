"""Role-based access control and list pagination.

Covers corner queue sections `rbac` and `endpoints`.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_season, create_team, create_player, sign_contract, team_version,
    create_fine_payload,
    build_user_headers, make_team_gm_headers, TEST_USERS,
)

COMMISH = TEST_USERS["commissioner_headers"]


def test_team_gm_cannot_assess_fine(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN_ROLE
    (HTTP 403)." PRD §2.1: "The commissioner ... assesses and waives fines".

    Design: Corner/rbac/team_gm_cannot_assess_fine
    """
    season = create_season()
    team = create_team(season["id"], name="T", market_size_weight=1)
    player = create_player(season["id"], handle="p")
    sign_contract(team["id"], player["id"], base_salary_cents=5_000_000, contract_type="STANDARD")
    res = api.create_fine(
        create_fine_payload(team["id"], player["id"], amount_cents=50_000, penalty_points=1),
        make_team_gm_headers(team["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE")


def test_team_gm_cannot_waive_other_teams_contract(api):
    """PRD §2.1: "When a TeamGM attempts to mutate a resource that does not belong to the
    team whose id equals X-User-ID — waiving or promoting another team's contract ... —
    the request is rejected with ERR_NOT_TEAM_OWNER (HTTP 403)."

    Design: Corner/rbac/team_gm_cannot_waive_other_teams_contract
    """
    season = create_season()
    a = create_team(season["id"], name="A", market_size_weight=1)
    b = create_team(season["id"], name="B", market_size_weight=1)
    pb = create_player(season["id"], handle="pb")
    c = sign_contract(b["id"], pb["id"], base_salary_cents=5_000_000, contract_type="STANDARD")
    b_v = team_version(b["id"])
    # GM of team A tries to waive team B's contract.
    res = api.waive_contract(c["id"], {"expected_team_version": b_v},
                             make_team_gm_headers(a["id"]))
    validate_error(res, "ERR_NOT_TEAM_OWNER")


def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if X-User-Role is not one of the two
    recognized role names, the request is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    headers = build_user_headers("someone", "Anonymous")
    res = api.create_season({"name": "S", "salary_cap_cents": 50_000_000}, headers)
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_list_teams_pagination_envelope(api):
    """PRD §2.3: "The meta block of a list response carries the pagination fields limit,
    offset, total_count (the total number of records matching the query before the page
    window is applied), and has_more (true when records remain beyond the current
    window)."

    Design: Corner/endpoints/list_teams_pagination_envelope
    """
    season = create_season()
    create_team(season["id"], name="A", market_size_weight=1)
    create_team(season["id"], name="B", market_size_weight=1)
    res = api.list_teams(COMMISH, params={"season_id": season["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_list_teams_limit_over_max_returns_validation(api):
    """PRD §2.3: "The limit defaults to 10, with a minimum of 1 and a maximum of 100 ...
    A limit or offset outside these bounds is a malformed request and is rejected with
    ERR_VALIDATION (HTTP 400)."

    Design: Corner/endpoints/list_teams_limit_over_max_returns_validation
    """
    res = api.list_teams(COMMISH, params={"limit": 101})
    validate_error(res, "ERR_VALIDATION")
