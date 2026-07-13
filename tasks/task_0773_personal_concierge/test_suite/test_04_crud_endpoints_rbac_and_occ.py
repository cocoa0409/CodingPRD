"""Entity CRUD, listing/retrieval endpoints, RBAC, and optimistic concurrency.

Corner queue: entities, endpoints, rbac, cross-cutting complexity layers.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_member_headers,
    setup_membership,
    intake_request,
    get_open_cycle,
    create_active_member,
    create_plan,
    create_membership_payload,
    log_time,
    api_client,
)

AM = TEST_USERS["account_manager_headers"]
AGENT = TEST_USERS["concierge_agent_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]


# ─── Corner/entities/member_create_returns_201_with_system_fields ───────────
def test_member_create_returns_pending_with_system_fields(api):
    """PRD §3.1: "A new member starts in `PENDING` status with `lifetime_billed_cents`
    initialized to zero."
    PRD §2.4: "The `version` field is an integer that begins at 1 on creation and
    increments by 1 on every mutation of the resource; it also underpins optimistic
    concurrency control where applicable."

    Design: Corner/entities/member_create_returns_201_with_system_fields
    """
    resp = api.create_member({"full_name": "Ann", "email": "ann@x.com"}, AM)
    member = validate_success(resp, expected_status=201)
    assert member["status"] == "PENDING", f"expected PENDING, got {member['status']}"
    assert member["lifetime_billed_cents"] == 0, f"expected 0, got {member['lifetime_billed_cents']}"
    assert member["version"] == 1, f"expected version 1, got {member['version']}"


# ─── Corner/entities/member_get_nonexistent_returns_not_found ───────────────
def test_get_nonexistent_member_returns_not_found(api):
    """PRD §2.8: "Existence of every referenced resource is checked next: all path and body
    identifiers are resolved left to right, and the first that does not exist yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/member_get_nonexistent_returns_not_found
    """
    resp = api.get_member(NON_EXISTENT_UUID, AM)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ─── Corner/entities/member_missing_email_returns_invalid_request ───────────
def test_member_missing_email_returns_invalid_request(api):
    """PRD §2.8: "Only then is the request body validated for well-formedness — required
    fields present, enums drawn from their legal sets, and numeric constraints satisfied —
    with any violation yielding `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/member_missing_email_returns_invalid_request
    """
    resp = api.create_member({"full_name": "NoEmail"}, AM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── Corner/endpoints/service_requests_list_pagination ──────────────────────
def test_service_requests_list_pagination(api):
    """PRD §2.3: "The `meta` object of a list response carries the pagination fields
    `limit`, `offset`, `total_count`, and `has_more`, where `total_count` is the total
    number of matching resources across all pages and `has_more` indicates whether further
    pages remain."

    Design: Corner/endpoints/service_requests_list_pagination
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    for title in ("a", "b", "c"):
        intake_request(ctx, category="ERRAND", title=title)
    resp = api.list_service_requests(AM, params={"membership_id": ctx["ms_id"], "limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 2, f"expected 2 rows, got {len(data)}"
    assert meta["total_count"] == 3, f"expected total_count 3, got {meta['total_count']}"
    assert meta["has_more"] is True, f"expected has_more True, got {meta['has_more']}"


# ─── Corner/endpoints/fk_reverse_time_entries_by_billing_cycle ──────────────
def test_time_entries_filtered_by_billing_cycle(api):
    """PRD §4: "Time entries may be filtered by `service_request_id`, `billing_cycle_id`,
    and `status`."
    PRD §3.5: "The entry is created in `FINALIZED` status."

    Design: Corner/endpoints/fk_reverse_time_entries_by_billing_cycle
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    cycle = get_open_cycle(ctx["ms_id"])
    sr = intake_request(ctx, category="ERRAND", title="t")
    te = log_time(sr["id"], 30)
    data, _ = validate_paginated(api.list_time_entries(FINANCE, params={"billing_cycle_id": cycle["id"]}))
    match = [t for t in data if t["id"] == te["id"]]
    assert match, f"time entry {te['id']} not returned for cycle {cycle['id']}"
    assert match[0]["minutes"] == 30, f"expected minutes 30, got {match[0]['minutes']}"
    assert match[0]["status"] == "FINALIZED", f"expected FINALIZED, got {match[0]['status']}"


# ─── Corner/endpoints/engagement_create_nonexistent_vendor_returns_not_found ─
def test_engagement_with_nonexistent_vendor_returns_not_found(api):
    """PRD §2.8: "Existence of every referenced resource is checked next: all path and body
    identifiers are resolved left to right, and the first that does not exist yields
    `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/endpoints/engagement_create_nonexistent_vendor_returns_not_found
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    sr = intake_request(ctx, category="BOOKING", title="r")
    resp = api.create_engagement(sr["id"], {
        "vendor_id": NON_EXISTENT_UUID, "billing_mode": "MARKUP", "markup_pct": 0.10,
        "estimated_cost_lines": [1000],
        "service_start": "2026-03-06T10:00:00Z", "service_end": "2026-03-06T11:00:00Z"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ─── Corner/rbac/member_cannot_close_billing_cycle_forbidden ────────────────
def test_member_cannot_close_billing_cycle(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/member_cannot_close_billing_cycle_forbidden
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")
    cycle = get_open_cycle(ctx["ms_id"])
    resp = api.close_billing_cycle(cycle["id"], ctx["member_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── Corner/rbac/concierge_agent_cannot_create_member_forbidden ─────────────
def test_concierge_agent_cannot_create_member(api):
    """PRD §2.1: "When the headers are well-formed but the named role is not permitted to
    invoke the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/concierge_agent_cannot_create_member_forbidden
    """
    resp = api.create_member({"full_name": "X", "email": "x@x.com"}, AGENT)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


# ─── Corner/rbac/member_not_owner_of_membership_forbidden ───────────────────
def test_member_cannot_intake_on_foreign_membership(api):
    """PRD §2.1: "A `Member` acting on a resource owned by a different member is rejected
    with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/member_not_owner_of_membership_forbidden
    """
    ctx = setup_membership(vip_tier="STANDARD", plan_kind="STD")  # owned by member A
    member_b, _ = create_active_member()
    resp = api.create_service_request(
        {"membership_id": ctx["ms_id"], "category": "ERRAND", "title": "sneaky"},
        make_member_headers(member_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ─── Corner/rbac/missing_role_header_returns_unauthenticated ────────────────
def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` does not name a role the
    system recognizes, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    headers = {"X-User-ID": "someone", "Content-Type": "application/json"}  # no X-User-Role
    resp = api.create_member({"full_name": "NoRole", "email": "norole@x.com"}, headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ─── Corner/cross-cutting complexity layers/occ_stale_member_version_on_membership_create ─
def test_membership_create_with_stale_member_version_rejected(api):
    """PRD §2.7: "if `expected_member_version` does not equal the target member's current
    `version`, the request is rejected with `ERR_STALE_MEMBER_VERSION` (HTTP 412),
    preventing the caller from acting on a member snapshot that has since advanced."
    PRD §2.4: "The `version` field is an integer that begins at 1 on creation and
    increments by 1 on every mutation of the resource; it also underpins optimistic
    concurrency control where applicable."

    Design: Corner/cross-cutting complexity layers/occ_stale_member_version_on_membership_create
    """
    member, version = create_active_member()  # version == 2 after activate mutation
    plan = create_plan(plan_kind="STD")
    # Passing the stale pre-activation version 1 (current is 2) must be rejected.
    assert version == 2, f"activated member version should be 2, got {version}"
    resp = api.create_membership(
        member["id"], create_membership_payload(plan["id"], expected_member_version=1, vip_tier="STANDARD"), AM)
    validate_error(resp, ApiErrorId.ERR_STALE_MEMBER_VERSION.value)


# ─── Corner/cross-cutting complexity layers/occ_member_version_increments_on_activate ─
def test_member_version_increments_on_activate(api):
    """PRD §2.4: "The `version` field is an integer that begins at 1 on creation and
    increments by 1 on every mutation of the resource; it also underpins optimistic
    concurrency control where applicable."

    Design: Corner/cross-cutting complexity layers/occ_member_version_increments_on_activate
    """
    member = validate_success(api.create_member({"full_name": "Vinc", "email": "vinc@x.com"}, AM),
                              expected_status=201)
    assert member["version"] == 1, f"expected version 1 at create, got {member['version']}"
    activated = validate_success(api.activate_member(member["id"], AM))
    assert activated["version"] == 2, f"expected version 2 after activate, got {activated['version']}"
