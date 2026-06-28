"""RBAC role denials, ownership violations, and authentication.

Translates queue-B corner instances in section `rbac`.
"""
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_member_headers,
    fixtures,
)

MGR = TEST_USERS["studio_manager_headers"]


def test_member_cannot_create_studio_forbidden(api):
    """PRD 2.1: "A request whose role is well-formed but not permitted for the
    targeted operation is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD 4: POST /studios is authorized for StudioManager only.

    Design: Corner/rbac/member_cannot_create_studio_forbidden
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    studio = fixtures.create_studio(name="Seed")
    member = fixtures.register_member(studio["id"])
    resp = api.create_studio(
        {"name": "Hacker Studio", "city": "NYC"}, make_member_headers(member["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_member_cannot_check_in_forbidden_role(api):
    """PRD 2.1: "A request whose role is well-formed but not permitted for the
    targeted operation is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD 4: the check-in endpoint is authorized for Instructor only.

    Design: Corner/rbac/member_cannot_check_in_others_reservation_forbidden
    """
    ctx = fixtures.setup_booked_reservation(
        n_bikes=1,
        start_utc="2026-06-02T10:00:00Z",
        end_utc="2026-06-02T11:00:00Z",
    )
    fixtures.set_clock("2026-06-02T10:30:00Z")
    # Member attempts a check-in (an Instructor-exclusive operation).
    resp = api.check_in_reservation(
        ctx["studio"]["id"],
        ctx["session"]["id"],
        ctx["reservation"]["id"],
        make_member_headers(ctx["member"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, expected_status=403)


def test_member_cannot_cancel_other_members_reservation_ownership(api):
    """PRD 2.1: "A member may therefore act only on their own reservations, their own
    credit packs, their own waitlist entries, and their own retail and penalty records."
    PRD 2.1: "A violation of either ownership rule is rejected with
    `ERR_OWNERSHIP_VIOLATION`."

    Design: Corner/rbac/member_cannot_cancel_other_members_reservation_ownership
    """
    estate = fixtures.setup_studio_estate(n_bikes=1)
    studio_id = estate["studio"]["id"]
    member_a, _ = fixtures.setup_member_with_pack(studio_id, email="ma@x.com", full_name="Mem A")
    member_b = fixtures.register_member(studio_id, email="mb@x.com", full_name="Mem B")
    session = fixtures.create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"]
    )
    res_a = fixtures.book(
        studio_id, session["id"], member_a["id"], estate["bikes"][0]["id"], session["version"]
    )
    # Member B (well-formed Member role) tries to cancel member A's reservation.
    resp = api.cancel_reservation(
        studio_id, session["id"], res_a["id"], make_member_headers(member_b["id"])
    )
    validate_error(resp, ApiErrorId.ERR_OWNERSHIP_VIOLATION.value, expected_status=403)


def test_missing_auth_returns_unauthenticated(api):
    """PRD 2.1: "A request that omits either header, or supplies a malformed one, on a
    protected endpoint is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_auth_returns_unauthenticated
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    fixtures.create_studio()
    # No X-User-ID / X-User-Role headers on a protected list endpoint.
    resp = api.list_studios(headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401)
