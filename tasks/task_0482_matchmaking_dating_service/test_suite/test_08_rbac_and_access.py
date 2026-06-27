"""Role-based access control, authentication, pagination, and party-scoped actions."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    make_member_headers,
    no_auth_headers,
    ApiErrorId,
    fixtures as fx,
)
import test_helpers.factories as f

ADMIN = TEST_USERS["billing_admin_headers"]
SCREENING = TEST_USERS["screening_officer_headers"]
MATCHMAKER = TEST_USERS["matchmaker_headers"]


def test_member_cannot_create_introduction(api):
    """PRD §3.4: "Suggesting an introduction is a `Matchmaker` action". PRD §2.1: "When
    the headers are well-formed but the declared role is not permitted to perform the
    requested operation ... the request is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/member_cannot_create_introduction
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    plan = fx.create_plan()
    member_a, _ = fx.create_active_member(plan["id"], "ca13@x.com", gender="MALE", with_preferences=False)
    member_b = fx.register_prospect("cb13@x.com", gender="FEMALE")
    a_id = member_a["id"]

    a_ver = fx.current_version(a_id)
    resp = api.create_introduction(
        f.create_introduction_payload(a_id, member_b["id"], a_ver), make_member_headers(a_id)
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)


def test_member_cannot_respond_on_others_introduction(api):
    """PRD §2.1: "A `Member` may act only on their own introductions, feedback,
    preferences, dates, coaching sessions, and background checks; acting on a resource
    owned by a different member is an `ERR_FORBIDDEN`."
    PRD §2.1: "For introduction-scoped actions a member is considered an owner when their
    `id` is one of the two parties to the introduction." Ownership (class 2,
    ERR_FORBIDDEN) is evaluated before referential integrity per §2.8.

    Design: Corner/rbac/member_cannot_respond_on_others_introduction
    """
    ctx = fx.setup_suggested_introduction(a_email="ca14@x.com", b_email="cb14@x.com")
    intro_id = ctx["introduction"]["id"]
    # A third, unrelated member.
    member_c = fx.register_prospect("cc14@x.com", gender="MALE")

    resp = api.respond_introduction(
        intro_id, f.respond_introduction_payload("ACCEPTED", ctx["introduction"]["version"]),
        make_member_headers(member_c["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, 403)


def test_unauthenticated_request_rejected(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/unauthenticated_request_rejected
    """
    resp = api.create_plan(
        f.create_plan_payload(tier="BASIC", monthly_fee_cents=9000, term_months=3,
                              guaranteed_introductions=4, included_coaching_sessions=2,
                              coaching_value_cents=4000, background_check_addon_cents=2000),
        no_auth_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_list_members_pagination_envelope(api):
    """PRD §2.3: "Every list-based response carries the following fields inside the `meta` object: `limit`, `offset`, `total_count`, and `has_more`." PRD §2.2: response_type is
    "array for a list of resources."

    Design: Corner/endpoints/list_members_pagination_envelope
    """
    fx.register_prospect("pg1@x.com", gender="MALE")
    fx.register_prospect("pg2@x.com", gender="FEMALE")

    resp = api.list_members(MATCHMAKER, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    body = resp.json()
    assert body["response_type"] == "array", f"expected array, got {body['response_type']}"
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"limit 1 of 2 => has_more true, got {meta['has_more']}"

# Corner/endpoints/feedback_by_non_party_rejected is SKIPPED:
# The instance has author_member_id == the acting X-User-ID of a non-party member, so
# PRD §2.8's precedence makes the ownership check (class 2, ERR_FORBIDDEN) fire BEFORE
# the referential party check (class 6, ERR_NOT_INTRODUCTION_PARTY). A faithful
# PRD-only reader would therefore return ERR_FORBIDDEN, not the asserted
# ERR_NOT_INTRODUCTION_PARTY — the expected outcome is not uniquely derivable.
