"""Access control, ownership, and resource retrieval.

Covers role denial / authentication, entity-backed ownership checks, the
PartnerOperator settle path, not-found existence checks, and paginated listing.
"""
from test_helpers import (
    TEST_USERS,
    get_success_data,
    validate_error,
    validate_paginated,
    set_clock,
    setup_program,
    register_member,
    post_purchase,
    get_member,
    member_version,
    add_partner,
    create_program,
    define_tiers,
    add_reward,
    make_member_headers,
    make_partner_operator_headers,
    anonymous_headers,
    create_partner_transfer_payload,
    redemption_line,
    ApiErrorId,
    NON_EXISTENT_UUID,
    STANDARD_ONLY,
)

ADMIN = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# RBAC: role denial
# ---------------------------------------------------------------------------
def test_member_cannot_define_tier(api):
    """PRD 2.1: "When the headers are present but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Defining a tier is a ProgramAdmin-exclusive operation; a Member calling it is
    rejected with ERR_FORBIDDEN.

    Design: Corner/rbac/member_cannot_define_tier_returns_403
    """
    base = setup_program()
    prog = base["program"]
    member = register_member(prog["id"])
    resp = api.create_tier(prog["id"], {
        "program_id": prog["id"], "code": "GOLD", "qualify_threshold": 5000,
        "earn_multiplier": 1.5, "transfer_ratio": 0.8, "rank": 2},
        make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_missing_auth_headers_rejected(api):
    """PRD 2.1: "A request that omits or malforms either header on a protected endpoint is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    A protected call carrying no auth headers is rejected with ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_returns_401
    """
    prog = create_program()
    resp = api.create_tier(prog["id"], {
        "program_id": prog["id"], "code": "STANDARD", "qualify_threshold": 0,
        "earn_multiplier": 1.0, "transfer_ratio": 0.5, "rank": 0},
        anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_member_cannot_redeem_for_another_member(api):
    """PRD 2.1: "A member acting on a resource that belongs to a different member is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Member A opening a redemption whose member_id is Member B is rejected with
    ERR_NOT_RESOURCE_OWNER.

    Design: Corner/rbac/member_cannot_redeem_for_another_member_returns_403
    """
    base = setup_program()
    prog = base["program"]
    reward = add_reward(prog["id"], point_cost=100, stock=5)
    a = register_member(prog["id"], email="a@x.com", full_name="A")
    b = register_member(prog["id"], email="b@x.com", full_name="B", birth_month_day="04-20")
    post_purchase(b["id"], 100000)
    resp = api.create_redemption(
        {"member_id": b["id"], "lines": [redemption_line(reward["id"], 1)]},
        make_member_headers(a["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_partner_operator_settles_own_transfer(api):
    """PRD 3.8: "A submitted transfer reaches its terminal `SETTLED` status when the partner's operator settles it; settlement is legal only from `SUBMITTED` and only while the partner account is `ACTIVE`, after which the partner credits the converted points externally."

    A PartnerOperator acting as their own partner account settles a SUBMITTED
    transfer: 200 and status SETTLED.

    Design: Corner/rbac/partner_operator_settle_own_transfer_succeeds
    """
    base = setup_program()
    prog = base["program"]
    partner = add_partner(prog["id"], transfer_block_size=100, min_transfer_points=100)
    set_clock("2026-03-01T00:00:00Z")
    member = register_member(prog["id"])
    post_purchase(member["id"], 50000)   # 500 points
    v = member_version(member["id"])
    xfer = get_success_data(api.create_partner_transfer(
        create_partner_transfer_payload(member["id"], partner["id"], 500, v), ADMIN))
    # PartnerOperator identity is the PartnerAccount id (ownership-gated).
    resp = api.settle_transfer(xfer["id"], make_partner_operator_headers(partner["id"]))
    settled = get_success_data(resp)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert settled["status"] == "SETTLED", f"Expected SETTLED, got {settled['status']}"


# ---------------------------------------------------------------------------
# Not found
# ---------------------------------------------------------------------------
def test_get_member_not_found(api):
    """PRD 2.6: "the server validates the path identifiers from left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier in the path that does not resolve to an existing resource."

    Design: Corner/entities/get_member_not_found_returns_404
    """
    create_program()
    resp = api.get_member(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Listing & pagination
# ---------------------------------------------------------------------------
def test_list_members_filtered_by_program_paginated(api):
    """PRD 2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."

    Listing members filtered by program returns the member array with pagination
    meta exposing total_count and has_more.

    Design: Corner/entities/list_members_filtered_by_program_paginated
    """
    base = setup_program()
    prog = base["program"]
    member = register_member(prog["id"])
    data, meta = validate_paginated(
        api.list_members(ADMIN, params={"program_id": prog["id"], "limit": 10, "offset": 0}))
    assert any(m["id"] == member["id"] for m in data), "expected the registered member in the list"
    assert "total_count" in meta and "has_more" in meta


def test_pagination_limit_out_of_bounds_rejected(api):
    """PRD 2.3: "A request whose `limit` is below 1 or above 100, or whose `offset` is below 0, is rejected with `ERR_VALIDATION_LIMIT` (HTTP 422)."

    Listing members with limit 0 is rejected with ERR_VALIDATION_LIMIT.

    Design: Corner/entities/pagination_limit_out_of_bounds_returns_422
    """
    base = setup_program()
    resp = api.list_members(ADMIN, params={"program_id": base["program"]["id"], "limit": 0})
    validate_error(resp, ApiErrorId.ERR_VALIDATION_LIMIT.value)
