"""Role authorization, ownership enforcement, and authentication."""
from test_helpers import (
    validate_error, TEST_USERS,
    create_membership, grant_loyalty, make_member_headers, make_anonymous_headers,
)

MGR = TEST_USERS["manager_headers"]
STAFF = TEST_USERS["staff_headers"]


# ─── Corner/rbac/rbac_staff_cannot_create_table_returns_unauthorized ───────
def test_staff_cannot_create_table(api):
    """PRD §2.1: "If the headers are well-formed but the role is not permitted to invoke the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/rbac_staff_cannot_create_table_returns_unauthorized
    """
    res = api.create_table(
        {"label": "X", "seats": 4, "half_hour_rate_cents": 0, "day_pass_cents": 0,
         "cover_fee_cents": 0, "min_spend_cents": 0}, STAFF)
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner/rbac/rbac_member_cannot_create_tournament_returns_unauthorized ─
def test_member_cannot_create_tournament(api):
    """PRD §2.1: "If the headers are well-formed but the role is not permitted to invoke the
    requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/rbac_member_cannot_create_tournament_returns_unauthorized
    """
    member = create_membership(api, email="mem@x.com", full_name="Mem")
    res = api.create_tournament(
        {"name": "Nope", "game_title": "Chess", "format": "CASUAL", "capacity": 4,
         "entry_fee_cents": 0, "start_at": "2026-07-20T18:00:00Z"},
        make_member_headers(member["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner/rbac/rbac_member_redeem_other_member_returns_unauthorized ──────
def test_member_cannot_redeem_other_members_points(api):
    """PRD §2.1: "When a `Member` attempts to mutate a reservation, registration, redemption,
    or retail order whose `membership_id` does not equal its `X-User-ID`, the request is
    rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/rbac_member_redeem_other_member_returns_unauthorized
    """
    member_a = create_membership(api, email="a2@x.com", full_name="A2")
    member_b = create_membership(api, email="b2@x.com", full_name="B2")
    grant_loyalty(api, member_b["id"], 500, "grant")
    res = api.redeem(member_b["id"], {"points_cost": 100, "reward_description": "Steal"},
                     make_member_headers(member_a["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


# ─── Corner/rbac/unauthenticated_missing_headers_returns_401 ───────────────
def test_unknown_role_returns_unauthenticated(api):
    """PRD §2.1: "The role must be exactly one of `Manager`, `Staff`, or `Member`. If either
    header is missing, or the role is not one of these three values, the request is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_missing_headers_returns_401
    """
    res = api.list_tables(make_anonymous_headers())
    validate_error(res, "ERR_UNAUTHENTICATED")
